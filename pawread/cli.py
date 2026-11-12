#!/usr/bin/env python3
"""Pawread 命令行入口。

**用法**：

```bash
# 从粘贴的书单跑
python3 -m pawread.cli --list-file books.txt

# 从内置清单跑（用户提供的 59 本）
python3 -m pawread.cli --builtin-list

# 只跑发现阶段，看各站点结果
python3 -m pawread.cli --builtin-list --no-read

# 只对指定序号重跑
python3 -m pawread.cli --builtin-list --only 5 9 13
```
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pawread.logging_setup import RunLogger  # noqa: E402
from pawread.pipeline import (  # noqa: E402
    BookRequest,
    parse_booklist,
    render_report,
    run_pipeline,
)

#: 内置书目清单。
BUILTIN_LIST = ROOT / "data" / "booklist.json"


def main() -> None:
    """命令行入口。"""
    ap = argparse.ArgumentParser(description="Pawread 免费电子书流水线")
    ap.add_argument("--list-file", default="",
                    help="粘贴的书单文本文件；缺省用内置清单")
    ap.add_argument("--builtin-list", action="store_true",
                    help="使用内置的 59 本书目清单")
    ap.add_argument("--no-discover", action="store_true",
                    help="跳过发现与下载阶段")
    ap.add_argument("--no-read", action="store_true",
                    help="跳过读书阶段")
    ap.add_argument("--only", type=int, nargs="*", default=None,
                    help="只处理指定序号的条目")
    ap.add_argument("--max-chapters", type=int, default=None,
                    help="每本书最多读几章")
    ap.add_argument("--tier", default="test",
                    help="LLM 模型档位：test / standard / quality / max")
    args = ap.parse_args()

    if args.list_file:
        text = Path(args.list_file).read_text(encoding="utf-8")
        requests = parse_booklist(text)
    else:
        from pawread.sources import load_booklist
        entries = load_booklist(str(BUILTIN_LIST))
        requests = [
            BookRequest(n=e.get("n", idx + 1), title=e.get("title", ""),
                        entry_url=e.get("url", ""))
            for idx, e in enumerate(entries)
        ]

    if args.only:
        requests = [r for r in requests if r.n in set(args.only)]

    if not requests:
        print("没有可处理的书目")
        return

    logger = RunLogger()
    print(f"run_id: {logger.run_id}")
    print(f"书目：{len(requests)} 本\n")

    try:
        outcomes = run_pipeline(
            requests, logger=logger,
            do_discover=not args.no_discover,
            do_read=not args.no_read,
            max_chapters=args.max_chapters,
            tier=args.tier)
    finally:
        logger.finish()

    print(render_report(outcomes))
    print(f"日志：{ROOT / 'logs' / (logger.run_id + '.jsonl')}")


if __name__ == "__main__":
    main()
