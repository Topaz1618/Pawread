"""Pawread 文本抽取。

**职责**：把已下载的电子书（PDF / EPUB / TXT）按**章节**切成带页码的
文本块，供读书阶段逐块交给 LLM 记笔记。本模块不做笔记、不做下载。

**章节切分**在 `pawread/chapters.py`，本模块负责把切好的章节转成
文本块，并做规则级的内容过滤。

**上游**：`pipeline.py` 的读书阶段。
**下游**：`pawread/reader.py`。

**与既有脚本的关系**：文本抽取的底层能力（`pdftotext` / EPUB 解包）
已在 `pawread/fetcher.py` 中实现，本模块 **import 复用**，
不复制粘贴。差别在于本模块按章切块并保留页码，而校验部分只读前若干页
做标题匹配。
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .chapters import (
    running_head,
    split_pdf_by_chapter,
    strip_running_head,
)

#: 单个文本块的最大字符数。章节过长时按此上限二次切分，
#: 避免单块内容超出 LLM 的舒适输入长度。
MAX_CHARS_PER_CHUNK = 18000

#: 高置信度前置页标记。命中即丢弃 —— 这些内容（版权、ISBN、印次）
#: 没有任何阅读价值，规则判定不会出错，也不浪费 token。
FRONT_MATTER_STRICT = (
    "copyright", "all rights reserved", "isbn", "published by",
    "版权", "ISBN",
)

#: 噪声页判定：正文长度低于此值且不含完整句子，视为页眉页脚、
#: 空白页等无内容页。
NOISE_MAX_CHARS = 120

#: 噪声页判定：句子成分（连续三个以上字母构成的词）少于此个数时，
#: 认为没有实际句子，只是残留的页码与版面标记。
NOISE_MIN_WORDS = 3

#: 一块正文少于这个字符数就不足以支撑一次笔记。
#: 低于此值的块直接标记为「内容不足」跳过 —— 否则模型会凭对该书的
#: 先验知识编造内容（实测：仅含扉页的 53 字符块，模型输出了
#: 「系统是由相互连接的组成部分构成的整体」，原文并无此内容）。
MIN_CHUNK_CHARS = 300

#: 章节级的装饰页标题。命中则整章跳过。
#:
#: 为什么在规则层做：**目录切分会把「版权页 + 目录 + 作者的话 +
#: 编者按」合并成一个「前置内容」块**。这是混合内容 —— 里面既有该跳的
#: 也有该留的，整块交给 LLM 判断会得到 READY（因为里面有正文）。
#: 但这些页本身有明确的标题，规则判定不会出错，也不浪费一次 LLM 调用。
FRONT_MATTER_TITLES = (
    "a note from the author", "a note from the editor",
    "about the author", "editor's acknowledgments",
    "editor’s acknowledgments", "acknowledgments", "acknowledgements",
    "copyright", "about the publisher",
    "作者的话", "作者自述", "前言", "序", "致谢", "编��按",
    "版权", "译者序", "关于作者",
)

#: 章节标题里表示「附录」的词。附录本身是有价值的内容，
#: 但术语表、索引这类属于参考资料，不是论述。
FRONT_MATTER_TITLE_EXACT = (
    "index", "bibliography", "notes", "glossary",
    "contents", "table of contents",
    "索引", "参考文献", "术语表", "目录",
)

#: 句子末尾的虚词。运行头取到页面第一行、遇到引文时会被截断，
#: 末词必然是这些虚词之一。章节名不会这样结尾。
SENTENCE_END_WORDS = (
    "is", "are", "was", "were", "be", "been", "the", "a", "an",
    "and", "or", "but", "to", "of", "in", "on", "at", "for",
    "with", "as", "that", "this", "it", "its", "their", "his",
    "her", "our", "your", "we", "they", "he", "she",
    "是", "的", "了", "和", "与", "在", "把", "被",
)


@dataclass
class TextChunk:
    """一个待记笔记的文本块（对应书里的一个章节或章节的一段）。

    字段:
        index: 块序号，从 0 起。
        start_page: 起始页码（PDF 为 1 起；EPUB 用章节序号）。
        end_page: 结束页码（含）。
        chapter: 所属章节名。
        text: 块内正文。
        approx_chars: 正文字符数。
        skipped_front_matter: 本块因规则过滤而跳过的段落数。
        insufficient: 正文字符数是否不足以支撑一次笔记。
            为 True 时不应送去 LLM —— 模型会凭对该书的先验知识编造内容。
    """

    index: int
    start_page: int
    end_page: int
    text: str
    chapter: str = ""
    approx_chars: int = 0
    skipped_front_matter: int = 0
    insufficient: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转为可 JSON 序列化的字典。

        Returns:
            含块元数据与正文的字典。
        """
        return {
            "index": self.index,
            "start_page": self.start_page,
            "end_page": self.end_page,
            "chapter": self.chapter,
            "approx_chars": self.approx_chars,
            "skipped_front_matter": self.skipped_front_matter,
            "insufficient": self.insufficient,
            "text": self.text,
            **self.meta,
        }


