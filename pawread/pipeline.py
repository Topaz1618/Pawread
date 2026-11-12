"""Pawread 主流程。

**职责**：把七个环节串成一条可运行的流水线。

```
粘贴书单
  ↓ [1] 解析      文本 → BookRequest[]
  ↓ [2] 规范化    LLM：中文书名 → 英文标题 / 作者 / 检索词
  ↓ [3] 发现      站点适配器检索 → 候选资源（含站点级失败归因）
  ↓ [4] 下载      SmartProxy 下载
  ↓ [5] 校验      内容校验，防同名论文冒充
  ↓ [6] 读书      按章切块 → LLM 笔记 → Markdown
  ↓ [7] 报告      成功清单 + 下载不到的原因清单
```

**与既有脚本的关系**：下载、校验、代理会话直接 `import` 包内的
`pawread.fetcher` 实现，不复制粘贴。

**上游**：`pawread/cli.py`。
**下游**：用户（CLI 输出与笔记文件）。
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .discover import discover
from .extract import build_chunks
from .llm import LLMClient
from .logging_setup import RunLogger
from .reader import BookNotes, merge_notes, read_chunks
from .sources import load_booklist

#: 项目根目录。
ROOT = Path(__file__).resolve().parent.parent

#: 书籍目录。
BOOKS_DIR = ROOT / "books"

#: 笔记目录。
NOTES_DIR = ROOT / "notes"

#: 清单文件。既有清单由 `pawread.fetcher` 维护，格式是
#: `{n, title, author, status, file, ...}`；本模块的运行结果格式不同
#: （以 `request` 嵌套），因此**写到独立文件**，不覆盖既有清单。
MANIFEST = BOOKS_DIR / "manifest.json"

#: 本流程的运行结果清单。
RUN_MANIFEST = BOOKS_DIR / "pipeline_manifest.json"

#: 书单解析：切出每一行书名与可能的 URL。
BOOK_LINE = re.compile(
    r"^\s*(?:\d+[.、)]\s*)?(?P<title>[^\n|]{2,120}?)"
    r"(?:\s*\|\s*(?P<url>https?://\S+))?\s*$")


@dataclass
class BookRequest:
    """一个待处理的书目请求。

    字段:
        n: 序号。
        title: 原始书名（可能是中文）。
        author: 作者，未知时为空串。
        entry_url: 用户给的检索入口地址。
        normalized_title: 规范化后的英文标题。
        normalized_author: 规范化后的作者。
        search_terms: 检索关键词列表。
    """

    n: int
    title: str
    author: str = ""
    entry_url: str = ""
    normalized_title: str = ""
    normalized_author: str = ""
    search_terms: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转为可 JSON 序列化的字典。

        Returns:
            书目请求字典。
        """
        return {
            "n": self.n,
            "title": self.title,
            "author": self.author,
            "entry_url": self.entry_url,
            "normalized_title": self.normalized_title,
            "normalized_author": self.normalized_author,
            "search_terms": self.search_terms,
        }


