"""Pawread 章节切分。

**职责**：把 PDF / EPUB / TXT 按**章节**切开，产出带页码的文本块。

**为什么按章节切**：按固定页数切会把一个论证拦腰截断，笔记读起来
上下文断裂。按章节切保证每块是一个完整的论述单元。

**章节边界怎么找**：优先用**目录页** —— 目录里的「章名 + 起始页码」
是权威依据。PDF 物理页与印刷页码的偏移量从正文页反推。
目录不可用时退化为**运行头聚类**：把每页顶部的运行头归一化后聚类，
相同运行头的连续页归为一章。

**上游**：`pawread/extract.py`。
**下游**：`pawread/reader.py`。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

#: 目录行。形如 "ONE. The Basics | 11" 或 "System Definitions | 187"。
TOC_LINE = re.compile(
    r"^\s*(?P<title>[A-Z0-9][^|]*?)\s*[|｜]?\s*(?P<page>\d{1,4})\s*$")

#: 目录里没有页码的行 —— 部分标题（Part One 等）不标页码。
TOC_HEADING = re.compile(r"^\s*(?P<title>[A-Z0-9][^|]{2,60})\s*$")

#: 目录页的判定关键词。
TOC_MARKERS = ("contents", "table of contents", "目录", "索 引")

#: 运行头里的页码行。形如 "28" 或 "xvi"。
PAGE_NUMBER_LINE = re.compile(r"^[ivxlcdm]+$|^\d+$", re.I)

#: 运行头里的出版标记。形如 "TIS final pgs xviii"。
PUBLISHER_MARK = re.compile(r"final pgs|final pages|©|copyright",
                             re.I)

#: 罗马数字页码。用于把前置页（x、xiv）与正文页码区分开。
ROMAN_PAGE = re.compile(r"^[ivxlcdm]+$", re.I)

#: 运行头归一化时剥掉的装饰词。奇偶页的运行头常带不同装饰
#: （例如 "INTRODUCTION" 与 "THE SYSTEM LENS" 其实是同一个章名），
#: 归一化后才能比较出「是不是同一章」。
#:
#: 注意：`introduction` 不在此列 —— 本书正文第一章就叫
#: "Introduction: The Systems Lens"，剥掉后会与别的章节混淆。
HEAD_NOISE_WORDS = (
    "chapter", "part", "section", "contents",
    "preface", "foreword", "appendix", "index",
)

#: 目录里常见的「装饰标题」，本身不是内容章节。
TOC_SKIP_TITLES = (
    "contents", "index", "about the author", "bibliography",
    "acknowledgments", "acknowledgements", "notes", "目录", "索引",
)


def normalize_head(head: str) -> str:
    """把运行头归一化，便于比较是否属于同一章。

    奇偶页的运行头通常带不同装饰（例如 "INTRODUCTION" 与
    "THE SYSTEM LENS" 指向同一章），直接比较会把每页都切成新章。
    归一化做法：去掉装饰词与冠词，保留实词并压成字母序的关键词集合。

    Args:
        head: 原始运行头。

    Returns:
        归一化后的字符串；原串为空时返回空串。
    """
    if not head:
        return ""
    cleaned = head.lower()
    words = re.findall(r"[a-z0-9]+", cleaned)
    meaningful = [w for w in words
                  if w not in HEAD_NOISE_WORDS
                  and w not in ("the", "a", "an", "of", "and")]
    if not meaningful:
        return " ".join(sorted(words))
    return " ".join(sorted(meaningful))


def running_head(page_text: str) -> str:
    """从一页文本里提取运行头（章名）。

    PDF 的运行头位于页面顶部，可能是：
    - 单独一行章名（偶数页）
    - 「页码 + 章名」两行（奇数页）

    页码行与出版标记行会被剔除。

    Args:
        page_text: `pdftotext` 输出的一页文本。

    Returns:
        推断出的章名；判断不出时返回空字符串。
    """
    lines = [l.strip() for l in page_text.split("\n") if l.strip()]
    if not lines:
        return ""
    for line in lines[:4]:
        if PAGE_NUMBER_LINE.match(line):
            continue
        if PUBLISHER_MARK.search(line):
            continue
        if len(line) <= 80:
            return line
    return ""


def strip_running_head(page_text: str) -> str:
    """去掉页面顶部的运行头。

    运行头是排版元素，不是正文。不去掉的话，笔记里会出现
    「THE SYSTEM LENS」这种无意义的行。

    Args:
        page_text: 一页的原始文本。

    Returns:
        去掉运行头后的正文。
    """
    lines = page_text.split("\n")
    head = running_head(page_text)
    if not head:
        return page_text
    for idx, line in enumerate(lines[:4]):
        stripped = line.strip()
        if not stripped:
            continue
        if PAGE_NUMBER_LINE.match(stripped) or PUBLISHER_MARK.search(stripped):
            continue
        if stripped == head:
            del lines[idx]
        break
    return "\n".join(lines)


def find_toc_pages(page_texts: List[str]) -> List[int]:
    """找出目录页的页码下标。

    Args:
        page_texts: 每页的原始文本。

    Returns:
        目录页的下标列表；没找到时返回空列表。
    """
    found: List[int] = []
    for idx, text in enumerate(page_texts):
        head = text.strip()[:200].lower()
        if any(marker in head for marker in TOC_MARKERS):
            found.append(idx)
    return found


def parse_toc(page_texts: List[str]) -> List[Dict[str, Any]]:
    """从目录页解析章名与起始印刷页码。

    Args:
        page_texts: 每页的原始文本。

    Returns:
        目录条目列表，每项含 `title` 与 `page`（印刷页码，int）。
        没有可用目录时返回空列表。
    """
    entries: List[Dict[str, Any]] = []
    for idx in find_toc_pages(page_texts):
        for line in page_texts[idx].split("\n"):
            line = line.strip()
            if not line:
                continue
            match = TOC_LINE.match(line)
            if match:
                title = match.group("title").strip()
                page = int(match.group("page"))
                if title and page > 0:
                    entries.append({"title": title, "page": page})
                continue
            # 无页码的标题行（Part One 等），只用于衔接上下文
            head = TOC_HEADING.match(line)
            if head:
                title = head.group("title").strip()
                low = title.lower()
                if (title.isupper() or low.startswith("part ")
                        or low.startswith("appendix")) and \
                        low not in TOC_SKIP_TITLES and len(title) < 60:
                    entries.append({"title": title, "page": 0})
    return entries


def head_overlap(key: str, head: str) -> float:
    """计算目录条目与运行头的词元重合度。

    不能用子串匹配 —— 目录写 "The Systems Lens"，运行头写
    "THE SYSTEM LENS"，单复数与冠词都可能不同。改用词元重合比例。

    Args:
        key: 归一化后的目录条目。
        head: 归一化后的运行头。

    Returns:
        重合比例（0 到 1）；任一为空时返回 0。
    """
    if not key or not head:
        return 0.0
    key_tokens = set(key.split())
    head_tokens = set(head.split())
    if not key_tokens or not head_tokens:
        return 0.0
    return len(key_tokens & head_tokens) / len(key_tokens)


def detect_page_offset(page_texts: List[str], toc_entries: List[Dict[str, Any]],
                       start_page: int) -> int:
    """推断「印刷页码 → PDF 物理页」的偏移量。

    做法：取目录里第一个有页码的条目，在 PDF 里找与它最匹配的一页
    （词元重合度最高且不低于阈值），两者相减即偏移量。
    匹配从目录页之后开始 —— 否则会匹配到目录页自身
    （目录里也印着章名），导致偏移量算错。

    Args:
        page_texts: 每页的原始文本。
        toc_entries: 目录条目。
        start_page: 起始 PDF 页码（1 起）。

    Returns:
        偏移量；无法推断时返回 0。
    """
    toc_pages = set(find_toc_pages(page_texts))
    for entry in toc_entries:
        title = entry.get("title", "")
        printed = entry.get("page", 0)
        if not title or printed <= 0:
            continue
        key = normalize_head(title)
        if not key:
            continue
        best_idx = -1
        best_score = 0.0
        for idx in range(len(page_texts)):
            if idx in toc_pages:
                continue
            score = head_overlap(key, normalize_head(running_head(page_texts[idx])))
            if score > best_score:
                best_score = score
                best_idx = idx
        if best_idx >= 0 and best_score >= 0.5:
            return (best_idx + start_page) - printed
    return 0


def chapters_from_toc(page_texts: List[str],
                      toc_entries: List[Dict[str, Any]],
                      offset: int,
                      total_pages: int) -> List[Dict[str, Any]]:
    """按目录条目生成章节的页码区间。

    Args:
        page_texts: 每页的原始文本。
        toc_entries: 目录条目。
        offset: 印刷页码到 PDF 物理页的偏移量。
        total_pages: PDF 总页数。

    Returns:
        章节列表，每项含 `title`、`start_page`、`end_page`。
    """
    numbered = [e for e in toc_entries if e.get("page", 0) > 0]
    numbered.sort(key=lambda e: e["page"])
    chapters: List[Dict[str, Any]] = []
    for idx, entry in enumerate(numbered):
        start = entry["page"] + offset
        if idx + 1 < len(numbered):
            end = numbered[idx + 1]["page"] + offset - 1
        else:
            end = total_pages
        if start < 1:
            start = 1
        if end > total_pages:
            end = total_pages
        if end < start:
            continue
        chapters.append({
            "title": entry["title"],
            "start_page": start,
            "end_page": end,
        })
    return chapters


def chapters_by_running_head(page_texts: List[str],
                             start_page: int) -> List[Dict[str, Any]]:
    """按运行头聚类生成章节页码区间。

    目录不可用时的退路。

    Args:
        page_texts: 每页的原始文本。
        start_page: 起始 PDF 页码（1 起）。

    Returns:
        章节列表，每项含 `title`、`start_page`、`end_page`。
    """
    chapters: List[Dict[str, Any]] = []
    last_key = ""
    for idx, text in enumerate(page_texts):
        head = running_head(text)
        key = normalize_head(head)
        if not key:
            continue
        if key != last_key:
            chapters.append({
                "title": head,
                "start_page": idx + start_page,
                "end_page": idx + start_page,
            })
            last_key = key
        elif chapters:
            chapters[-1]["end_page"] = idx + start_page
    return chapters


def split_pdf_by_chapter(path: Path,
                         page_texts: List[str]) -> List[Dict[str, Any]]:
    """把 PDF 按章节切开，并填入每章的正文。

    Args:
        path: PDF 路径。
        page_texts: 每页的原始文本。

    Returns:
        章节列表，每项含 `title`、`start_page`、`end_page`、`text`。
    """
    total = len(page_texts)
    toc = parse_toc(page_texts)
    offset = detect_page_offset(page_texts, toc, 1)
    if toc and offset:
        chapters = chapters_from_toc(page_texts, toc, offset, total)
        method = "toc"
    else:
        chapters = chapters_by_running_head(page_texts, 1)
        method = "running_head"

    # 目录之前的内容（版权、目录页本身）单独作为前置块。
    # 这段是**混合内容** —— 版权页、目录、作者的话、编者按混在一起。
    # 整块交给 LLM 判断会得到 READY（因为里面有正文），
    # 所以按运行头再切一刀，让每一小段都有明确标题。
    front: List[Dict[str, Any]] = []
    if method == "toc" and chapters:
        first = chapters[0]["start_page"]
        if first > 1:
            front.extend(_split_front_by_head(page_texts, 1, first - 1))
        chapters = front + chapters

    bodies: Dict[int, str] = {}
    for chapter in chapters:
        for page in range(chapter["start_page"], chapter["end_page"] + 1):
            if page not in bodies:
                bodies[page] = strip_running_head(page_texts[page - 1])
        # 按页保留正文，切分时才能算出每段真实的页码范围
        chapter["pages"] = [
            {"page": page, "text": bodies.get(page, "")}
            for page in range(chapter["start_page"], chapter["end_page"] + 1)
        ]
        chapter["text"] = "\n".join(
            bodies.get(p, "") for p in
            range(chapter["start_page"], chapter["end_page"] + 1))

    return chapters


def _split_front_by_head(page_texts: List[str], start: int,
                          end: int) -> List[Dict[str, Any]]:
    """把前置页按运行头切成多个小段。

    前置内容是混合的 —— 版权页、目录、作者的话、编者按连在一起。
    按运行头切开后，每段有自己的标题，规则层就能准确排除
    「作者的话」「编者按」，而不会误伤同块里的正文。

    Args:
        page_texts: 每页的原始文本。
        start: 起始页（1 起，含）。
        end: 结束页（含）。

    Returns:
        小段列表，每项含 `title`、`start_page`、`end_page`。
    """
    segments: List[Dict[str, Any]] = []
    current_title = ""
    current_start = start
    for page in range(start, end + 1):
        head = running_head(page_texts[page - 1])
        if head and head != current_title:
            if page > current_start:
                segments.append({
                    "title": current_title or "前置内容",
                    "start_page": current_start,
                    "end_page": page - 1,
                })
            current_title = head
            current_start = page
    if end >= current_start:
        segments.append({
            "title": current_title or "前置内容",
            "start_page": current_start,
            "end_page": end,
        })
    return segments
