#!/usr/bin/env python3
"""Pawread Web 服务入口。

启动：

```bash
python3 server.py
```

绑定地址与端口从环境变量读（见 `config/env.example`）：

| 变量 | 含义 | 缺省 |
|---|---|---|
| `PAWREAD_HOST` | 绑定地址 | `127.0.0.1` |
| `PAWREAD_PORT` | 端口 | `8026` |

命令行参数优先于环境变量。

页面：
- `/` —— 操作页，提交书单、查看处理队列
- `/library` —— 书单页，按优先级与状态过滤
- `/read/<book_id>` —— 阅读页，侧边栏 + Markdown 渲染
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from pawread.env import get_int, get_str, load_env  # noqa: E402

#: 绑定地址的缺省值。只监听本机，不对外暴露。
DEFAULT_HOST = "127.0.0.1"

#: 端口的缺省值。
DEFAULT_PORT = 8026


def main() -> None:
    """解析参数并启动服务。"""
    ap = argparse.ArgumentParser(description="Pawread Web 服务")
    ap.add_argument("--port", type=int, default=None,
                    help=f"端口（缺省读 PAWREAD_PORT，再缺省 {DEFAULT_PORT}）")
    ap.add_argument("--host", default=None,
                    help=f"绑定地址（缺省读 PAWREAD_HOST，再缺省 {DEFAULT_HOST}）")
    args = ap.parse_args()

    load_env()

    host = args.host or get_str("PAWREAD_HOST", DEFAULT_HOST)
    port = args.port or get_int("PAWREAD_PORT", DEFAULT_PORT)

    from pawread.web.app import run
    run(port=port, address=host)


if __name__ == "__main__":
    main()