def pdf_page_text(path: Path, page: int) -> str:
    """抽取 PDF 单页的文本。

    Args:
        path: PDF 路径。
        page: 页码，从 1 起。

    Returns:
        该页文本；抽取失败时返回空字符串。
    """
    try:
        out = subprocess.run(
            ["pdftotext", "-f", str(page), "-l", str(page), str(path), "-"],
            capture_output=True, text=True, timeout=120)
        return out.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def pdf_page_count(path: Path) -> int:
    """读取 PDF 总页数。

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


def is_noise_page(text: str) -> bool:
    """判断一段文本是否是页眉页脚、空白页之类的无内容残留。

    PDF 每页底部常有「TIS final pgs xviii 5/2/09 10:37:34」这类版面标记，
    单独成页时不含任何实质内容。

    Args:
        text: 段落文本。

    Returns:
        是无内容页时返回 True。
    """
    stripped = text.strip()
    if len(stripped) > NOISE_MAX_CHARS:
        return False
    words = re.findall(r"[A-Za-z]{3,}", stripped)
    return len(words) < NOISE_MIN_WORDS


def is_front_matter(text: str) -> bool:
    """判断一段文本是否是**高置信度**的机械前置页。

    只处理版权信息、ISBN、印次这类完全无阅读价值的内容。
    序言 / 致谢 / 导言一类**不**在此判定范围内 ——
    实测《Thinking in Systems》的 "A NOTE FROM THE AUTHOR" 靠关键词
    匹配不到，而 "Introduction" 章节是正文第一章，靠关键词会误杀。
    语义判断交给 LLM（见 `pawread/prompts/reader/v1.txt`）。

    Args:
        text: 段落文本。

    Returns:
        是机械前置页时返回 True。
    """
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in FRONT_MATTER_STRICT)


def is_quote_page(text: str) -> bool:
    """判断一段文本是否是纯引文页。

    实测《Thinking in Systems》第 16 页是编者按里的一段引文 ——
    页面上除了引文本身没有作者的论述。整页被切成一个「章节」后，
    LLM 会为它写出「原文逐句解析」这种笔记，其实没有价值。

    判定依据：整段没有结构性标记（Markdown 标题、列表项、
    编号段落），也没有作者自己的说明性文字。

    Args:
        text: 段落文本。

    Returns:
        是纯引文时返回 True。
    """
    stripped = text.strip()
    if not stripped:
        return True
    lines = [l.strip() for l in stripped.split("\n") if l.strip()]
    if not lines:
        return True
    for line in lines:
        # 有列表项、编号、标题 —— 说明是结构化正文
        if re.match(r"^([-*+•]|\d+[.)]|#{1,6}|>)\s*", line):
            return False
    # 全是短句的散文段落 —— 更像引文或正文
    # 用句长与引号密度做粗判：引文页通常有引号且句子整齐
    quoted = stripped.count('"') + stripped.count('“')
    return quoted >= 2 and len(stripped) < 2000


def is_front_matter_chapter(title: str) -> bool:
    """判断一个章节标题是否指向装饰性内容。

    整章都是装饰内容时（作者的话、编者按、致谢、索引），
    标题本身就足以确认 —— 不需要 LLM 判断。

    还有一种情况：标题其实是一句话。实测《Thinking in Systems》
    第 16 页是编者按里的一段引文，页面第一行是引文的开头，
    被当成运行头就成了「标题」。这种「标题」又长又是完整的句子，
    不是章节名 —— 对应的内容也是引文，没有记笔记的价值。

    Args:
        title: 章节标题。

    Returns:
        是装饰性章节时返回 True。
    """
    if not title:
        return False
    stripped = title.strip()
    low = stripped.lower()
    if low in FRONT_MATTER_TITLE_EXACT:
        return True
    if any(marker in low for marker in FRONT_MATTER_TITLES):
        return True
    # 标题其实是一句话 —— 内容是引文。
    # 判据：长度超长，且以虚词结尾（is / the / and / to / of 等）。
    # 运行头取的是页面第一行，遇到引文时会被截在半句上，
    # 末词必然是虚词。章节名不会这样结尾。
    if len(stripped) > 40:
        last = stripped.split()[-1].strip(",.;:!?'\"").lower()
        if last in SENTENCE_END_WORDS:
            return True
    return False


def epub_chapters(path: Path) -> List[Dict[str, Any]]:
    """按 spine 顺序读取 EPUB 的章节。

    Args:
        path: EPUB 路径。

    Returns:
        章节列表，每项含 `title`、`start_page`、`end_page`、`text`。
    """
    import html
    import zipfile

    try:
        with zipfile.ZipFile(path) as archive:
            from .fetcher import epub_spine_order
            names = epub_spine_order(archive)
            if not names:
                names = sorted(n for n in archive.namelist() if n.endswith(".html"))
            chapters: List[Dict[str, Any]] = []
            for idx, name in enumerate(names):
                try:
                    raw = archive.read(name).decode("utf-8", "replace")
                except (KeyError, OSError):
                    continue
                plain = re.sub(r"<[^>]+>", " ", raw)
                text = re.sub(r"\s+", " ", html.unescape(plain)).strip()
                title = ""
                match = re.search(r"<h[1-3][^>]*>(.*?)</h[1-3]>", raw,
                                  re.I | re.S)
                if match:
                    title = re.sub(r"\s+", " ",
                                  html.unescape(
                                      re.sub(r"<[^>]+>", "", match.group(1))
                                  )).strip()
                chapters.append({
                    "title": title or name,
                    "start_page": idx + 1,
                    "end_page": idx + 1,
                    "text": text,
                })
            return chapters
    except (OSError, zipfile.BadZipFile):
        return []


def plain_text_chapters(path: Path) -> List[Dict[str, Any]]:
    """把纯文本文件按标题行切成章。

    以形如 `第X章` / `Chapter N` / `PART N` 的行作为章起点。

    Args:
        path: TXT 路径。

    Returns:
        章节列表；读不到内容时返回空列表。
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    heading = re.compile(
        r"^\s*(第[一二三四五六七八九十百零〇\d]+[章节篇回卷]"
        r"|chapter\s+[\divxlc]+|part\s+[\divxlc]+)\b.*$",
        re.I)

    chapters: List[Dict[str, Any]] = []
    current_title = ""
    buffer: List[str] = []
    for line in raw.split("\n"):
        if heading.match(line):
            if buffer:
                chapters.append({
                    "title": current_title,
                    "start_page": len(chapters) + 1,
                    "end_page": len(chapters) + 1,
                    "text": "\n".join(buffer).strip(),
                })
                buffer = []
            current_title = line.strip()
            continue
        buffer.append(line)
    if buffer:
        chapters.append({
            "title": current_title,
            "start_page": len(chapters) + 1,
            "end_page": len(chapters) + 1,
            "text": "\n".join(buffer).strip(),
        })
    return [c for c in chapters if c["text"]]


