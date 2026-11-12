"""页面 Handler。

三个页面共用同一套外壳（顶栏 + 内容区），只有主体不同。
模板在 `templates_pawread/`。
"""

from __future__ import annotations

from typing import Any, Dict

import tornado.web

from .state import find_book, list_books, read_note


class PageHandler(tornado.web.RequestHandler):
    """页面基类。

    提供外壳数据与通用渲染。
    """

    #: 页面标识，前端据此高亮导航。
    page = ""

    def get_template_name(self) -> str:
        """返回模板名。

        Returns:
            模板文件名。
        """
        return f"{self.page}.html"

    def shell_data(self) -> Dict[str, Any]:
        """外壳数据。

        Returns:
            所有页面共有的上下文。
        """
        return {
            "page": self.page,
            "nav": [
                {"key": "ingest", "label": "操作", "href": "/",
                 "i18n": "nav.ingest"},
                {"key": "library", "label": "书单", "href": "/library",
                 "i18n": "nav.library"},
                {"key": "reader", "label": "阅读", "href": "/library",
                 "i18n": "nav.reader"},
            ],
        }


class IngestHandler(PageHandler):
    """操作页。

    上半部分是一个 textarea 提交书名，下半部分显示队列。
    """

    page = "ingest"

    def get(self) -> None:
        """渲染页面。

        Returns:
            无。
        """
        self.render(self.get_template_name(), **self.shell_data())


class LibraryHandler(PageHandler):
    """书单页。

    列出全部书，按优先级与状态过滤。
    """

    page = "library"

    def get(self) -> None:
        """渲染页面。

        Returns:
            无。
        """
        self.render(self.get_template_name(), **self.shell_data())


class ReaderHandler(PageHandler):
    """阅读页。

    左侧是书名列表，右侧是渲染后的 Markdown。
    """

    page = "reader"

    def get(self, book_id: str) -> None:
        """渲染页面。

        Args:
            book_id: 条目 id。

        Returns:
            无。
        """
        book = find_book(book_id)
        if book is None:
            self.set_status(404)
            self.render(self.get_template_name(), **self.shell_data(),
                        book=None, book_id=book_id)
            return
        note = read_note(book_id) or ""
        data = self.shell_data()
        # 阅读页顶栏的「阅读」项指向当前这本书
        for item in data["nav"]:
            if item["key"] == "reader":
                item["href"] = f"/read/{book_id}"
        self.render(self.get_template_name(), **data,
                    book=book, book_id=book_id, note=note)


class NotFoundHandler(tornado.web.RequestHandler):
    """404 兜底。

    API 请求返回 JSON，页面请求返回 HTML。
    """

    def prepare(self) -> None:
        """设置响应类型。

        Returns:
            无。
        """
        self.set_header("Content-Type", "application/json; charset=UTF-8")

    def get(self) -> None:
        """返回 404。

        Returns:
            无。
        """
        self.set_status(404)
        self.finish('{"error": "not found"}')

    def post(self) -> None:
        """返回 404。

        Returns:
            无。
        """
        self.get()
