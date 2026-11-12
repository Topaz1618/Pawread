#!/usr/bin/env python3
"""小规模端到端测试：读一本已下载的书，生成 Markdown 笔记。

按**章节**切分 —— 每章一块（过长则再切），不再是固定页数。

用法：
```bash
python3 tools/demo_read.py --book 6 --chapters 4
python3 tools/demo_read.py --book "Thinking in Systems" --model qwen-flash
```
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pawread.booklists import (  # noqa: E402
    chapter_titles_for,
    find_by_id,
    load_booklist_doc,
    slugify,
)
from pawread.extract import build_chunks  # noqa: E402
from pawread.llm import LLMClient  # noqa: E402
from pawread.reader import BookNotes, read_chunks  # noqa: E402


def find_book_file(name: str) -> tuple:
    """按序号或书名找到已下载的文件。

    manifest 里的 `file.path` 可能指向历史目录，
    因此先按 manifest 记录找，找不到再回退到本项目 `books/` 目录
    下按书名 slug 匹配。

    Args:
        name: 序号数字或书名片段。

    Returns:
        `(书名, 文件路径, 书单条目)`；未找到时前两项为 None。
    """
    manifest = json.loads((ROOT / "books" / "manifest.json").read_text(
        encoding="utf-8"))
    books_dir = ROOT / "books"
    doc = load_booklist_doc(ROOT / "data" / "booklists" / "personal.json")

    for entry in manifest:
        if entry.get("status") != "downloaded":
            continue
        matched = (str(entry.get("n")) == str(name)
                   or str(name).lower() in entry.get("title", "").lower())
        if not matched:
            continue
        title = entry["title"]
        recorded = entry.get("file") or {}
        path = Path(recorded.get("path", ""))
        if path.exists():
            return title, path, find_by_id(doc, slugify(title))
        slug = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_")[:80]
        for ext in (".pdf", ".epub", ".txt"):
            candidate = books_dir / f"{slug}{ext}"
            if candidate.exists():
                return title, candidate, find_by_id(doc, slugify(title))
    return None, None, None


def main() -> None:
    """跑一遍「抽文本 → 按章切分 → LLM 笔记 → 写 Markdown」。"""
    ap = argparse.ArgumentParser(description="小规模读书流程测试")
    ap.add_argument("--book", default="6",
                    help="书目序号或书名片段（默认 6 = Thinking in Systems）")
    ap.add_argument("--chapters", type=int, default=4,
                    help="最多读几章（默认 4）")
    ap.add_argument("--model", default="qwen-flash", help="模型名")
    ap.add_argument("--out", default="", help="笔记输出目录")
    args = ap.parse_args()

    title, path, entry = find_book_file(args.book)
    if not path:
        print(f"未找到已下载的书：{args.book}")
        return

    print(f"书名：{title}")
    print(f"文件：{path}")

    # 配置文件里的章节表（方案 C 的第一级来源）。
    # 配置里没有章节名时，用切分时的运行头 —— 不可靠，但不加要求就不污染生成。
    titles: Dict[int, Tuple[str, str]] = {}
    if entry:
        configured = chapter_titles_for(entry, lang="cn")
        if configured:
            print(f"配置章节表：{len(configured)} 条（优先使用）")
            titles = {i: (name, zh) for i, (name, zh)
                      in enumerate(configured)}

    chunks = build_chunks(path)
    print(f"按章切分：共 {len(chunks)} 块")
    if not chunks:
        print("切分失败")
        return
    for chunk in chunks:
        flag = "  [内容不足，跳过]" if chunk.insufficient else ""
        print(f"  块 {chunk.index}: {chunk.chapter[:40]!r} "
              f"第 {chunk.start_page}-{chunk.end_page} 页 "
              f"{chunk.approx_chars} 字符{flag}")

    client = LLMClient(tier="test")
    started = time.monotonic()
    notes = read_chunks(client, title, chunks, max_chunks=args.chapters,
                        chapter_titles=titles)
    elapsed = time.monotonic() - started

    print()
    for note in notes:
        if note.skipped:
            print(f"块 {note.chunk_index} 跳过：{note.skip_reason}")
            continue
        token = note.usage.total_tokens if note.usage else 0
        model = note.usage.model if note.usage else "?"
        print(f"\n--- 块 {note.chunk_index} {note.chapter!r} "
              f"(第 {note.start_page}-{note.end_page} 页) "
              f"模型={model} token={token} ---")
        print(note.note[:1200])

    written = [n for n in notes if not n.skipped and n.note]
    skipped = [n for n in notes if n.skipped]
    print(f"\n=== 用量 === 耗时 {elapsed:.1f}s")
    print(f"有效块 {len(written)} / 跳过 {len(skipped)}")
    print(json.dumps(client.summary()["pool"], ensure_ascii=False, indent=2))

    book_notes = BookNotes(
        title=title,
        chunks=notes,
        stats={
            "skipped": len(skipped),
            "total_tokens": client.summary()["pool"]["total_tokens"],
        },
    )
    out_dir = Path(args.out) if args.out else ROOT / "notes"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_ " else "_"
                   for c in title).strip().replace(" ", "_")
    out_path = out_dir / f"{safe}.md"
    out_path.write_text(book_notes.render_markdown(str(path)), encoding="utf-8")
    print(f"\n笔记写入：{out_path}")


if __name__ == "__main__":
    main()