@dataclass
class BookOutcome:
    """一本书的最终结果。

    字段:
        request: 书目请求。
        status: `downloaded` / `not_found` / `failed` / `skipped`。
        file: 下载到的文件路径。
        source: 来源站点。
        source_url: 来源地址。
        note_path: 笔记文件路径。
        reasons: 下载不到的原因（站点级）。
        candidates: 候选资源列表。
        verify: 校验结论。
    """

    request: BookRequest
    status: str = "not_found"
    file: Optional[str] = None
    source: str = ""
    source_url: str = ""
    note_path: Optional[str] = None
    reasons: List[Dict[str, Any]] = field(default_factory=list)
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    verify: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转为可 JSON 序列化的字典。

        Returns:
            结果字典。
        """
        return {
            "request": self.request.to_dict(),
            "status": self.status,
            "file": self.file,
            "source": self.source,
            "source_url": self.source_url,
            "note_path": self.note_path,
            "reasons": self.reasons,
            "candidates": self.candidates,
            "verify": self.verify,
        }


def parse_booklist(text: str) -> List[BookRequest]:
    """把粘贴的书单文本解析成书目请求。

    支持三种输入：
    - 每行一个书名
    - 带序号的列表（`1. 书名`）
    - 表格行（`书名 | https://...`）

    Args:
        text: 用户粘贴的文本。

    Returns:
        书目请求列表。
    """
    requests: List[BookRequest] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2 and parts[1].startswith("http"):
                title, url = parts[0], parts[1]
                author = ""
                if " - " in title:
                    title, author = title.split(" - ", 1)
                requests.append(BookRequest(
                    n=len(requests) + 1, title=title.strip(),
                    author=author.strip(), entry_url=url))
                continue
        match = BOOK_LINE.match(line)
        if not match:
            continue
        title = match.group("title").strip()
        if not title:
            continue
        requests.append(BookRequest(
            n=len(requests) + 1, title=title,
            entry_url=match.group("url") or ""))
    return requests


def normalize_titles(client: LLMClient,
                     requests: List[BookRequest]) -> List[BookRequest]:
    """用 LLM 把书名规范化。

    中文书名在英文站点上搜不到 —— 「深度工作」要变成
    `Deep Work Cal Newport` 才能命中。LLM 在这一步的价值是
    **把书名翻译成目标站点的检索语言**，而不是给下载链接
    （它会给，但给的是借阅件，不可下载）。

    Args:
        client: LLM 客户端。
        requests: 书目请求列表，就地更新。

    Returns:
        更新后的书目请求列表。
    """
    for req in requests:
        if not req.title:
            continue
        prompt = (
            "把下面的书名转成适合在英文电子书站点检索的形式。"
            "只输出 JSON，不要解释。\n\n"
            "输出格式："
            '{"title_en":"英文标题","author":"作者英文名",'
            '"terms":["检索词1","检索词2"]}\n\n'
            "规则：\n"
            "- 已经是英文的书名，title_en 保持原样\n"
            "- 中文书名译成英文原标题\n"
            "- author 留空字符串如果不知道\n"
            "- terms 给出 2-3 个检索关键词（含可能的副标题变体）\n\n"
            f"书名：{req.title}\n"
            + (f"已知作者：{req.author}\n" if req.author else ""))
        try:
            payload, _ = client.complete_json(
                prompt, max_tokens=500, temperature=0.1)
        except Exception:  # noqa: BLE001 - 规范化失败不阻断流程
            req.normalized_title = req.title
            continue
        if not isinstance(payload, dict):
            req.normalized_title = req.title
            continue
        req.normalized_title = (payload.get("title_en")
                                or req.title).strip()
        req.normalized_author = (payload.get("author") or "").strip()
        terms = payload.get("terms") or []
        req.search_terms = [str(t).strip() for t in terms if str(t).strip()]
    return requests


def _mostly_ascii(text: str) -> bool:
    """判断文本是否基本都是 ASCII（即可直接用英文站点检索）。

    Args:
        text: 原始文本。

    Returns:
        基本是 ASCII 时返回 True。
    """
    if not text:
        return True
    ascii_count = sum(1 for ch in text if ord(ch) < 128)
    return ascii_count / len(text) >= 0.8


def _slug(title: str) -> str:
    """把书名转成安全的文件名主干。

    Args:
        title: 书名。

    Returns:
        仅含字母、数字与下划线的字符串。
    """
    return re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_")[:80]


def find_existing_file(title: str) -> Optional[Path]:
    """在书籍目录里找已有的文件。

    Args:
        title: 书名。

    Returns:
        文件路径；没有时返回 None。
    """
    slug = _slug(title)
    for ext in (".pdf", ".epub", ".txt"):
        candidate = BOOKS_DIR / f"{slug}{ext}"
        if candidate.exists():
            return candidate
    return None


def write_manifest(outcomes: List[BookOutcome]) -> None:
    """把结果写入运行清单。

    写到 `books/pipeline_manifest.json`，**不覆盖** `books/manifest.json`
    —— 后者由 `pawread.fetcher` 维护，格式不同，覆盖会丢掉
    已下载书籍的原始记录。

    Args:
        outcomes: 各书结果。

    Returns:
        无。
    """
    payload = [o.to_dict() for o in outcomes]
    BOOKS_DIR.mkdir(parents=True, exist_ok=True)
    RUN_MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                             encoding="utf-8")


def render_report(outcomes: List[BookOutcome]) -> str:
    """生成给用户看的汇总报告。

    两块内容：成功清单与下载不到的原因清单。
    失败清单精确到站点与原因，不是笼统一句「未找到」——
    哪个站不可达、哪个站限流、哪个站搜到了但没匹配上，都分开写。

    Args:
        outcomes: 各书结果。

    Returns:
        报告文本。
    """
    ok = [o for o in outcomes if o.status == "downloaded"]
    bad = [o for o in outcomes if o.status != "downloaded"]

    lines = ["", "=" * 68, "Pawread 汇总报告", "=" * 68, ""]
    lines.append(f"成功 {len(ok)} / 共 {len(outcomes)}")
    lines.append("")

    if ok:
        lines.append("--- 成功清单 ---")
        for o in ok:
            lines.append(f"  [{o.request.n}] {o.request.title}")
            lines.append(f"      来源：{o.source}")
            lines.append(f"      文件：{o.file}")
            if o.note_path:
                lines.append(f"      笔记：{o.note_path}")
            lines.append("")

    if bad:
        lines.append("--- 下载不到的书 ---")
        for o in bad:
            lines.append(f"  [{o.request.n}] {o.request.title}")
            for reason in o.reasons:
                lines.append(f"      · {reason.get('site')}: "
                             f"{reason.get('error')}")
            if o.candidates:
                lines.append(f"      搜到 {len(o.candidates)} 个候选条目，"
                             "均未能取到可下载文件：")
                for cand in o.candidates[:4]:
                    title = (cand.get("title") or "")[:52]
                    extra = ""
                    meta = cand.get("meta") or {}
                    if meta.get("restricted"):
                        extra = " [受借阅限制]"
                    elif meta.get("public_domain"):
                        extra = " [公有领域]"
                    elif meta.get("ebook_access"):
                        extra = f" [访问:{meta['ebook_access']}]"
                    lines.append(f"        - {cand.get('site')}: "
                                 f"{title}{extra}")
                if len(o.candidates) > 4:
                    lines.append(f"        …… 另有 "
                                 f"{len(o.candidates) - 4} 个候选")
            lines.append("")

    lines.append("=" * 68)
    return "\n".join(lines)


def resolve_download_url(session: Any, candidate: Dict[str, Any],
                         title: str) -> Optional[str]:
    """把候选条目解析成实际可下载的文件地址。

    `discover.probe_downloadable` 已经查过条目元数据，候选的 `url`
    已经是文件地址。查不到时退回重新解析。

    Args:
        session: 已配置代理的会话。
        candidate: 候选条目。
        title: 目标书名。

    Returns:
        文件下载地址；解析不出时返回 None。
    """
    from .fetcher import ia_metadata, pick_file

    meta = candidate.get("meta") or {}
    if meta.get("file_name"):
        identifier = meta.get("identifier")
        if identifier:
            return ("https://archive.org/download/" + identifier + "/"
                    + urllib.parse.quote(meta["file_name"]))

    site = candidate.get("site", "")
    identifiers: List[str] = []
    if site == "archive.org":
        if meta.get("identifier"):
            identifiers.append(meta["identifier"])
    elif site == "openlibrary.org":
        identifiers.extend(meta.get("ia") or [])

    for identifier in identifiers:
        metadata = ia_metadata(session, identifier)
        if metadata is None:
            continue
        chosen = pick_file(metadata, title)
        if not chosen:
            continue
        return ("https://archive.org/download/" + identifier + "/"
                + urllib.parse.quote(chosen["name"]))
    return None


def download_candidate(session: Any, candidate: Dict[str, Any],
                       title: str, author: str, dest_dir: Path,
                       logger: RunLogger) -> Optional[Dict[str, Any]]:
    """下载一个候选资源并做内容校验。

    Args:
        session: 已配置代理的会话。
        candidate: 候选条目。
        title: 目标书名。
        author: 目标作者。
        dest_dir: 下载目录。
        logger: 日志记录器。

    Returns:
        下载结果字典；失败时返回 None。
    """
    from .fetcher import download, safe_unlink
    from .fetcher import verify_file

    url = resolve_download_url(session, candidate, title)
    if not url:
        logger.event("download", "skipped",
                     site=candidate.get("site"),
                     reason="无法解析出文件下载地址")
        return None

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{_slug(title)}{Path(url).suffix.lower() or '.pdf'}"
    result = download(session, url, dest)
    if not result:
        logger.event("download", "failed", site=candidate.get("site"),
                     url=url, reason="下载失败")
        return None

    check = verify_file(dest, {"title": title, "author": author})
    if check.get("status") != "ok":
        logger.event("download", "failed", site=candidate.get("site"),
                     url=url, reason=f"校验不通过：{check.get('detail')}")
        safe_unlink(dest)
        return None

    logger.event("download", "ok", site=candidate.get("site"), url=url,
                 file=str(dest), bytes=result.get("bytes"),
                 sha256=result.get("sha256"))
    result["verify"] = check
    result["source"] = candidate.get("site", "")
    result["source_url"] = url
    return result


def run_pipeline(requests: List[BookRequest],
                 logger: Optional[RunLogger] = None,
                 do_discover: bool = True,
                 do_read: bool = True,
                 max_chapters: Optional[int] = None,
                 max_downloads: int = 3,
                 do_merge: bool = True,
                 tier: str = "test") -> List[BookOutcome]:
    """跑完整流水线。

    Args:
        requests: 书目请求列表。
        logger: 日志记录器。缺省新建一个。
        do_discover: 是否执行发现与下载阶段。
        do_read: 是否执行读书阶段。
        max_chapters: 每本书最多读几章。缺省不限。
        max_downloads: 每本书最多尝试下载几个候选。
        do_merge: 是否生成全书整合笔记。
        tier: LLM 模型档位。

    Returns:
        各书结果列表。
    """
    from .fetcher import download, make_session

    own_logger = logger is None
    logger = logger or RunLogger()
    session = make_session()
    client = LLMClient(tier=tier)
    outcomes: List[BookOutcome] = []

    try:
        if do_discover:
            logger.event("pipeline", "ok", stage_detail="开始发现阶段",
                         books=len(requests))

        # 书名规范化：中文书名要先译成英文原标题才能在英文站点检索。
        # 只对「看起来不是英文」的书目做，省 token。
        need_normalize = [r for r in requests
                          if r.title and not _mostly_ascii(r.title)]
        if need_normalize:
            logger.event("normalize", "ok", count=len(need_normalize))
            normalize_titles(client, need_normalize)

        for req in requests:
            outcome = BookOutcome(request=req)
            started = time.monotonic()

            # 已有文件直接复用，不重复下载
            existing = find_existing_file(req.title) or \
                find_existing_file(req.normalized_title)
            if existing:
                outcome.status = "downloaded"
                outcome.file = str(existing)
                outcome.source = "本地已有"
                outcome.source_url = ""
                logger.event("book", "ok", n=req.n, title=req.title,
                             book_status="downloaded", file=str(existing),
                             source="本地已有")
            elif do_discover:
                title = req.normalized_title or req.title
                author = req.normalized_author or req.author
                found = discover(session, title, author, req.entry_url)
                logger.save_raw(f"discover_{req.n:03d}", found)
                outcome.candidates = found["candidates"]
                outcome.reasons = (found["failures"]
                                   + found["empty_sites"])
                logger.event(
                    "discover", "ok", n=req.n, title=title,
                    candidates=len(found["candidates"]),
                    failures=len(found["failures"]),
                    empty=len(found["empty_sites"]),
                    elapsed_ms=int((time.monotonic() - started) * 1000))

                # 逐个候选尝试下载
                for cand in found["candidates"][:max_downloads]:
                    got = download_candidate(session, cand, title, author,
                                             BOOKS_DIR, logger)
                    if got:
                        outcome.status = "downloaded"
                        outcome.file = got.get("path")
                        outcome.source = got.get("source", "")
                        outcome.source_url = got.get("source_url", "")
                        outcome.verify = got.get("verify", {})
                        logger.event("book", "ok", n=req.n, title=title,
                                     book_status="downloaded",
                                     file=outcome.file,
                                     source=outcome.source)
                        break
                    outcome.reasons.append({
                        "site": cand.get("site"),
                        "error": f"候选「{(cand.get('title') or '')[:40]}」"
                                 f"下载或校验失败",
                    })
            else:
                outcome.status = "skipped"
                outcome.reasons = [{"site": "-", "error": "未启用发现阶段"}]

            # 读书阶段
            if do_read and outcome.file:
                try:
                    chunks = build_chunks(Path(outcome.file))
                    notes = read_chunks(client, req.title, chunks,
                                        max_chunks=max_chapters)
                    # 全书整合：合并后的整体笔记
                    merged = ""
                    if do_merge:
                        merged = merge_notes(client, req.title, notes)
                        logger.event("merge", "ok", n=req.n,
                                     title=req.title,
                                     chars=len(merged))
                    book_notes = BookNotes(
                        title=req.title, chunks=notes, merged=merged,
                        stats={
                            "skipped": sum(1 for n in notes if n.skipped),
                            "total_tokens":
                                client.summary()["pool"]["total_tokens"],
                        })
                    NOTES_DIR.mkdir(parents=True, exist_ok=True)
                    note_path = NOTES_DIR / f"{_slug(req.title)}.md"
                    note_path.write_text(
                        book_notes.render_markdown(outcome.file),
                        encoding="utf-8")
                    outcome.note_path = str(note_path)
                    logger.event("read", "ok", n=req.n, title=req.title,
                                 chunks=len(chunks),
                                 written=sum(1 for n in notes
                                             if not n.skipped),
                                 note_path=str(note_path))
                except Exception as exc:  # noqa: BLE001 - 读书失败不阻断
                    logger.event("read", "failed", n=req.n, title=req.title,
                                 error=f"{type(exc).__name__}: {exc}")

            outcomes.append(outcome)

        write_manifest(outcomes)
        logger.event("pipeline", "ok", stage_detail="完成",
                     downloaded=sum(1 for o in outcomes
                                    if o.status == "downloaded"),
                     total=len(outcomes))
        return outcomes
    finally:
        if own_logger:
            logger.finish()


def run_from_booklist_file(path: str,
                           logger: Optional[RunLogger] = None,
                           **kwargs: Any) -> List[BookOutcome]:
    """从书目清单文件跑流水线。

    Args:
        path: 清单 JSON 路径。
        logger: 日志记录器。
        **kwargs: 透传给 `run_pipeline`。

    Returns:
        各书结果列表。
    """
    entries = load_booklist(path)
    requests = [
        BookRequest(n=e.get("n", idx + 1), title=e.get("title", ""),
                    entry_url=e.get("url", ""))
        for idx, e in enumerate(entries)
    ]
    return run_pipeline(requests, logger=logger, **kwargs)
