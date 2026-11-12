"""Pawread 读书模块。

**职责**：把切好的文本块交给 LLM 产出**详尽笔记**，并合并成一份完整笔记。

**要点**：产出的是笔记不是摘要。摘要为了简洁必然丢信息，
而用户要的是「读完笔记就不用回去重读原文」。提示词在
`pawread/prompts/reader/v1.txt`。

**上游**：`pipeline.py` 的读书阶段。
**下游**：`pipeline.py` 的笔记写盘与报告。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .extract import TextChunk
from .llm import LLMClient, LLMUsage
from .prompt_loader import get_prompt_loader

#: 每块送入 LLM 的最大字符数。超出部分截断，避免单次请求过大。
MAX_CHUNK_CHARS = 12000

#: 合并阶段输入的最大字符数。超过则做两级合并。
MAX_MERGE_CHARS = 40000

#: 模型判定为「装饰性内容」时的输出标记。
SKIP_MARKER = "SKIP"

#: 判定「笔记是否用了中文」的最小汉字数。低于此值说明模型没翻译
#: —— 实测同一份提示词下，有时会直接返回英文原文。
MIN_CHINESE_CHARS = 20

#: 汉字的 Unicode 范围。
CHINESE = re.compile(r"[一-鿿]")


def is_chinese_heavy(text: str) -> bool:
    """判断一段文本是否以中文为主。

    实测同一份提示词下模型有时会直接返回英文原文 —— 提示词
    里的要求不是硬保证，需要一道后置检查。

    Args:
        text: 待检查文本。

    Returns:
        汉字数量达标时返回 True。
    """
    return len(CHINESE.findall(text or "")) >= MIN_CHINESE_CHARS


@dataclass
class ChunkNote:
    """一个文本块的笔记结果。

    字段:
        chunk_index: 对应的块序号。
        start_page: 起始页码。
        end_page: 结束页码。
        chapter: 所属章节名。
        note: 笔记正文；被跳过时为空串。
        skipped: 是否被判定为装饰性内容。
        skip_reason: 跳过原因。
        usage: 本次调用的用量记录。
        chapter_title: 章节标题（原文）。来源优先级：
            配置文件里的 `chapters` > LLM 提炼 > 切分时的运行头。
        chapter_title_zh: 章节标题的用户语言译名。
    """

    chunk_index: int
    start_page: int
    end_page: int
    chapter: str = ""
    note: str = ""
    skipped: bool = False
    skip_reason: str = ""
    usage: Optional[LLMUsage] = None
    chapter_title: str = ""
    chapter_title_zh: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转为可 JSON 序列化的字典。

        Returns:
            笔记记录字典。
        """
        return {
            "chunk_index": self.chunk_index,
            "start_page": self.start_page,
            "end_page": self.end_page,
            "chapter": self.chapter,
            "note": self.note,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "usage": self.usage.to_dict() if self.usage else None,
            "chapter_title": self.chapter_title,
            "chapter_title_zh": self.chapter_title_zh,
        }


