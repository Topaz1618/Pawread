"""Pawread 资源发现。

**职责**：把「书名 + 作者」派发给各站点适配器，汇总候选资源，
并对每个站点的失败做归因。

**失败归因是重点** —— 用户明确要求「找不到下载不到的记录日志，
显示给用户」。因此每个站点都必须产出明确的 `SiteResult`，
区分以下失败类型：

| 错误类型 | 含义 |
|---|---|
| `proxy_unreachable` | 代理连不上该站 |
| `http_error` | HTTP 状态码非 200 |
| `timeout` | 超时 |
| `parse_error` | 响应解析失败 |
| `no_result` | 站点可达但没找到匹配条目 |

**上游**：`pawread/pipeline.py`。
**下游**：`pawread/pipeline.py` 的下载阶段。
"""

from __future__ import annotations

import json
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

from .sources import (
    PARSERS,
    SITES,
    Candidate,
    Site,
    SiteResult,
    build_query,
)

#: 各站点的查询构造方式。`title` 用书名，`title+author` 用书名加作者。
QUERY_MODE = {
    "archive.org": "title+author",
    "openlibrary.org": "title",
    "gutenberg.org": "title",
    "books.google.com": "title",
}


def classify_error(exc: BaseException) -> str:
    """把异常归类为失败类型。

    Args:
        exc: 捕获到的异常。

    Returns:
        失败类型标识。
    """
    import requests

    name = type(exc).__name__
    if isinstance(exc, requests.exceptions.ProxyError):
        return "proxy_unreachable"
    if isinstance(exc, requests.exceptions.Timeout):
        return "timeout"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "connection_error"
    if "Proxy" in name:
        return "proxy_unreachable"
    if "Timeout" in name:
        return "timeout"
    if "Connection" in name:
        return "connection_error"
    return "error"


def _score_candidate(candidate: Candidate, title: str,
                     author: str) -> int:
    """给候选资源打分，判断它是不是目标书。

    打分同时考虑「像不像目标书」与「能不能下」——
    受借阅限制的条目排在最后，但仍保留在列表里，因为用户能看到
    「搜到了但下不到」这个事实。

    Args:
        candidate: 候选资源。
        title: 目标书名。
        author: 目标作者。

    Returns:
        分数；明显不匹配时返回 0。
    """
    key = _norm(title)
    item = _norm(candidate.title)
    if not key or not item:
        return 0
    if key not in item and item not in key:
        return 0
    score = 10
    if key == item:
        score += 8
    if author:
        creator = _norm(candidate.author)
        if creator:
            surname = _norm(author).split()[-1]
            if surname and surname in creator:
                score += 6
    if candidate.meta.get("public_domain"):
        score += 4
    if candidate.meta.get("pdf") or candidate.meta.get("epub"):
        score += 6
    if candidate.meta.get("ebook_access") in ("borrowable", "public"):
        score += 5
    if candidate.meta.get("restricted"):
        # 受借阅限制：几乎肯定下不到，压到最低
        score -= 100
    return max(score, 1)


def _norm(text: str) -> str:
    """把文本规范化，用于标题比对。

    Args:
        text: 原始文本。

    Returns:
        小写、仅含字母数字与空格的字符串。
    """
    import re
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def search_site(session: Any, site: Site, title: str,
                author: str = "") -> SiteResult:
    """在单个站点上检索一本书。

    Args:
        session: 已配置代理的会话。
        site: 站点定义。
        title: 书名。
        author: 作者。

    Returns:
        站点检索结果，含候选与失败归因。
    """
    import requests

    started = time.monotonic()
    result = SiteResult(site=site.name)

    mode = QUERY_MODE.get(site.name, "title")
    query = build_query(title, author if mode == "title+author" else "")

    try:
        resp = session.get(site.search.format(query=query),
                           timeout=90, headers=_HEADERS)
    except Exception as exc:  # noqa: BLE001 - 站点失败需归因后继续
        result.error = f"{classify_error(exc)}: {type(exc).__name__}"
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        return result

    if resp.status_code != 200:
        result.error = f"http_error: {resp.status_code}"
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        return result

    parser = PARSERS.get(site.parser)
    candidates: List[Candidate] = []
    if parser is not None:
        if site.parser == "parse_gutenberg":
            candidates = parser(resp.text)
        elif site.parser == "parse_direct_pdf":
            # 直链站点没有检索接口，命中即为唯一候选
            candidates = [Candidate(
                site=site.name,
                title=title,
                url=site.search,
                kind="pdf" if site.search.lower().endswith(".pdf") else "page",
                author=author,
                source=site.domain,
            )]
        else:
            try:
                candidates = parser(resp.json())
            except (ValueError, AttributeError) as exc:
                result.error = f"parse_error: {type(exc).__name__}"
                result.elapsed_ms = int((time.monotonic() - started) * 1000)
                return result

    scored = [(score, cand) for cand in candidates
              for score in [_score_candidate(cand, title, author)]
              if score > 0]
    scored.sort(key=lambda item: -item[0])

    result.candidates = [cand for _, cand in scored]
    result.ok = True
    if not result.candidates:
        result.error = "no_result"
    result.elapsed_ms = int((time.monotonic() - started) * 1000)
    return result


