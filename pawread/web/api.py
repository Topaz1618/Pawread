"""JSON API 与 WebSocket。

进度推送走 WebSocket 而不是轮询 —— 抓取一本书要几分钟，
轮询既费请求又延迟。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import tornado.web
import tornado.websocket

from .base import BaseHandler
from .jobs import MAX_BATCH, QUEUE
from .state import (ROOT, find_book, list_books, load_state,
                    read_note, save_state)


class IngestHandler(BaseHandler):
    """提交书单。

    请求体：`{"titles": ["书名", ...], "authors": ["作者", ...]}`
    """

    def post(self) -> None:
        """接收书单并入队。

        Returns:
            无。
        """
        body = self.json_body()
        titles = body.get("titles") or []
        authors = body.get("authors") or []

        if not isinstance(titles, list):
            self.write_json({"error": "titles 必须是数组"}, 400)
            return

        cleaned: List[str] = []
        for item in titles:
            if not isinstance(item, str):
                continue
            text = item.strip()
            if text:
                cleaned.append(text)

        if not cleaned:
            self.write_json({"error": "书单为空"}, 400)
            return
        if len(cleaned) > MAX_BATCH:
            self.write_json({
                "error": f"一次最多 {MAX_BATCH} 本，本次收到 {len(cleaned)} 本",
                "accepted": len(cleaned[:MAX_BATCH]),
            }, 400)
            return

        QUEUE.start()
        jobs = QUEUE.submit(cleaned, authors)
        self.write_json({
            "ok": True,
            "count": len(jobs),
            "jobs": [j.to_dict() for j in jobs],
        })


class JobsHandler(BaseHandler):
    """队列快照。"""

    def get(self) -> None:
        """返回全部任务。

        Returns:
            无。
        """
        self.write_json({"jobs": QUEUE.snapshot()})


class BooksHandler(BaseHandler):
    """书单 + 状态。"""

    def get(self) -> None:
        """返回全部书。

        查询参数 `lang` 指定译名语言，默认 `cn`。

        Returns:
            无。
        """
        lang = self.get_argument("lang", self._lang())
        books = list_books(lang)
        self.write_json({
            "books": books,
            "total": len(books),
            "noted": sum(1 for b in books if b.get("has_note")),
            "lang": lang,
        })

    def _lang(self) -> str:
        """从浏览器请求里取语言。

        优先看 `Accept-Language`，然后是 `?lang=`。

        Returns:
            语言代码。
        """
        query = self.get_argument("lang", "")
        if query:
            return query
        header = self.request.headers.get("Accept-Language", "")
        for part in header.split(","):
            code = part.split(";")[0].strip().lower()
            if code.startswith("zh"):
                return "cn"
            if code.startswith("en"):
                return "en"
            if code.startswith("es"):
                return "es"
            if code.startswith("de"):
                return "de"
        return "cn"


class BookHandler(BaseHandler):
    """单本详情。"""

    def get(self, book_id: str) -> None:
        """返回一本书的详情。

        Args:
            book_id: 条目 id。

        Returns:
            无。
        """
        book = find_book(book_id)
        if book is None:
            self.write_json({"error": "没有这本书"}, 404)
            return
        self.write_json(book)


class NoteHandler(BaseHandler):
    """笔记 Markdown 原文。"""

    def get(self, book_id: str) -> None:
        """返回笔记原文。

        Args:
            book_id: 条目 id。

        Returns:
            无。
        """
        note = read_note(book_id)
        if note is None:
            self.write_json({"error": "这本书还没有笔记"}, 404)
            return
        self.write_json({"book_id": book_id, "markdown": note})


class ProgressHandler(BaseHandler):
    """阅读位置。

    位置存在 `data/state/progress.json` —— 与下载状态分开，
    前端编辑书单时不会覆盖。
    """

    def get(self, book_id: str) -> None:
        """返回阅读位置。

        Args:
            book_id: 条目 id。

        Returns:
            无。
        """
        self.write_json({"book_id": book_id,
                         "progress": self._load().get(book_id, 0.0)})

    def post(self, book_id: str) -> None:
        """保存阅读位置。

        Args:
            book_id: 条目 id。

        Returns:
            无。
        """
        body = self.json_body()
        try:
            value = float(body.get("progress", 0))
        except (TypeError, ValueError):
            value = 0.0
        value = max(0.0, min(1.0, value))
        data = self._load()
        data[book_id] = value
        path = ROOT / "data" / "state" / "progress.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        self.write_json({"ok": True, "book_id": book_id, "progress": value})

    @staticmethod
    def _load() -> Dict[str, float]:
        """读全部阅读位置。

        Returns:
            `书名 id → 进度比例` 的字典。
        """
        path = ROOT / "data" / "state" / "progress.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}


class JobsSocketHandler(tornado.websocket.WebSocketHandler):
    """任务进度推送。

    连接后先发一次全量快照，之后只推变化。
    """

    def open(self) -> None:  # noqa: D102 - Tornado 接口
        """建立连接。

        Returns:
            无。
        """
        self._callback = self._send_job
        QUEUE.subscribe(self._callback)
        self._send_snapshot()

    def on_close(self) -> None:  # noqa: D102 - Tornado 接口
        """断开连接。

        Returns:
            无。
        """
        QUEUE.unsubscribe(getattr(self, "_callback", None))

    def check_origin(self, origin: str) -> bool:  # noqa: D102
        """允许同源。

        Args:
            origin: 来源。

        Returns:
            始终为 True。
        """
        return True

    def _send_snapshot(self) -> None:
        """推送全量快照。

        Returns:
            无。
        """
        try:
            self.write_message(json.dumps(
                {"type": "snapshot", "jobs": QUEUE.snapshot()},
                ensure_ascii=False))
        except tornado.websocket.WebSocketClosedError:
            pass

    def _send_job(self, job: Dict[str, Any]) -> None:
        """推送单个任务的变化。

        Args:
            job: 任务字典。

        Returns:
            无。
        """
        try:
            self.write_message(json.dumps({"type": "job", "job": job},
                                          ensure_ascii=False))
        except tornado.websocket.WebSocketClosedError:
            QUEUE.unsubscribe(self._callback)