@dataclass
class BookNotes:
    """一本书的完整笔记。

    字段:
        title: 书名。
        chunks: 逐块笔记。
        merged: 合并后的整体笔记；未合并时为空串。
        stats: 统计信息。
    """

    title: str
    chunks: List[ChunkNote] = field(default_factory=list)
    merged: str = ""
    stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转为可 JSON 序列化的字典。

        Returns:
            笔记字典。
        """
        return {
            "title": self.title,
            "merged": self.merged,
            "stats": self.stats,
            "chunks": [c.to_dict() for c in self.chunks],
        }

    def render_markdown(self, source: str = "",
                        lang: str = "cn") -> str:
        """渲染成 Markdown 笔记。

        结构：
        1. 抬头（元信息）
        2. **章节目录表** —— 序号 + 章节原名 + 章节译名
        3. 合并后的整体笔记（若有）
        4. 逐章详细笔记

        Args:
            source: 来源文件路径，写进抬头。
            lang: 用户语言，章节译名用它。

        Returns:
            Markdown 文本。
        """
        written = [c for c in self.chunks if not c.skipped and c.note]

        # 按章名分组。同一章被切成多块时（长章节会二次切分），
        # 目录里应该只占一行，正文也应该合成一节 ——
        # 否则会出现三行同名「ONE. The Basics」，锚点也重复。
        groups: List[Tuple[str, List[ChunkNote]]] = []
        for chunk in written:
            name = (chunk.chapter or "").strip() or f"片段 {chunk.chunk_index + 1}"
            if groups and groups[-1][0] == name:
                groups[-1][1].append(chunk)
            else:
                groups.append((name, [chunk]))

        lines = [f"# {self.title}", ""]
        if source:
            lines.append(f"> 来源：`{source}`")
        stats = self.stats or {}
        lines.append(
            f"> 有效章节 {len(groups)}/{len(self.chunks)}　"
            f"跳过 {stats.get('skipped', 0)} 块　"
            f"token 合计 {stats.get('total_tokens', 0)}")
        lines.append("")

        if groups:
            lines.append("## 目录")
            lines.append("")
            lines.append("| # | 章节 | 要点预览 |")
            lines.append("|---|---|---|")
            for i, (name, group) in enumerate(groups, 1):
                anchor = _anchor(name)
                preview = _preview(group[0].note)
                lines.append(f"| {i} | [{name}](#{anchor}) | {preview} |")
            lines.append("")

        if self.merged:
            lines.append("## 全书整合")
            lines.append("")
            lines.append(demote_headings(self.merged))
            lines.append("")

        for name, group in groups:
            lines.append(f"## {name}")
            lines.append("")
            for chunk in group:
                lines.append(demote_headings(chunk.note))
                lines.append("")
        return "\n".join(lines)


def demote_headings(text: str, levels: int = 1) -> str:
    """把笔记正文里的标题层级整体下沉。

    模型输出里自带 `#` / `##` 标题，而笔记文件外层已经用了
    `# 书名` 与 `## 章名`。不处理的话，模型的一级标题会盖掉章名，
    目录锚点也会失效。

    只下沉 1 级 —— 模型自己的层级通常是 `###` / `#####`，
    下沉 2 级会变成 6 级，目录树就没法看了。

    Args:
        text: 笔记正文。
        levels: 下沉几级。

    Returns:
        标题层级下沉后的正文。
    """
    out: List[str] = []
    in_code = False
    for line in text.split("\n"):
        stripped = line.lstrip()
        # 代码块里的 `#` 不是标题
        if stripped.startswith("```"):
            in_code = not in_code
            out.append(line)
            continue
        if not in_code and stripped.startswith("#"):
            hashes = len(stripped) - len(stripped.lstrip("#"))
            if hashes <= 6:
                # 标题里的页码也要去掉：「### 第28至36页」→ 「### 」
                title = stripped[hashes:]
                title = title.strip("*_ ").strip()
                title = re.sub(
                    r"\s*[（(]?\s*第?\s*\d+\s*[-–—至~]\s*\d+\s*页?\s*[）)]?"
                    r"\s*$", "", title).strip()
                title = title.strip("*_ ").strip()
                if not title:
                    # 整个标题就是页码 —— 这行没有信息，丢掉
                    continue
                out.append("#" * min(hashes + levels, 6) + " " + title)
                continue
        out.append(line)
    return "\n".join(out)


def _anchor(heading: str) -> str:
    """生成 Markdown 标题锚点。

    与 GitHub 的锚点规则一致：小写、空格转连字符、去掉标点。

    Args:
        heading: 标题文本。

    Returns:
        锚点字符串。
    """
    text = heading.strip().lower()
    text = re.sub(r"[^\w\s一-鿿-]", "", text)
    return re.sub(r"\s+", "-", text).strip("-")


#: 笔记开头的元信息行。模型有时会先写「章节：xxx」「页码：第28至36页」
#: 这类抬头 —— 它们不是内容，不该进 preview。
META_LINE_PREFIXES = (
    "章节：", "章节:", "页码：", "页码:", "书名：", "书名:",
    "标题：", "标题:", "部分：", "部分:",
    "Chapter:", "Pages:", "Title:", "Section:",
)

#: 笔记开场的白话。模型有时会先说明自己做了什么。
PREVIEW_SKIP_MARKERS = (
    "以下是根据", "以下是", "以下为", "严格按照要求", "完全忠实于原文",
    "不删减", "不概括", "不压缩", "以下内容",
)


def _preview(note: str, limit: int = 100) -> str:
    """生成章节预览片段。

    优先级：
    1. **原文引用块**（`>` 开头）—— 那是作者的原话，信息量最高，
       且天然体现「这一章在讲什么」。
    2. **带标签的行**（`**标签**：说明`）—— 概括性强。
    3. **最长的散文行** —— 兜底。

    不取第一行，是因为模型的开头格式每次都不同
    （「章节：xxx」「以下是…」「完全忠实于原文…」），
    靠穷举关键词跟不上变化。

    Args:
        note: 笔记正文。
        limit: 预览最大字数。

    Returns:
        预览片段。
    """
    quotes: List[str] = []
    tagged: List[str] = []
    prose: List[str] = []

    for line in note.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        # 跳过标题行与分隔线
        if stripped.startswith("#") or set(stripped) <= set("-*_ |"):
            continue

        if stripped.startswith(">"):
            # 原文引用块 —— 去掉引用标记与破折号署名
            text = stripped.lstrip("> ").strip()
            text = re.sub(r"^[*_]+|[*_]+$", "", text).strip()
            # 署名行（——某某，某领域专家）不含内容，跳过
            if re.match(r"^[—–\-]{1,2}\s*\S", text):
                continue
            # 门槛只要 8 字 —— 短句也可能是本章主旨
            if len(text) >= 8:
                quotes.append(text)
            continue

        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if len(cells) < 2:
                continue
            stripped = cells[1]
        else:
            stripped = stripped.lstrip("-*> ").strip()

        has_label = bool(re.match(r"^\*{0,2}[^：:]{2,20}\*{0,2}[：:]", stripped))
        text = re.sub(r"\*{1,2}", "", stripped).strip()
        if len(text) < 15:
            continue
        # 跳过模型的元信息抬头与开场白
        if any(text.startswith(p) for p in META_LINE_PREFIXES):
            continue
        if any(m in text for m in PREVIEW_SKIP_MARKERS):
            continue
        if has_label:
            tagged.append(text)
        else:
            prose.append(text)

    best = ""
    if quotes:
        # 取**最靠前**的引文，不是最长的 —— 靠前的引文通常代表本章主旨，
        # 靠后的可能只是某个具体例子的引文
        best = quotes[0]
    elif tagged:
        best = max(tagged, key=len)
    elif prose:
        best = max(prose, key=len)

    if not best:
        return ""
    if len(best) > limit:
        best = best[:limit].rstrip() + "…"
    return best.replace("|", "\\|")


def chunk_heading(chunk: "ChunkNote") -> str:
    """生成块的 Markdown 标题。

    有章名时用章名，否则退回「片段 N」。

    **不带页码** —— 页码是抓取过程的中间信息，对读者没有价值，
    反而让标题变长、破坏目录的可读性。

    Args:
        chunk: 块笔记。

    Returns:
        标题文本。
    """
    chapter = (chunk.chapter or "").strip()
    if chapter:
        return chapter
    return f"片段 {chunk.chunk_index + 1}"


def _is_skip(text: str) -> bool:
    """判断模型输出是否为 SKIP。

    Args:
        text: 模型原始输出。

    Returns:
        是 SKIP 时返回 True。
    """
    stripped = text.strip()
    if not stripped:
        return True
    first = stripped.splitlines()[0].strip()
    return first.upper().startswith(SKIP_MARKER)


#: 开头白话的开场白特征。模型偶尔会先写一段说明再进入正文。
PREAMBLE_MARKERS = (
    "以下是", "以下为", "根据您提供", "根据你提供", "严格按照要求",
    "以下是根", "以下是根据", "我将", "现在为", "下面是这份",
)

#: 模型结尾的自我交代。
#:
#: 每条都要足够特异 —— 之前放过「以上内容」「全程使用」这种宽泛词，
#: 正常正文里也会出现，会被误删。
SELF_REPORT_MARKERS = (
    "笔记至此结束", "内容完整、未压缩", "未删减、未修改原意",
    "以上即为完整", "本笔记完毕", "如上所述全部内容",
    "确保内容完整", "杜绝英文原文", "全程使用简体中文",
    "严格按照要求生成", "内容已完整保留",
)


#: 页码元信息行。模型会在正文里写这些 —— 它们是抓取过程的中间信息，
#: 对读者没有价值，还要占版面。
PAGE_META_PATTERNS = (
    re.compile(r"^\s*页码\s*[:：]\s*第?\s*\d+\s*[-–—至~]\s*\d+\s*页?\s*$"),
    re.compile(r"^\s*页码\s*[:：]\s*\d+\s*$"),
    re.compile(r"^\s*第\s*\d+\s*[-–—至~]\s*\d+\s*页\s*$"),
    re.compile(r"^\s*第\s*\d+\s*页\s*$"),
    re.compile(r"^\s*Pages?\s*[:：]\s*\d+\s*[-–—]\s*\d+\s*$", re.I),
    re.compile(r"^\s*\d+\s*[-–—]\s*\d+\s*$"),
)


def _is_page_meta_line(line: str) -> bool:
    """判断一行是否是页码元信息。

    Args:
        line: 原始行。

    Returns:
        是页码元信息时返回 True。
    """
    stripped = line.strip()
    if not stripped:
        return False
    return any(p.match(stripped) for p in PAGE_META_PATTERNS)


def strip_preamble(text: str) -> str:
    """去掉模型输出里的自我说明。

    模型有时会在开头写一段说明（「以下是按照要求生成的详细笔记…」），
    或在结尾写一段交代（「（笔记至此结束，内容完整、未压缩…）」）。
    这类话对读者没用，在 Markdown 里会变成孤立的散文。

    做法：开头找第一个 Markdown 标题（`#`）或引用块（`>`），
    之前的部分丢弃；结尾找括号或行内的自我说明，丢弃。

    Args:
        text: 模型原始输出。

    Returns:
        去掉自我说明后的正文。
    """
    lines = text.split("\n")

    # 页码相关的元信息行 —— 模型会在正文里写「页码：第28至36页」，
    # 或者把页码写进标题（「第28至36页」）。这些都是抓取过程的中间信息，
    # 对读者没有价值。
    lines = [ln for ln in lines
             if not _is_page_meta_line(ln)]

    # 开头：丢掉第一个标题/引用块之前的白话
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith(">"):
            if idx > 0:
                head = "\n".join(lines[:idx]).strip()
                if idx >= 3 or any(m in head for m in PREAMBLE_MARKERS):
                    lines = lines[idx:]
            break

    # 结尾：丢掉自我交代与下一章预告
    while lines:
        last = lines[-1].strip()
        if not last:
            lines.pop()
            continue
        if last.startswith(("（", "(")) and any(
                m in last for m in SELF_REPORT_MARKERS):
            lines.pop()
            continue
        if any(m in last for m in SELF_REPORT_MARKERS) and len(last) < 200:
            lines.pop()
            continue
        break

    # 「下一章预告」这类附加段落 —— 从标记行一直删到文末
    marker = re.compile(
        r"^[📌📝🔮✨🎯]?\s*\*{0,2}(下一章|本章小结|章节小结|小结|预告|"
        r"总结与展望|下章)")
    for idx in range(len(lines) - 1, -1, -1):
        if marker.match(lines[idx].strip()):
            del lines[idx:]
            break

    # 模型的自我检查清单 —— 开头是「本笔记严格遵守要求」这类总述，
    # 后面跟一串「未压缩 / 未删减 / 未偷懒」的条目。整段删掉。
    #
    # 注意：这里每个分组都**必须**存在，否则正则会匹配空串，
    # 把整篇笔记从第一行删到文末（踩过这个坑）。
    # 模型的自我检查清单 —— 开头是「本笔记严格遵守要求」这类总述，
    # 后面跟一串「未压缩 / 未删减 / 未偷懒」的条目。整段删掉。
    #
    # 两种句式：
    #   「✅ **本笔记严格遵守要求：**」—— 短，声明式
    #   「✅ **本章笔记完整无删减，内容忠实原文…要求。**」—— 长，带清单
    #
    # 注意：这里每组都**必须**有内容，否则正则会匹配空串，
    # 把整篇笔记从第一行删到文末（踩过这个坑）。
    short_check = re.compile(
        r"(?:本|该|此|上|全)?(?:笔记|记录)"
        r"[\s\*✅❌☑️：:，,、]*"
        r"(?:严格|完全|确实)?"
        r"[\s\*✅❌☑️：:，,、]*"
        r"(?:遵守|遵循|符合|满足)"
        r"[\s\*✅❌☑️：:，,、]*"
        r"(?:要求|指示|说明|规范)")
    long_check = re.compile(
        r"(?:无删减|无省略|未删减|未省略|未压缩|忠实原文|完整无)"
        r"[\s\*✅❌☑️，,、：:]"
        r".{0,80}"
        r"(?:要求|原文|简体中文|输出要求)")
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if len(stripped) < 10 or len(stripped) > 120:
            continue
        if short_check.search(stripped) or long_check.search(stripped):
            del lines[idx:]
            break

    return "\n".join(lines)


def read_chunks(client: LLMClient,
                title: str,
                chunks: List[TextChunk],
                max_chunks: Optional[int] = None,
                prompt_version: str = "v3",
                judge_version: str = "judge-v1",
                judge: bool = True,
                skip_insufficient: bool = True,
                chapter_titles: Optional[Dict[int, Tuple[str, str]]] = None
                ) -> List[ChunkNote]:
    """逐块生成笔记。

    两次调用的分工：
    1. **判断**（可选，`judge-v1.txt`）—— 这段要不要记。
       前言、致谢、作者自述这类装饰内容在这里被排除。
    2. **生成**（`reader/v3.txt`）—— 只有一句指令：
       「生成详细笔记，不允许丢失和压缩内容，不要修改原意，禁止偷懒」。
       实测这一句就足以产出层次分明的结构化笔记，
       提示词写太长反而会干扰模型。

       「不要修改原意」这一句很关键 —— 实测 v3 的笔记里
       保留了 29 处原文引用块（`>` 包裹），而没有这句的 v2 是 0 处。
       原文引句被原样保留，解释跟在后面，原意不会被模型的转述带偏。

    **不要往生成提示词里加任何附加要求**。实测 v4（v3 + 「附上章节
    标题与译名两行」）会让模型切到「按格式交作业」的短格式模式：
    小节标题从 7 个掉到 0 个，正文行数从 583 掉到 66，token 减半。
    提示词一旦变复杂，模型对「写详尽笔记」这件事的注意力就没了。

    **章节名的来源优先级**（方案 C）：
    1. `chapter_titles` —— 配置文件里给的，准确
    2. 切分时的运行头 —— 可能是正文句子，不可靠

    LLM 提炼标题**没有走这条路** —— 它必须独立成一次调用，
    不能混在生成提示词里。

    `max_chunks` 数的是**实际产出笔记的块数**，不是尝试的块数。
    前置页被跳过后不占额度 —— 否则「读 4 章」会全落在版权页上。

    跳过本身也是执行事实 —— 被跳过的块保留记录，不静默丢弃。

    Args:
        client: LLM 客户端。
        title: 书名。
        chunks: 文本块列表。
        max_chunks: 最多产出多少章笔记。缺省不限。
        prompt_version: 生成笔记的提示词版本。
        judge_version: 判断提示词的版本。
        judge: 是否先判断是否值得记。
        skip_insufficient: 是否跳过内容不足的块。
        chapter_titles: 块序号 → `(标题, 译名)`。来自配置文件的章节表。

    Returns:
        逐块笔记记录列表。
    """
    loader = get_prompt_loader()
    notes: List[ChunkNote] = []
    produced = 0
    titles = chapter_titles or {}

    for chunk in chunks:
        if max_chunks is not None and produced >= max_chunks:
            break
        if chunk.insufficient:
            if skip_insufficient:
                notes.append(ChunkNote(
                    chunk_index=chunk.index,
                    start_page=chunk.start_page,
                    end_page=chunk.end_page,
                    chapter=chunk.chapter,
                    skipped=True,
                    skip_reason=(f"正文仅 {chunk.approx_chars} 字符，"
                                 f"低于最小可总结长度"),
                ))
                continue

        body = chunk.text[:MAX_CHUNK_CHARS]
        fields = {
            "title": title,
            "chapter": chunk.chapter,
            "start_page": chunk.start_page,
            "end_page": chunk.end_page,
            "text": body,
        }

        # 第一步：判断是否值得记
        if judge:
            try:
                verdict, judge_usage = client.complete(
                    loader.render("reader", judge_version, **fields),
                    max_tokens=64, temperature=0.0)
            except Exception as exc:  # noqa: BLE001 - 判断失败不阻断
                verdict = ""
                judge_usage = None
                judge_error = f"{type(exc).__name__}: {exc}"
            else:
                judge_error = ""
            if _is_skip(verdict):
                notes.append(ChunkNote(
                    chunk_index=chunk.index,
                    start_page=chunk.start_page,
                    end_page=chunk.end_page,
                    chapter=chunk.chapter,
                    skipped=True,
                    skip_reason="模型判定为装饰性内容",
                    usage=judge_usage,
                ))
                continue
            if judge_error:
                notes.append(ChunkNote(
                    chunk_index=chunk.index,
                    start_page=chunk.start_page,
                    end_page=chunk.end_page,
                    chapter=chunk.chapter,
                    skipped=True,
                    skip_reason=f"判断调用失败：{judge_error}",
                ))
                continue

        # 第二步：生成笔记
        prompt = loader.render("reader", prompt_version, **fields)
        try:
            content, usage = client.complete(
                prompt, max_tokens=4000, temperature=0.2)
        except Exception as exc:  # noqa: BLE001 - 单块失败不应中断整本
            notes.append(ChunkNote(
                chunk_index=chunk.index,
                start_page=chunk.start_page,
                end_page=chunk.end_page,
                chapter=chunk.chapter,
                skipped=True,
                skip_reason=f"调用失败：{type(exc).__name__}: {exc}",
            ))
            continue

        # 清理正文。标题信息不混在生成提示词里 —— 见 read_chunks 的说明。
        content = strip_preamble(content)

        # 后置检查：模型有时会直接返回英文原文，重试一次。
        if not is_chinese_heavy(content):
            try:
                retry, retry_usage = client.complete(
                    prompt + "\n\n【重要】上面的要求未满足："
                            "必须用**简体中文**输出，不要英文原文，"
                            "不要繁体字。现在重新输出笔记。",
                    max_tokens=4000, temperature=0.1)
            except Exception:  # noqa: BLE001 - 重试失败就用原结果
                retry = ""
            if is_chinese_heavy(retry):
                content = retry
                usage = retry_usage

        # 章节名优先级：配置 > 运行头
        conf_title, conf_title_zh = titles.get(chunk.index, ("", ""))
        final_title = conf_title or chunk.chapter

        notes.append(ChunkNote(
            chunk_index=chunk.index,
            start_page=chunk.start_page,
            end_page=chunk.end_page,
            chapter=final_title,
            chapter_title=final_title,
            chapter_title_zh=conf_title_zh,
            note=content.strip(),
            skipped=False,
            usage=usage,
        ))
        produced += 1
    return notes


def merge_notes(client: LLMClient,
                title: str,
                notes: List[ChunkNote]) -> str:
    """把逐块笔记合并成整体笔记。

    块数不多时直接单次合并；内容超限时做两级合并，
    先分组合并再合并总结果。

    合并提示词与生成提示词同源 —— 同样强调「不允许丢失和压缩」。
    合并是压缩风险最高的一步：一旦在这里丢了信息，
    逐块记的详细笔记也白记了。

    Args:
        client: LLM 客户端。
        title: 书名。
        notes: 逐块笔记。

    Returns:
        合并后的笔记；无可合并内容时返回空串。
    """
    written = [n for n in notes if not n.skipped and n.note]
    if not written:
        return ""

    body = "\n\n".join(
        f"【第 {n.start_page}-{n.end_page} 页】\n{n.note}" for n in written)

    if len(body) > MAX_MERGE_CHARS:
        return _merge_two_level(client, title, written)

    prompt = (
        f"下面是《{title}》的逐段读书笔记。\n\n"
        "把它们合并成一份完整的笔记，要求：\n"
        "1. **不允许丢失和压缩内容，不要修改原意，禁止偷懒** —— "
        "原文有的每一条都要保留，不许合并同类项、不许只留结论、"
        "不许概括\n"
        "2. 同一主题的内容归到一起，但不因此丢掉任何一条\n"
        "3. 保留原有的数字、术语、案例、专有名词与英文原文；"
        "原文引句用 `>` 引用块原样保留\n"
        "4. 用**简体中文**，按主题分节，节标题用 `###`\n"
        "5. 只输出笔记本身，不要开场白、不要总结\n\n"
        f"{body}")
    try:
        content, _ = client.complete(prompt, max_tokens=8000, temperature=0.2)
    except Exception:  # noqa: BLE001 - 合并失败时退回逐块输出
        return ""
    return content.strip()


def _merge_two_level(client: LLMClient,
                     title: str,
                     written: List[ChunkNote]) -> str:
    """内容超限时的两级合并。

    Args:
        client: LLM 客户端。
        title: 书名。
        written: 已产出笔记的块。

    Returns:
        合并后的笔记。
    """
    groups: List[List[ChunkNote]] = []
    current: List[ChunkNote] = []
    size = 0
    for note in written:
        if size + len(note.note) > MAX_MERGE_CHARS and current:
            groups.append(current)
            current = []
            size = 0
        current.append(note)
        size += len(note.note)
    if current:
        groups.append(current)

    merged_groups: List[str] = []
    for group in groups:
        body = "\n\n".join(
            f"【第 {n.start_page}-{n.end_page} 页】\n{n.note}" for n in group)
        prompt = (
            f"下面是《{title}》的部分读书笔记。合并这一部分，"
            "**不允许丢失和压缩内容，不要修改原意，禁止偷懒** —— "
            "每一条都要保留。用简体中文，按主题分节。\n\n"
            f"{body}")
        try:
            content, _ = client.complete(prompt, max_tokens=8000,
                                          temperature=0.2)
            merged_groups.append(content.strip())
        except Exception:  # noqa: BLE001 - 单组失败时退回原文拼接
            merged_groups.append(body)

    final = "\n\n".join(merged_groups)
    prompt = (
        f"下面是《{title}》各部分笔记的合并结果。再合并成一份完整笔记，"
        "**不允许丢失和压缩内容，不要修改原意，禁止偷懒**。"
        "用简体中文，按主题分节，节标题用 `###`。只输出笔记本身。\n\n"
        f"{final}")
    try:
        content, _ = client.complete(prompt, max_tokens=8000, temperature=0.2)
        return content.strip()
    except Exception:  # noqa: BLE001 - 最终合并失败时退回分组结果
        return final