def split_by_chars(chapters: List[Dict[str, Any]],
                   max_chars: int = MAX_CHARS_PER_CHUNK
                   ) -> List[Dict[str, Any]]:
    """把过长的章节按字符数二次切分。

    在段落边界切，不切断句子。PDF 章节带 `pages` 字段时，
    切出来的每一段会带上真实的页码范围。

    Args:
        chapters: 章节列表。
        max_chars: 单块最大字符数。

    Returns:
        切分后的块列表。
    """
    units: List[Dict[str, Any]] = []
    for chapter in chapters:
        text = chapter.get("text") or ""
        if len(text) <= max_chars:
            units.append(chapter)
            continue

        pages = chapter.get("pages")
        if pages:
            units.extend(_split_pdf_pages(pages, chapter, max_chars))
            continue

        paragraphs = re.split(r"\n\s*\n", text)
        buf: List[str] = []
        size = 0
        part = 1
        for para in paragraphs:
            if size + len(para) > max_chars and buf:
                units.append({
                    "title": chapter["title"],
                    "start_page": chapter["start_page"],
                    "end_page": chapter["end_page"],
                    "text": "\n\n".join(buf),
                    "part": part,
                })
                buf = []
                size = 0
                part += 1
            buf.append(para)
            size += len(para)
        if buf:
            units.append({
                "title": chapter["title"],
                "start_page": chapter["start_page"],
                "end_page": chapter["end_page"],
                "text": "\n\n".join(buf),
                "part": part,
            })
    return units