def probe_downloadable(session: Any, candidates: List[Candidate],
                       title: str, limit: int = 5) -> List[Candidate]:
    """筛出真正有可下载文件的候选。

    搜索结果的元数据不含文件列表 ——「搜到了」不等于「能下」。
    受借阅限制的条目、单篇论文、只有 history/ 备份文件的条目都会
    出现在结果里，但下载必然失败。这里逐个查条目元数据确认。

    Args:
        session: 已配置代理的会话。
        candidates: 候选列表。
        title: 目标书名。
        limit: 最多检查几个候选。

    Returns:
        确认有可下载文件的候选列表。
    """
    from .fetcher import ia_metadata, pick_file

    downloadable: List[Candidate] = []
    for cand in candidates[:limit]:
        identifiers: List[str] = []
        if cand.site == "archive.org":
            if cand.meta.get("identifier"):
                identifiers.append(cand.meta["identifier"])
        elif cand.site == "openlibrary.org":
            identifiers.extend(cand.meta.get("ia") or [])

        for identifier in identifiers:
            metadata = ia_metadata(session, identifier)
            if metadata is None:
                continue
            if metadata.get("metadata", {}).get("access-restricted-item"):
                cand.meta["restricted"] = True
                continue
            chosen = pick_file(metadata, title)
            if not chosen:
                continue
            cand.meta["identifier"] = identifier
            cand.meta["file_name"] = chosen["name"]
            cand.meta["file_size"] = chosen.get("size", 0)
            cand.kind = (Path(chosen["name"]).suffix.lower().lstrip(".")
                         or "pdf")
            cand.url = ("https://archive.org/download/" + identifier + "/"
                        + urllib.parse.quote(chosen["name"]))
            downloadable.append(cand)
            break
    return downloadable


#: 请求头，与 `pawread/sources.py` 保持一致。
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/131.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}


def select_sites(title: str,
                 entry_url: str = "") -> List[Site]:
    """挑出适用于某本书的站点。

    通用检索站（archive / openlibrary / gutenberg / google books）
    对每本书都适用。直链站点只对应特定的书 —— 例如作者官网的
    PDF 只有那一本书能用，对每本书都去请求是浪费。

    Args:
        title: 书名。
        entry_url: 用户给的检索入口地址。用于判断直链站点是否适用。

    Returns:
        适用站点列表。
    """
    domain = ""
    if entry_url:
        import re
        match = re.match(r"^https?://([^/]+)", entry_url)
        if match:
            domain = match.group(1).lower()

    key = _norm(title)
    selected: List[Site] = []
    for site in SITES:
        if not site.enabled:
            continue
        if not site.book_scoped:
            selected.append(site)
            continue
        # 直链站点：域名匹配，或书名匹配
        if domain and domain == site.domain:
            selected.append(site)
            continue
        if any(_norm(name) == key for name in site.books):
            selected.append(site)
    return selected


def discover(session: Any, title: str, author: str = "",
             entry_url: str = "",
             sites: Optional[List[Site]] = None,
             per_site_limit: int = 5,
             probe: bool = True,
             probe_limit: int = 6) -> Dict[str, Any]:
    """在所有适用站点上检索一本书。

    Args:
        session: 已配置代理的会话。
        title: 书名。
        author: 作者。
        entry_url: 用户给的检索入口地址，用于挑选直链站点。
        sites: 要检索的站点。缺省按书名自动挑选。
        per_site_limit: 每站最多保留的候选数。
        probe: 是否逐个查条目元数据，确认候选真的可下载。
        probe_limit: 最多预检几个候选。

    Returns:
        含各站结果、合并候选与预检结论的字典。
    """
    targets = sites if sites is not None else select_sites(title, entry_url)
    results: List[SiteResult] = []
    for site in targets:
        results.append(search_site(session, site, title, author))

    merged: List[Dict[str, Any]] = []
    all_candidates: List[Candidate] = []
    for site_result in results:
        for cand in site_result.candidates[:per_site_limit]:
            merged.append(cand.to_dict())
            all_candidates.append(cand)

    # 预检：确认候选真的有可下载文件
    downloadable: List[Candidate] = []
    if probe:
        downloadable = probe_downloadable(session, all_candidates,
                                           title, probe_limit)
        downloadable_urls = {c.url for c in downloadable}
        for cand in all_candidates:
            if cand.url in downloadable_urls:
                continue
            if cand.site in ("archive.org", "openlibrary.org"):
                cand.meta["not_downloadable"] = True

    failures = [
        {"site": r.site, "error": r.error, "elapsed_ms": r.elapsed_ms}
        for r in results if not r.ok
    ]
    empty = [
        {"site": r.site, "error": r.error}
        for r in results if r.ok and not r.candidates
    ]

    return {
        "title": title,
        "author": author,
        "candidates": [c.to_dict() for c in downloadable] if probe
        else merged,
        "all_candidates": merged,
        "downloadable_count": len(downloadable),
        "sites": [r.to_dict() for r in results],
        "failures": failures,
        "empty_sites": empty,
    }
