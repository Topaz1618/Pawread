"""Web 层的数据读取。

**为什么单独一层**：前端要展示的东西来自三个地方 ——
书单配置（`data/booklists/`）、下载状态（`data/state/`）、
笔记正文（`notes/`）。这三个来源各有各的生命周期，
硬拼在 Handler 里会让每个 Handler 都重复读文件、判空、处理缓存。

**状态语义**：

| state | 含义 | 有笔记？ |
|---|---|---|
| `pending` | 还没尝试 | 否 |
| `searching` | 正在检索资源 | 否 |
| `downloading` | 正在下载 | 否 |
| `verifying` | 正在校验内容 | 否 |
| `noting` | 正在生成笔记 | 否 |
| `available` | 资源已就位，尚未读书 | 否 |
| `noted` | 已下载且已产出笔记 | 是 |
| `unavailable` | 找不到可下载的资源 | 否 |
| `failed` | 下载或校验失败 | 否 |
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..booklists import BOOKLISTS_DIR, display_title, slugify

#: 项目根目录。
ROOT = Path(__file__).resolve().parent.parent.parent

#: 运行状态文件。
STATE_PATH = ROOT / "data" / "state" / "acquisition.json"

#: 笔记目录。
NOTES_DIR = ROOT / "notes"

#: 书单文件。
PERSONAL_LIST = BOOKLISTS_DIR / "personal.json"

#: 有笔记的判定：笔记文件存在且非空。
_LOCK = threading.RLock()
_CACHE: Dict[str, Any] = {"mtime": None, "data": None}


def _read_json(path: Path) -> Any:
    """读 JSON 文件。

    Args:
        path: 文件路径。

    Returns:
        解析结果；文件不存在或格式错误时返回 None。
    """
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_state() -> Dict[str, Any]:
    """读取下载状态。

    带 mtime 缓存 —— 状态文件会被流水线频繁改写，
    每次请求都重读会拖慢接口。

    Returns:
        状态字典；文件不存在时返回空结构。
    """
    with _LOCK:
        try:
            mtime = STATE_PATH.stat().st_mtime
        except OSError:
            return {"version": 1, "books": {}}
        if _CACHE["mtime"] == mtime and _CACHE["data"] is not None:
            return _CACHE["data"]
        data = _read_json(STATE_PATH) or {"version": 1, "books": {}}
        _CACHE["mtime"] = mtime
        _CACHE["data"] = data
        return data


def save_state(data: Dict[str, Any]) -> None:
    """写回下载状态。

    Args:
        data: 状态字典。
    """
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        STATE_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        _CACHE["mtime"] = None
        _CACHE["data"] = None


def note_path(book_id: str) -> Optional[Path]:
    """找一本书的笔记文件。

    文件名用 slug，但历史上也用过标题 slug，两种都试。

    Args:
        book_id: 条目 id。

    Returns:
        笔记路径；不存在时返回 None。
    """
    for candidate in (NOTES_DIR / f"{book_id}.md",
                      NOTES_DIR / f"{book_id.replace('-', '_')}.md"):
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    return None


def read_note(book_id: str) -> Optional[str]:
    """读一本书的笔记正文。

    Args:
        book_id: 条目 id。

    Returns:
        Markdown 原文；没有笔记时返回 None。
    """
    path = note_path(book_id)
    if not path:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def list_books(lang: str = "cn") -> List[Dict[str, Any]]:
    """列出全部书，合并配置与状态。

    这是书单页与阅读页侧边栏的数据源。

    Args:
        lang: 译名语言。查不到该语言的译名时退回原名。

    Returns:
        条目列表，每项含配置字段与 `state` 状态。
    """
    doc = _read_json(PERSONAL_LIST) or {}
    raw_books: List[Dict[str, Any]] = []
    for book_list in doc.get("lists", []):
        raw_books.extend(book_list.get("books", []))

    state_doc = load_state()
    states = state_doc.get("books", {})

    out: List[Dict[str, Any]] = []
    for entry in raw_books:
        book_id = entry.get("id", "")
        st = states.get(book_id) or {}
        note = note_path(book_id)
        merged = dict(entry)
        merged["display_title"] = display_title(entry, lang)
        merged["original_title"] = (entry.get("title") or {}).get("text", "")
        merged["state"] = st.get("state", "pending")
        merged["state_detail"] = st.get("detail", "")
        merged["state_progress"] = st.get("progress", 0)
        merged["reasons"] = st.get("reasons", [])
        merged["has_note"] = note is not None
        merged["note_path"] = str(note) if note else ""
        merged["bytes"] = (st.get("file") or {}).get("bytes", 0)
        merged["source"] = st.get("source", "")
        merged["source_url"] = st.get("source_url", "")
        merged["license"] = st.get("license", "")
        out.append(merged)
    return out


def find_book(book_id: str, lang: str = "cn") -> Optional[Dict[str, Any]]:
    """按 id 找一本书。

    Args:
        book_id: 条目 id。
        lang: 译名语言。

    Returns:
        条目；找不到时返回 None。
    """
    for entry in list_books(lang):
        if entry.get("id") == book_id:
            return entry
    return None


def ensure_book_entry(title: str,
                      lang: str = "cn",
                      author: str = "") -> Dict[str, Any]:
    """确保书单里有一本书，返回它的条目。

    用户从操作页提交新书名时用这个 —— 已有就复用，
    没有就追加到 `personal.json`。

    Args:
        title: 原书名。
        lang: 用户语言。
        author: 作者，可为空。

    Returns:
        书单条目。
    """
    doc = _read_json(PERSONAL_LIST) or {
        "version": 1,
        "languages": {},
        "lists": [{"id": "personal", "name": "我的书单", "kind": "personal",
                   "default_lang": lang, "priority_levels": [], "books": []}],
    }
    book_list = doc["lists"][0]
    book_id = slugify(title)

    for entry in book_list.get("books", []):
        if entry.get("id") == book_id:
            return entry

    entry = {
        "id": book_id,
        "title": {"text": title, "lang": lang, "script": "latin"},
        "priority": None,
        "translations": {lang: title} if lang != "cn" else {},
        "aliases": [],
        "search": {"lang": lang, "terms": [title]},
        "sources": [],
    }
    if author:
        entry["author"] = author
    book_list.setdefault("books", []).append(entry)

    PERSONAL_LIST.parent.mkdir(parents=True, exist_ok=True)
    PERSONAL_LIST.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return entry


#: 失败原因的机器可读枚举。前端据此选图标与文案。
REASON_LABELS = {
    "no_result": "检索无结果",
    "restricted": "受借阅或权限限制",
    "http_error": "HTTP 错误",
    "proxy_unreachable": "代理不可达",
    "network_error": "网络错误",
    "timeout": "请求超时",
    "verify_failed": "内容校验不通过",
    "wrong_format": "文件格式不支持",
    "size_mismatch": "文件大小异常",
    "parse_failed": "文件解析失败",
    "not_processed": "尚未处理",
}


def migrate_manifest() -> int:
    """从 `books/manifest.json` 生成初始状态文件。

    只在状态文件不存在时执行 —— 之后的真实状态以状态文件为准。

    Returns:
        迁移的条目数。
    """
    if STATE_PATH.exists():
        return 0
    manifest = _read_json(ROOT / "books" / "manifest.json")
    if not isinstance(manifest, list):
        return 0

    doc = _read_json(PERSONAL_LIST) or {}
    by_slug: Dict[str, Dict[str, Any]] = {}
    for book_list in doc.get("lists", []):
        for entry in book_list.get("books", []):
            by_slug[slugify(entry.get("title", {}).get("text", ""))] = entry

    books: Dict[str, Any] = {}
    for item in manifest:
        title = item.get("title", "")
        book_id = slugify(title)
        entry = by_slug.get(book_id)
        downloaded = item.get("status") == "downloaded"
        file_info = item.get("file") or {}

        state = "noted" if downloaded else "unavailable"
        reasons: List[Dict[str, Any]] = []
        if not downloaded:
            reasons.append({
                "site": "-",
                "reason": "not_found",
                "detail": item.get("note") or "未找到可下载的完整文件",
            })

        books[book_id] = {
            "state": state,
            "detail": "" if downloaded else (item.get("note") or ""),
            "progress": 100 if downloaded else 0,
            "file": {
                "path": file_info.get("path", ""),
                "bytes": file_info.get("bytes", 0),
                "sha256": file_info.get("sha256", ""),
            } if downloaded else None,
            "source": item.get("source", ""),
            "source_url": item.get("source_url", ""),
            "license": item.get("license", ""),
            "verify": {
                "status": item.get("verify_status", ""),
                "detail": item.get("verify_detail", ""),
            },
            "reasons": reasons,
            "note_path": (entry or {}).get("id", "") and "",
        }
        if entry:
            books[book_id]["note_path"] = str(
                note_path(entry["id"]) or "")

    save_state({"version": 1, "books": books})
    return len(books)
