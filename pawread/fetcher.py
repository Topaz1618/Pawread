"""Pawread 的文件下载与校验。

**职责**：把候选条目变成 `books/` 里的实际文件。

**来源**：早先的 `fetch_pawread_books.py` 与 `verify_pawread_books.py`
是独立脚本，无法被包内模块 import。被流水线实际用到的部分已抽到这里，
让 `pawread` 包自洽 —— 原脚本保留在 `tools/legacy/` 作对照。

**要点**：
- 下载失败重试三次。住宅代理传大文件时偶发
  `DECRYPTION_FAILED_OR_BAD_RECORD_MAC`
- 连接层失败时重建会话以更换 SmartProxy 出口 IP ——
  同一出口重发无效，换 IP 才有机会绕开被拒的站点
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import subprocess
import time
import urllib.parse
import zipfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from .env import get_str, load_env

#: SmartProxy 网关默认端口。
DEFAULT_PROXY_PORT = 3120

#: 会话保持时间（分钟）。会话过期后同一 IP 会失效。
DEFAULT_SESSION_LIFE = 30

#: 随机标识的字母表（去掉易混淆字符）。
_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Safari/537.36")

#: 抽取正文时取前多少页 —— 校验只需要开头部分。
HEAD_PAGES = 12

#: 项目根目录。凭据文件在 `config/` 下。
ROOT = Path(__file__).resolve().parent.parent


def download(session: requests.Session, url: str, dest: Path) -> Optional[Dict[str, Any]]:
    """下载单个文件并计算校验和。

    下载失败重试三次。住宅代理在传输大文件时偶发
    `DECRYPTION_FAILED_OR_BAD_RECORD_MAC`，重试可正常完成。

    连接层失败（`ProxyError`、`ConnectionError`、`Timeout`）时，
    重建会话以更换 SmartProxy 出口 IP 后重试 —— 同一出口重发无效，
    换 IP 才有机会绕开被拒的目标站点。

    Args:
        session: 已配置代理的会话。
        url: 下载地址。
        dest: 目标路径。

    Returns:
        含 `path`、`bytes`、`sha256` 的字典；失败时返回 None。
    """
    for attempt in range(3):
        try:
            resp = session.get(url, timeout=180, stream=True)
            if resp.status_code != 200:
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))
                    continue
                return None
            dest.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            total = 0
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    digest.update(chunk)
                    total += len(chunk)
            if total < 10000:
                safe_unlink(dest)
                return None
            return {"path": str(dest), "bytes": total,
                    "sha256": digest.hexdigest()}
        except Exception as exc:  # noqa: BLE001 - 下载失败需重试
            print(f"      下载异常 第 {attempt + 1} 次: {type(exc).__name__}: {exc}")
            safe_unlink(dest)
            if attempt < 2:
                if isinstance(exc, (requests.exceptions.ProxyError,
                                    requests.exceptions.ConnectionError,
                                    requests.exceptions.Timeout)):
                    session = make_session()
                time.sleep(3 * (attempt + 1))
    return None


def make_session(session_id: Optional[str] = None) -> requests.Session:
    """构造走 SmartProxy 的会话。

    `trust_env = False` 使 `requests` 忽略环境里的代理设置，
    因此只有代码里显式给出的 `proxies` 生效，系统代理不会被使用。

    Args:
        session_id: 指定 SmartProxy 会话 ID，决定出口 IP。
            缺省时生成随机 ID。连接失败需要换出口时，
            用新 ID 重建会话即可。

    Returns:
        已配置代理的会话对象。
    """
    load_env_local()
    proxy = smartproxy_proxy_url(session_id)
    session = requests.Session()
    session.trust_env = False
    session.proxies = {"http": proxy, "https": proxy}
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
    })
    return session


def safe_unlink(path: Path) -> None:
    """删除文件，文件不存在时不报错。

    Args:
        path: 待删除的文件路径。

    Returns:
        无。
    """
    try:
        path.unlink()
    except OSError:
        pass


def ia_metadata(session: requests.Session, identifier: str) -> Optional[Dict[str, Any]]:
    """读取条目元数据。

    Args:
        session: 已配置代理的会话。
        identifier: 条目标识符。

    Returns:
        元数据字典；失败时返回 None。
    """
    resp = get(session, f"https://archive.org/metadata/{identifier}")
    if resp is None or resp.status_code != 200:
        return None
    try:
        return resp.json()
    except ValueError:
        return None


def pick_file(metadata: Dict[str, Any], title: str = "") -> Optional[Dict[str, Any]]:
    """从条目文件列表里挑出优先下载项。

    排除受借阅限制的条目、排除日志与元数据文件。
    同一条目里可能收录多本书，此时优先选文件名与目标书名相符的文件。
    同名文件按 PDF > EPUB > 纯文本的优先级排序，同格式内取体积较大者。

    Args:
        metadata: `ia_metadata` 的返回值。
        title: 目标书名。缺省时不按文件名过滤。

    Returns:
        选中的文件描述；无可用项时返回 None。
    """
    if metadata.get("metadata", {}).get("access-restricted-item"):
        return None
    usable: List[Dict[str, Any]] = []
    for f in metadata.get("files", []):
        name = f.get("name", "")
        fmt = (f.get("format") or "").lower()
        if "/" in name or fmt in {"log", "json", "xml", "marc", "marc binary",
                                  "dublin core", "item cdx index", "item cdx meta-index",
                                  "web archive gz", "chocr",
                                  "single page original jp2 tar"}:
            continue
        if not name.lower().endswith((".pdf", ".epub", ".txt")):
            continue
        size = int(f.get("size") or 0)
        if size < 20000:
            continue
        usable.append({"name": name, "format": fmt, "size": size})
    if not usable:
        return None

    title_key = norm(title)

    def rank(f: Dict[str, Any]) -> tuple:
        name = f["name"].lower()
        if name.endswith(".pdf"):
            tier = 0
        elif name.endswith(".epub"):
            tier = 1
        elif name.endswith(".txt"):
            tier = 2
        else:
            tier = 3
        # 排除 `_text.pdf` 这类节选派生件
        partial = 1 if ("_text." in name or "sample" in name) else 0
        # 文件名与书名相符的优先，避免选中条目里收录的另一本书
        name_hit = 0
        if title_key:
            stem = norm(name.rsplit(".", 1)[0])
            if title_key in stem:
                name_hit = 0
            elif stem and stem in title_key:
                name_hit = 0
            else:
                name_hit = 1
        return (tier, partial, name_hit, -f["size"])

    return sorted(usable, key=rank)[0]


def verify_file(path: Path, book: Dict[str, Any]) -> Dict[str, Any]:
    """校验单个已下载文件。

    PDF 有文本层时直接判定；没有文本层时标记为无法自动判定，
    并给出页数与体积供人工确认。

    Args:
        path: 文件路径。
        book: 书目条目。

    Returns:
        含 `status`、`pages`、`bytes`、`detail` 的字典。
        `status` 取值：`ok`、`wrong`、`no_text_layer`、`missing`。
    """
    result: Dict[str, Any] = {
        "file": path.name,
        "status": "missing",
        "pages": 0,
        "bytes": path.stat().st_size if path.exists() else 0,
        "detail": "",
    }
    if not path.exists():
        result["detail"] = "文件不存在"
        return result

    if path.exists():
        result["pages"] = pdf_pages(path)
    text = file_text(path)
    if text.strip():
        check = check_text(text, book["title"], book.get("author", ""))
        total = len(title_tokens(book["title"]))
        result["title_hit"] = check["title_hit"]
        result["title_ratio"] = check["title_ratio"]
        result["author_hit"] = check["author_hit"]
        # 作者命中且关键词命中至少一个，或关键词全中，或全部书名词都命中
        if check["author_hit"] and check["title_hit"] >= 1:
            result["status"] = "ok"
            result["detail"] = (f"作者命中，书名关键词命中 "
                                f"{check['title_hit']}/{total} 个")
        elif check["title_hit"] == total and total >= 1:
            result["status"] = "ok"
            result["detail"] = f"书名关键词全部命中（{total} 个）"
        elif check["title_ratio"] >= 0.66 and total >= 2:
            result["status"] = "ok"
            result["detail"] = (f"书名关键词命中 "
                                f"{check['title_hit']}/{total} 个")
        elif total >= 2 and check["title_hit"] >= 1 and result["pages"] >= 100:
            # 部分书的扉页不含完整书名，但正文页数充足且至少一个关键词出现
            result["status"] = "ok"
            result["detail"] = (f"书名关键词命中 "
                                f"{check['title_hit']}/{total} 个，"
                                f"共 {result['pages']} 页")
        else:
            result["status"] = "wrong"
            result["detail"] = (
                f"书名关键词仅命中 {check['title_hit']}/{total} 个，"
                "判定为非目标书")
        return result

    result["status"] = "no_text_layer"
    # 图像扫描件：渲染首页后用 OCR 判定
    if path.suffix.lower() == ".pdf":
        ocr = ocr_head(path)
        if ocr.strip():
            check = check_text(ocr, book["title"], book.get("author", ""))
            total = len(title_tokens(book["title"]))
            result["title_hit"] = check["title_hit"]
            result["title_ratio"] = check["title_ratio"]
            result["author_hit"] = check["author_hit"]
            if (check["title_hit"] >= max(1, total - 1)
                    or check["author_hit"]):
                result["status"] = "ok"
                result["detail"] = (f"OCR 识别：书名关键词命中 "
                                    f"{check['title_hit']}/{total} 个"
                                    + ("，作者命中" if check["author_hit"] else ""))
                return result
            result["status"] = "wrong"
            result["detail"] = (f"OCR 识别：书名关键词仅命中 "
                                f"{check['title_hit']}/{total} 个")
            return result
    result["detail"] = (f"{result['pages']} 页，无文本层（图像扫描件），"
                        "需人工或 OCR 确认")
    return result


def load_env_local() -> None:
    """从 `config/env.local` 补齐缺失的环境变量（不覆盖已有值）。

    只加载 `SMARTPROXY_*` 系列的键。

    Returns:
        无。
    """
    load_env(prefixes=("SMARTPROXY_",))


def smartproxy_proxy_url(session_id: Optional[str] = None) -> str:
    """生成 SmartProxy 住宅代理 URL。

    代理地址形如
    `http://smart-{账号}_area-{国家}_life-{时长}_session-{会话ID}:{密码}@{网关}:{端口}`。
    会话 ID 决定出口 IP，同一 ID 在有效期内保持同一 IP，
    每次调用生成新 ID，因此天然分散到不同出口。

    Args:
        session_id: 指定会话 ID。缺省时生成随机 ID。

    Returns:
        代理 URL。

    Raises:
        RuntimeError: 凭据缺失时抛出，不做静默降级。
    """
    load_env_local()
    account = get_str("SMARTPROXY_ACCOUNT")
    password = get_str("SMARTPROXY_PASSWORD")
    if not account or not password:
        raise RuntimeError(
            "SmartProxy 凭据缺失。设置 SMARTPROXY_ACCOUNT / SMARTPROXY_PASSWORD "
            "环境变量，或写入 .env.local。"
        )
    host = get_str("SMARTPROXY_HOST", "us.smartproxy.net")
    port = get_str("SMARTPROXY_PORT", "3120")
    area = get_str("SMARTPROXY_AREA", "US")
    life = get_str("SMARTPROXY_LIFE", "30")
    if not session_id:
        session_id = uuid.uuid4().hex[:10]
    user = (f"smart-{account}_area-{area}_life-{life}"
            f"_session-{session_id}")
    return f"http://{user}:{password}@{host}:{port}"

#: 受借阅限制的合集。这些条目可检索到，但文件下载返回 401。
BORROW_COLLECTIONS = {"printdisabled", "inlibrary", "lendinglibrary"}

#: 明确排除的合集 —— 收录的是论文、期刊、年报，不是目标书籍。
EXCLUDED_COLLECTIONS = {
    "arxiv", "journals", "journal", "bopcris", "eric", "biostor",
    "manualzilla", "annual-reports-archive", "whitneymuseum",
    "navalpostgraduateschoollibrary", "navalwarcollege", "pub_psychology",
    "dtic", "defensetechnicalinformationcenter", "npsarchive",
}

#: 明确排除的条目标识前缀。
EXCLUDED_PREFIXES = ("arxiv-", "10.", "MMU", "cia-readingroom", "response-to-",
                      "DTIC_", "nps-")

#: 人工确认的 Internet Archive 条目直链。
#: 这些条目由逐条排查确定，标题检索匹配不到或会被同名论文抢先。
#: 键为书目序号，值为 `(条目标识符, 文件名)`。
IA_MANUAL: Dict[int, Tuple[str, str]] = {
    2: ("peterbevelinseekingwisdomfromdarwintomunzlib.org",
        "[Peter_Bevelin]_Seeking_Wisdom__From_Darwin_to_Mun(z-lib.org).pdf"),
    33: ("in.ernet.dli.2015.138758",
         "2015.138758.Organizational-Behavior.pdf"),
}

#: 《Forecasting: Principles and Practice》第三版的章节文件名。
#: 站点目录页对住宅代理返回 403，章节清单由此处固定给出。
FPP3_CHAPTERS = [
    "intro", "preface", "forecasting", "judgmental", "regression",
    "dynamic-regression", "arima", "exponential-smoothing", "decomposition",
    "hierarchical-forecasting", "advanced", "graphics", "practical",
    "toolbox", "features", "authors", "references", "changelog",
]

#: 书目清单。`direct` 为已确认的免费全文直链，`pages` 为期望页数区间。
BOOKS: List[Dict[str, Any]] = [
    {"n": 1, "title": "Poor Charlie's Almanack", "author": "Charles T. Munger",
     "pages": (200, 900)},
    {"n": 2, "title": "Seeking Wisdom: From Darwin to Munger",
     "author": "Peter Bevelin", "pages": (100, 500)},
    {"n": 3, "title": "Good Strategy Bad Strategy", "author": "Richard Rumelt",
     "pages": (150, 500)},
    {"n": 4, "title": "The Art of Strategy", "author": "Sun Tzu",
     "pages": (150, 500)},
    {"n": 5, "title": "Superforecasting", "author": "Philip Tetlock",
     "pages": (150, 600)},
    {"n": 6, "title": "Thinking in Systems", "author": "Donella H. Meadows",
     "pages": (150, 400)},
    {"n": 7, "title": "The Social Animal", "author": "Elliot Aronson",
     "pages": (150, 600)},
    {"n": 8, "title": "Influence: The Psychology of Persuasion",
     "author": "Robert B. Cialdini", "pages": (150, 500)},
    {"n": 9, "title": "Financial Intelligence for Entrepreneurs",
     "author": "", "pages": (100, 500)},
    {"n": 10, "title": "The Psychology of Money", "author": "Morgan Housel",
     "pages": (150, 400)},
    {"n": 11, "title": "Difficult Conversations", "author": "",
     "pages": (150, 600)},
    {"n": 12, "title": "Never Split the Difference", "author": "Chris Voss",
     "pages": (150, 400)},
    {"n": 13, "title": "Playing to Win", "author": "Roger L. Martin",
     "pages": (150, 400)},
    {"n": 14, "title": "Principles of Corporate Finance", "author": "",
     "pages": (500, 3000)},
    {"n": 15, "title": "The Intelligent Investor", "author": "Benjamin Graham",
     "pages": (200, 800)},
    {"n": 16, "title": "Competitive Strategy", "author": "Michael E. Porter",
     "pages": (200, 900)},
    {"n": 17, "title": "The Innovator's Dilemma", "author": "Clayton Christensen",
     "pages": (150, 600)},
    {"n": 18, "title": "The Effective Executive", "author": "Peter Drucker",
     "pages": (100, 500)},
    {"n": 19, "title": "High Output Management", "author": "Andrew S. Grove",
     "pages": (150, 500)},
    {"n": 20, "title": "Getting to Yes", "author": "Roger Fisher",
     "pages": (150, 500)},
    {"n": 21, "title": "Thinking in Bets", "author": "Annie Duke",
     "pages": (150, 500)},
    {"n": 22, "title": "The Interpretation of Financial Statements",
     "author": "", "pages": (150, 600)},
    {"n": 23, "title": "A Random Walk Down Wall Street", "author": "Burton Malkiel",
     "pages": (200, 800)},
    {"n": 24, "title": "The Ascent of Money", "author": "Niall Ferguson",
     "pages": (200, 900)},
    {"n": 25, "title": "Manias, Panics, and Crashes", "author": "Charles Kindleberger",
     "pages": (200, 800)},
    {"n": 26, "title": "The Righteous Mind", "author": "Jonathan Haidt",
     "pages": (200, 800)},
    {"n": 27, "title": "Games People Play", "author": "Eric Berne",
     "pages": (150, 500)},
    {"n": 28, "title": "Mistakes Were Made (But Not by Me)",
     "author": "Elliot Aronson", "pages": (200, 600)},
    {"n": 29, "title": "Predictably Irrational", "author": "Dan Ariely",
     "pages": (150, 500)},
    {"n": 30, "title": "Why We Buy", "author": "Joseph B. Pine II",
     "pages": (100, 400)},
    {"n": 31, "title": "The Choice Factory", "author": "Sheena Iyengar",
     "pages": (100, 400)},
    {"n": 32, "title": "The Laws of Human Nature", "author": "Robert Greene",
     "pages": (300, 900)},
    {"n": 33, "title": "Organizational Behavior", "author": "Stephen P. Robbins",
     "pages": (400, 1200)},
    {"n": 34, "title": "The Human Side of Enterprise", "author": "Peter Drucker",
     "pages": (150, 600)},
    {"n": 35, "title": "The Beginning of Infinity", "author": "David Deutsch",
     "pages": (300, 900)},
    {"n": 36, "title": "The Lessons of History", "author": "Will Durant",
     "pages": (100, 400)},
    {"n": 37, "title": "The 33 Strategies of War", "author": "Robert Greene",
     "pages": (300, 900)},
    {"n": 38, "title": "The Art of War", "author": "Sun Tzu",
     "pages": (100, 500),
     "direct": "https://www.gutenberg.org/ebooks/17405"},
    {"n": 39, "title": "The Hard Thing About Hard Things", "author": "Ben Horowitz",
     "pages": (150, 500)},
    {"n": 40, "title": "The Mythical Man-Month", "author": "Frederick Brooks",
     "pages": (150, 400)},
    {"n": 41, "title": "Making Things Happen", "author": "Scott Berkun",
     "pages": (150, 500)},
    {"n": 42, "title": "Scrum", "author": "Jeff Sutherland", "pages": (100, 600)},
    {"n": 43, "title": "How to Win Friends and Influence People",
     "author": "Dale Carnegie", "pages": (150, 600)},
    {"n": 44, "title": "The 48 Laws of Power", "author": "Robert Greene",
     "pages": (300, 900)},
    {"n": 45, "title": "Made to Stick", "author": "Chip Heath",
     "pages": (150, 500)},
    {"n": 46, "title": "Crucial Conversations", "author": "Kerry Patterson",
     "pages": (150, 500)},
    {"n": 47, "title": "The Selfish Gene", "author": "Richard Dawkins",
     "pages": (200, 700)},
    {"n": 48, "title": "Business Cycles", "author": "Joseph Schumpeter",
     "pages": (300, 900)},
    {"n": 49, "title": "The Great Wave", "author": "David Hackett Fischer",
     "pages": (150, 600)},
    {"n": 50, "title": "The Rise and Fall of the Great Powers", "author": "Paul Kennedy",
     "pages": (500, 1500)},
    {"n": 51, "title": "The Clash of Civilizations and the Remaking of World Order",
     "author": "Samuel P. Huntington", "pages": (400, 1200)},
    {"n": 52, "title": "The Limits to Growth", "author": "Donella H. Meadows",
     "pages": (50, 300),
     "direct": "https://www.donellameadows.org/wp-content/userfiles/"
               "Limits-to-Growth-digital-scan-version.pdf"},
    {"n": 53, "title": "The Fourth Turning", "author": "William Strauss",
     "pages": (200, 700)},
    {"n": 54, "title": "The Age of Spiritual Machines", "author": "Ray Kurzweil",
     "pages": (200, 900)},
    {"n": 55, "title": "The Next 100 Years", "author": "George Friedman",
     "pages": (200, 700)},
    {"n": 56, "title": "The Signal and the Noise", "author": "Nate Silver",
     "pages": (200, 800)},
    {"n": 57, "title": "Forecasting: Principles and Practice",
     "author": "Rob J. Hyndman", "pages": (100, 1000),
     "direct": "https://otexts.com/fpp3/"},
    {"n": 58, "title": "Yesterday's Tomorrows", "author": "Robert J. Shikes",
     "pages": (100, 400)},
    {"n": 59, "title": "The Kondratieff Waves", "author": "Nathan Mager",
     "pages": (100, 500)},
]

#: 校验正文时抽取的页数。扉页、版权页、目录通常在前几页。
VERIFY_HEAD_PAGES = 25

#: 判定停用词。标题里这些词不参与正文匹配。
STOPWORDS = {"the", "a", "an", "of", "and", "to", "in", "for", "on",
             "with", "from", "by", "at", "as", "is", "how", "why", "what"}


def norm(text: str) -> str:
    """把文本规范化，用于标题与作者比对。

    Args:
        text: 原始文本。

    Returns:
        小写、仅含字母数字与空格的字符串。
    """
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def title_tokens(title: str) -> List[str]:
    """把书名拆成用于正文比对的关键词。

    Args:
        title: 书名。

    Returns:
        关键词列表，已剔除停用词与过短的词。
    """
    words = re.findall(r"[A-Za-z0-9]+", title.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 2]


def pdf_pages(path: Path) -> int:
    """读取 PDF 页数。

    Args:
        path: PDF 路径。

    Returns:
        页数；读取失败时返回 0。
    """
    try:
        out = subprocess.run(["pdfinfo", str(path)], capture_output=True,
                             text=True, timeout=60)
        match = re.search(r"^Pages:\s+(\d+)", out.stdout or "", re.M)
        return int(match.group(1)) if match else 0
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0



def ocr_head(path: Path, pages: int = 4) -> str:
    """用 OCR 抽取 PDF 前若干页的文字。

    图像扫描件没有文本层，只能渲染成图片后交给 `tesseract` 识别。
    依赖 `pdftoppm` 与 `tesseract` 两个命令行工具，缺失时返回空字符串。

    Args:
        path: PDF 路径。
        pages: 抽取页数。

    Returns:
        OCR 识别出的文本；工具缺失或执行失败时返回空字符串。
    """
    import shutil
    import tempfile

    if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
        return ""
    with tempfile.TemporaryDirectory() as tmp:
        prefix = os.path.join(tmp, "page")
        try:
            subprocess.run(["pdftoppm", "-f", "1", "-l", str(pages),
                            "-r", "150", "-jpeg", str(path), prefix],
                           capture_output=True, timeout=180)
        except (OSError, subprocess.SubprocessError):
            return ""
        chunks: List[str] = []
        for image in sorted(Path(tmp).glob("page*.jpg")):
            try:
                out = subprocess.run(["tesseract", str(image), "stdout"],
                                     capture_output=True, text=True,
                                     timeout=120, cwd=tmp)
                chunks.append(out.stdout or "")
            except (OSError, subprocess.SubprocessError):
                continue
        return "\n".join(chunks)


def file_text(path: Path) -> str:
    """按文件类型抽取文本。

    Args:
        path: 文件路径。

    Returns:
        抽取到的文本；类型不支持时返回空字符串。
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return pdf_text(path)
    if suffix == ".epub":
        return epub_text(path)
    if suffix == ".txt":
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    return ""


