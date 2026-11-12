"""Tornado 应用与路由。

三个页面：
- `/` —— 操作页，提交书单、查看队列
- `/library` —— 书单页，过滤与浏览全部书
- `/read/<book_id>` —— 阅读页，侧边栏 + Markdown 渲染

一组 JSON API 与一个 WebSocket：
- `/api/ingest` —— 提交书单
- `/api/jobs` —— 队列快照
- `/api/books` —— 书单 + 状态
- `/api/books/<book_id>` —— 单本详情
- `/api/notes/<book_id>` —— 笔记 Markdown 原文
- `/api/notes/<book_id>/progress` —— 保存阅读位置
- `/ws/jobs` —— 实时进度推送
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

import tornado.web

from . import api, handlers
from .jobs import QUEUE
from .state import migrate_manifest


def make_app() -> tornado.web.Application:
    """构造 Tornado 应用。

    Returns:
        应用实例。
    """
    web_dir = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(web_dir))
    static_dir = os.path.join(root, "static")
    template_dir = os.path.join(root, "templates_pawread")

    routes = [
        (r"/", handlers.IngestHandler),
        (r"/library", handlers.LibraryHandler),
        (r"/read/([^/]+)", handlers.ReaderHandler),
        (r"/api/ingest", api.IngestHandler),
        (r"/api/jobs", api.JobsHandler),
        (r"/api/books", api.BooksHandler),
        (r"/api/books/([^/]+)", api.BookHandler),
        (r"/api/notes/([^/]+)", api.NoteHandler),
        (r"/api/notes/([^/]+)/progress", api.ProgressHandler),
        (r"/ws/jobs", api.JobsSocketHandler),
    ]

    app = tornado.web.Application(
        routes,
        template_path=template_dir,
        static_path=static_dir,
        static_url_prefix="/static/",
        default_handler_class=handlers.NotFoundHandler,
        debug=False,
        autoreload=False,
    )
    app.settings["static_hash_cache"] = False
    return app


def run(port: int, address: str) -> None:
    """启动服务。

    Args:
        port: 端口。
        address: 绑定地址。
    """
    import asyncio

    migrate_manifest()
    QUEUE.start()
    app = make_app()
    app.listen(port, address=address)
    print(f"Pawread 已启动： http://{address}:{port}")
    loop = asyncio.get_event_loop()
    loop.run_forever()