def _split_pdf_pages(pages: List[Dict[str, Any]],
                     chapter: Dict[str, Any],
                     max_chars: int) -> List[Dict[str, Any]]:
    """按字符数切分 PDF 章节，并保留真实页码范围。

    Args:
        pages: 章节的逐页正文，每项含 `page` 与 `text`。
        chapter: 章节字典。
        max_chars: 单块最大字符数。

    Returns:
        切分后的块列表，每项含真实的 `start_page` 与 `end_page`。
    """
    units: List[Dict[str, Any]] = []
    buf: List[str] = []
    buf_pages: List[int] = []
    size = 0
    part = 1

    for page_item in pages:
        page_no = page_item["page"]
        for para in re.split(r"\n\s*\n", page_item.get("text") or ""):
            if size + len(para) > max_chars and buf:
                units.append({
                    "title": chapter["title"],
                    "start_page": buf_pages[0],
                    "end_page": buf_pages[-1],
                    "text": "\n\n".join(buf),
                    "part": part,
                })
                buf = []
                buf_pages = []
                size = 0
                part += 1
            buf.append(para)
            size += len(para)
            if page_no not in buf_pages:
                buf_pages.append(page_no)

    if buf:
        units.append({
            "title": chapter["title"],
            "start_page": buf_pages[0] if buf_pages else chapter["start_page"],
            "end_page": buf_pages[-1] if buf_pages else chapter["end_page"],
            "text": "\n\n".join(buf),
            "part": part,
        })
    return units


def build_chunks(path: Path,
                 max_chars_per_chunk: int = MAX_CHARS_PER_CHUNK,
                 skip_front_matter: bool = True) -> List[TextChunk]:
    """把电子书按章节切成带页码的文本块。

    PDF 按目录切（无目录时按运行头聚类）；EPUB 按 spine 章节切；
    TXT 按标题行切。过长的章节按 `max_chars_per_chunk` 二次切分。

    规则过滤两级：
    1. 机械前置页（版权 / ISBN）—— 高置信度，直接丢弃。
    2. 无内容页（页眉页脚残留、空白页）—— 直接丢弃。

    语义过滤（序言 / 致谢 / 作者自述）交给 LLM，见
    `pawread/prompts/reader/v1.txt`。

    Args:
        path: 电子书路径。
        max_chars_per_chunk: 单块最大字符数。
        skip_front_matter: 是否跳过机械前置页与无内容页。

    Returns:
        文本块列表；文件不支持时返回空列表。
    """
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        total = pdf_page_count(path)
        page_texts = [pdf_page_text(path, page)
                      for page in range(1, total + 1)]
        if not page_texts:
            return []
        raw_chapters = split_pdf_by_chapter(path, page_texts)
    elif suffix == ".epub":
        raw_chapters = epub_chapters(path)
    elif suffix in (".txt", ".text"):
        raw_chapters = plain_text_chapters(path)
    else:
        return []

    if not raw_chapters:
        return []

    units = split_by_chars(raw_chapters, max_chars_per_chunk)

    chunks: List[TextChunk] = []
    for unit in units:
        title = unit.get("title", "")

        # 章节级前置页判定。整章都是装饰内容时直接跳过 ——
        # 「A Note from the Author」「A Note from the Editor」
        # 这类标题明确，不需要 LLM 判断。
        if skip_front_matter and is_front_matter_chapter(title):
            continue

        kept: List[str] = []
        skipped = 0
        for para in re.split(r"\n\s*\n", unit.get("text") or ""):
            text = para.strip()
            if not text:
                continue
            if skip_front_matter:
                if is_noise_page(text):
                    skipped += 1
                    continue
                if is_front_matter(text):
                    skipped += 1
                    continue
                if is_quote_page(text):
                    skipped += 1
                    continue
            kept.append(text)
        if not kept:
            continue
        body = "\n\n".join(kept)
        chunks.append(TextChunk(
            index=len(chunks),
            start_page=unit["start_page"],
            end_page=unit["end_page"],
            chapter=title,
            text=body,
            approx_chars=len(body),
            skipped_front_matter=skipped,
            insufficient=len(body) < MIN_CHUNK_CHARS,
        ))
    return chunks
