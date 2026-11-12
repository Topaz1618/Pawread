"""Web 层。

三个页面 + 一组 JSON API + WebSocket 进度推送。

- `app.py` —— Application 与路由表
- `handlers.py` —— 页面 Handler
- `api.py` —— JSON API Handler
- `jobs.py` —— 下载与读书的任务队列
- `state.py` —— 书单、状态、笔记的统一读取层
"""

from __future__ import annotations

__all__ = ["app", "handlers", "api", "jobs", "state"]