def check_text(text: str, title: str, author: str) -> Dict[str, Any]:
    """在一段正文里查找书名关键词与作者。

    书名关键词只要多数出现即判定命中；作者姓氏出现作为加分证据。

    Args:
        text: 待检查的正文。
        title: 目标书名。
        author: 目标作者。

    Returns:
        含 `title_hit`、`title_ratio`、`author_hit`、`matched` 的字典。
    """
    lowered = text.lower()
    tokens = title_tokens(title)
    hits = [t for t in tokens if t in lowered]
    ratio = len(hits) / len(tokens) if tokens else 0.0
    author_hit = False
    if author:
        surname = re.split(r"\s+", author.strip())[-1].lower()
        if len(surname) > 3:
            author_hit = surname in lowered
        else:
            # 姓氏过短时用名字的前若干字符判断，例如 "Ray" → "ray"
            first = author.strip().split()[0].lower()
            if len(first) > 2:
                author_hit = first in lowered
    return {
        "title_hit": len(hits),
        "title_ratio": round(ratio, 3),
        "author_hit": author_hit,
        "matched": ratio >= 0.6,
    }



def pdf_text(path: Path, pages: int = HEAD_PAGES) -> str:
    """抽取 PDF 前若干页的文本。

    Args:
        path: PDF 路径。
        pages: 抽取页数。

    Returns:
        抽取到的文本；文件不可读时返回空字符串。
    """
    try:
        out = subprocess.run(
            ["pdftotext", "-f", "1", "-l", str(pages), str(path), "-"],
            capture_output=True, text=True, timeout=120)
        return out.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def epub_text(path: Path, max_files: int = 12) -> str:
    """抽取 EPUB 前若干个章节文件的文字。

    章节顺序按 EPUB 规范读取：优先用 spine 顺序；spine 不可用时
    退回文件名排序。

    Args:
        path: EPUB 路径。
        max_files: 最多读取的章节文件数。

    Returns:
        拼接后的文本；文件不可读时返回空字符串。
    """
    import html

    try:
        with zipfile.ZipFile(path) as archive:
            names = epub_spine_order(archive)
            if not names:
                names = sorted(n for n in archive.namelist() if n.endswith(".html"))
            chunks: List[str] = []
            for name in names[:max_files]:
                try:
                    raw = archive.read(name).decode("utf-8", "replace")
                except (KeyError, OSError):
                    continue
                plain = re.sub(r"<[^>]+>", " ", raw)
                chunks.append(html.unescape(plain))
            return re.sub(r"\s+", " ", " ".join(chunks))
    except (OSError, zipfile.BadZipFile):
        return ""



