"""Pawread 资源站点适配器。

**职责**：把「书名 + 作者」变成候选下载资源。

**站点清单**来自用户提供的 59 本书检索入口（见
`data/booklist.json`），按域名归类为适配器。

**合规分级**（`compliance` 字段）：

| 级别 | 含义 | 站点 |
|---|---|---|
| `public_domain` | 版权过期，合法公开 | gutenberg.org |
| `open_lending` | 开放借阅 / 受控数字借阅 | archive.org、openlibrary.org |
| `publisher` | 出版方或作者官方发布 | donellameadows.org、scottberkun.com、pacounderhill.com、otexts.com、order.poorcharliesalmanack.com |
| `reference` | 商业书商的检索入口，通常需购买 | books.google.com |

**代理策略**：全程走 SmartProxy（用户指定 `proxy_only`）。
实测可达性（2026-11-12，经 SmartProxy）：

| 站点 | 结果 |
|---|---|
| openlibrary.org | 200 |
| archive.org | 200 |
| gutenberg.org | 200 |
| donellameadows.org | 200（直链 PDF，43 MB） |
| scottberkun.com | 200 |
| pacounderhill.com | 200 |
| order.poorcharliesalmanack.com | 200 |
| books.google.com | 429（限流） |
| gutendex.com | 超时 |
| otexts.com | ProxyError |

**上游**：`pawread/pipeline.py` 的发现阶段。
**下游**：`pawread/pipeline.py` 的下载阶段。
"""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: 请求头。与 `pawread.fetcher.USER_AGENT` 一致。
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/131.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class Candidate:
    """一个候选下载资源。

    字段:
        site: 站点标识，例如 `archive.org`。
        title: 资源标题。
        url: 下载地址或详情页地址。
        kind: 资源类型，`pdf` / `epub` / `txt` / `page`。
        author: 作者。
        source: 来源说明，写进日志。
        meta: 站点特有的附加信息。
    """

    site: str
    title: str
    url: str
    kind: str = "page"
    author: str = ""
    source: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转为可 JSON 序列化的字典。

        Returns:
            候选资源字典。
        """
        return {
            "site": self.site,
            "title": self.title,
            "url": self.url,
            "kind": self.kind,
            "author": self.author,
            "source": self.source,
            "meta": self.meta,
        }


@dataclass
class SiteResult:
    """一个站点的检索结果。

    字段:
        site: 站点标识。
        ok: 是否成功完成检索。
        candidates: 候选资源列表。
        error: 失败原因；成功时为空串。
        elapsed_ms: 耗时毫秒。
    """

    site: str
    ok: bool = False
    candidates: List[Candidate] = field(default_factory=list)
    error: str = ""
    elapsed_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """转为可 JSON 序列化的字典。

        Returns:
            站点结果字典。
        """
        return {
            "site": self.site,
            "ok": self.ok,
            "candidates": [c.to_dict() for c in self.candidates],
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass
class Site:
    """一个站点适配器。

    字段:
        name: 站点标识。
        domain: 域名。
        compliance: 合规级别。
        search: 检索地址模板，`{query}` 会被替换成 URL 编码的查询词。
        parser: 响应解析器名，对应 `PARSERS` 里的函数名。
        enabled: 是否启用。
        note: 备注。
        book_scoped: 是否只对特定书生效。直链站点（如某作者的官网 PDF）
            只对应一本书，只有当用户给的检索入口属于该域名时才启用。
        books: 该站点对应的书名列表（`book_scoped` 时用）。
    """

    name: str
    domain: str
    compliance: str
    search: str = ""
    parser: str = ""
    enabled: bool = True
    note: str = ""
    book_scoped: bool = False
    books: List[str] = field(default_factory=list)


#: 站点注册表。检索地址模板里的 `{query}` 是 URL 编码后的查询词。
SITES: List[Site] = [
    Site(
        name="archive.org",
        domain="archive.org",
        compliance="open_lending",
        search=("https://archive.org/advancedsearch.php?q="
                "{query}+AND+mediatype%3Atexts"
                "&fl%5B%5D=identifier&fl%5B%5D=title&fl%5B%5D=creator"
                "&fl%5B%5D=access-restricted-item&fl%5B%5D=licenseurl"
                "&rows=40&page=1&output=json"),
        parser="parse_archive",
        note="Internet Archive。43 本既有书籍来自此处。"
             "受借阅限制的条目（access-restricted-item=true）不可下载。",
    ),
    Site(
        name="openlibrary.org",
        domain="openlibrary.org",
        compliance="open_lending",
        search=("https://openlibrary.org/search.json?q={query}"
                "&fields=key,title,author_name,first_publish_year,"
                "ebook_access,ia,edition_key&limit=20"),
        parser="parse_openlibrary",
        note="Open Library。多数条目指向 Internet Archive 的扫描件。",
    ),
    Site(
        name="gutenberg.org",
        domain="gutenberg.org",
        compliance="public_domain",
        search=("https://www.gutenberg.org/ebooks/search/?query={query}"
                "&submit_search=Go%21"),
        parser="parse_gutenberg",
        note="Project Gutenberg。版权过期图书。经 SmartProxy 可达"
             "（首测 ProxyError，换 session ID 后恢复）。",
    ),
    Site(
        name="books.google.com",
        domain="books.google.com",
        compliance="reference",
        search=("https://www.googleapis.com/books/v1/volumes?q={query}"
                "&maxResults=10"),
        parser="parse_googlebooks",
        enabled=False,
        note="Google Books API。实测全程 429 限流；且该站只提供预览、"
             "不提供可下载文件 —— 属于参考类站点，默认关闭，"
             "需要时用 `sites=[...]` 显式开启。",
    ),
    Site(
        name="donellameadows.org",
        domain="donellameadows.org",
        compliance="publisher",
        search=("https://www.donellameadows.org/wp-content/userfiles/"
                "Limits-to-Growth-digital-scan-version.pdf"),
        parser="parse_direct_pdf",
        book_scoped=True,
        books=["The Limits to Growth"],
        note="作者官方发布《增长的极限》扫描版 PDF，直链。",
    ),
    Site(
        name="scottberkun.com",
        domain="scottberkun.com",
        compliance="publisher",
        search="https://scottberkun.com/books/making-things-happen/",
        parser="parse_direct_pdf",
        book_scoped=True,
        books=["Making Things Happen"],
        note="作者官方发布《Making Things Happen》。",
    ),
    Site(
        name="pacounderhill.com",
        domain="pacounderhill.com",
        compliance="publisher",
        search="https://pacounderhill.com/books/",
        parser="parse_direct_pdf",
        book_scoped=True,
        books=["High Output Management"],
        note="出版社官方书目页。",
    ),
    Site(
        name="otexts.com",
        domain="otexts.com",
        compliance="publisher",
        search="https://otexts.com/fpp3/",
        parser="parse_direct_pdf",
        book_scoped=True,
        books=["Forecasting: Principles and Practice"],
        note="《Forecasting: Principles and Practice》官方站。"
             "实测 SmartProxy ProxyError，直连亦被拒。",
    ),
    Site(
        name="order.poorcharliesalmanack.com",
        domain="order.poorcharliesalmanack.com",
        compliance="publisher",
        search="https://order.poorcharliesalmanack.com/",
        parser="parse_direct_pdf",
        book_scoped=True,
        books=["Poor Charlie's Almanack"],
        note="《Poor Charlie's Almanack》官方订购页，非免费下载。",
    ),
]


def _norm(text: str) -> str:
    """把文本规范化，用于标题比对。

    Args:
        text: 原始文本。

    Returns:
        小写、仅含字母数字与空格的字符串。
    """
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _query_for(title: str, author: str = "") -> str:
    """构造检索查询词。

    Args:
        title: 书名。
        author: 作者。

    Returns:
        查询词字符串。
    """
    if author:
        return f"{title} {author}".strip()
    return title.strip()


def parse_archive(payload: Any) -> List[Candidate]:
    """解析 Internet Archive 检索结果。

    Args:
        payload: 响应 JSON。

    Returns:
        候选资源列表。
    """
    try:
        docs = payload["response"]["docs"]
    except (KeyError, TypeError):
        return []
    out: List[Candidate] = []
    for doc in docs:
        identifier = doc.get("identifier")
        if not identifier:
            continue
        title = doc.get("title")
        if isinstance(title, list):
            title = next((t for t in title if t), "")
        creator = doc.get("creator")
        if isinstance(creator, list):
            creator = next((c for c in creator if c), "")
        restricted = bool(doc.get("access-restricted-item"))
        out.append(Candidate(
            site="archive.org",
            title=title or "",
            url=f"https://archive.org/details/{identifier}",
            kind="page",
            author=creator or "",
            source="Internet Archive",
            meta={
                "identifier": identifier,
                "restricted": restricted,
                "license": doc.get("licenseurl") or "",
            },
        ))
    return out


def parse_openlibrary(payload: Any) -> List[Candidate]:
    """解析 Open Library 检索结果。

    Args:
        payload: 响应 JSON。

    Returns:
        候选资源列表。
    """
    try:
        docs = payload.get("docs") or []
    except AttributeError:
        return []
    out: List[Candidate] = []
    for doc in docs:
        key = doc.get("key")
        if not key:
            continue
        authors = doc.get("author_name") or []
        author = authors[0] if authors else ""
        out.append(Candidate(
            site="openlibrary.org",
            title=doc.get("title") or "",
            url=f"https://openlibrary.org{key}",
            kind="page",
            author=author,
            source="Open Library",
            meta={
                "ebook_access": doc.get("ebook_access") or "",
                "ia": doc.get("ia") or [],
                "edition_key": doc.get("edition_key") or [],
                "first_publish_year": doc.get("first_publish_year") or 0,
            },
        ))
    return out


def parse_gutenberg(payload: Any) -> List[Candidate]:
    """解析 Project Gutenberg 检索结果。

    Args:
        payload: 响应 HTML 文本。

    Returns:
        候选资源列表。
    """
    out: List[Candidate] = []
    # 搜索结果页的书目链接形如 /ebooks/12345
    for match in re.finditer(
            r'href="(/ebooks/(\d+))"[^>]*>(.*?)</a>', payload, re.S):
        url_path, book_id, title = match.groups()
        clean = re.sub(r"<[^>]+>", " ", title)
        clean = re.sub(r"\s+", " ", clean).strip()
        if not clean or not book_id:
            continue
        out.append(Candidate(
            site="gutenberg.org",
            title=clean,
            url=f"https://www.gutenberg.org{url_path}",
            kind="page",
            source="Project Gutenberg",
            meta={"ebook_id": book_id},
        ))
    # 去重，保持顺序
    seen = set()
    unique = []
    for cand in out:
        if cand.url in seen:
            continue
        seen.add(cand.url)
        unique.append(cand)
    return unique


def parse_googlebooks(payload: Any) -> List[Candidate]:
    """解析 Google Books 检索结果。

    Args:
        payload: 响应 JSON。

    Returns:
        候选资源列表。
    """
    try:
        items = payload.get("items") or []
    except AttributeError:
        return []
    out: List[Candidate] = []
    for item in items:
        info = item.get("volumeInfo") or {}
        access = item.get("accessInfo") or {}
        out.append(Candidate(
            site="books.google.com",
            title=info.get("title") or "",
            url=info.get("infoLink") or "",
            kind="page",
            author=", ".join(info.get("authors") or []),
            source="Google Books",
            meta={
                "viewability": access.get("viewability") or "",
                "public_domain": bool(access.get("publicDomain")),
                "pdf": bool((access.get("pdf") or {}).get("isAvailable")),
                "epub": bool((access.get("epub") or {}).get("isAvailable")),
            },
        ))
    return out


def parse_direct_pdf(payload: Any) -> List[Candidate]:
    """解析直链 PDF 站点。

    直链站点没有检索接口，命中即为唯一候选。

    Args:
        payload: 响应内容（未使用）。

    Returns:
        空列表 —— 直链候选由调用方直接构造。
    """
    return []


#: 解析器注册表。
PARSERS = {
    "parse_archive": parse_archive,
    "parse_openlibrary": parse_openlibrary,
    "parse_gutenberg": parse_gutenberg,
    "parse_googlebooks": parse_googlebooks,
    "parse_direct_pdf": parse_direct_pdf,
}


def site_by_name(name: str) -> Optional[Site]:
    """按名字取站点。

    Args:
        name: 站点标识。

    Returns:
        站点定义；不存在时返回 None。
    """
    for site in SITES:
        if site.name == name:
            return site
    return None


def build_query(title: str, author: str = "") -> str:
    """构造 URL 编码后的检索查询。

    Args:
        title: 书名。
        author: 作者。

    Returns:
        URL 编码的查询串。
    """
    return urllib.parse.quote(_query_for(title, author))


def load_booklist(path: str) -> List[Dict[str, Any]]:
    """读取用户提供的书目清单。

    Args:
        path: JSON 文件路径。

    Returns:
        书目条目列表；文件不存在时返回空列表。
    """
    from pathlib import Path
    file = Path(path)
    if not file.exists():
        return []
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