def epub_spine_order(archive: zipfile.ZipFile) -> List[str]:
    """按 EPUB 规范读取 spine 顺序的章节文件名。

    EPUB 的阅读顺序由 `META-INF/container.xml` 指向的 OPF 文件里的
    `<spine>` 决定，**不是文件名排序**。文件名排序会把
    `chapter10.xhtml` 排到 `chapter2.xhtml` 前面，读出来的正文顺序是错的。

    Args:
        archive: 已打开的 EPUB 压缩包。

    Returns:
        按 spine 顺序排列的章节文件名；解析失败时返回空列表。
    """
    import xml.etree.ElementTree as ET

    try:
        container = ET.fromstring(archive.read("META-INF/container.xml"))
    except (KeyError, OSError, ET.ParseError):
        return []

    opf_path = ""
    for rootf in container.iter():
        if rootf.tag.endswith("rootfile"):
            opf_path = rootf.attrib.get("full-path", "")
            if opf_path:
                break
    if not opf_path:
        return []

    try:
        opf = ET.fromstring(archive.read(opf_path))
    except (KeyError, OSError, ET.ParseError):
        return []

    base = os.path.dirname(opf_path)

    manifest: Dict[str, str] = {}
    for elem in opf.iter():
        if elem.tag.endswith("item") and elem.attrib.get("id"):
            manifest[elem.attrib["id"]] = elem.attrib.get("href", "")

    ordered: List[str] = []
    for elem in opf.iter():
        if not elem.tag.endswith("itemref"):
            continue
        href = manifest.get(elem.attrib.get("idref", ""))
        if not href:
            continue
        full = os.path.normpath(os.path.join(base, href)).replace(os.sep, "/")
        if full in archive.namelist():
            ordered.append(full)
    return ordered
