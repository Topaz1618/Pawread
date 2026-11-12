"""Handler 基类。

单独成模块是为了避开循环导入 ——
`api.py` 需要 `BaseHandler`，而 `app.py` 需要 `api.py`。
"""

from __future__ import annotations

import json
from typing import Any, Dict

import tornado.web


class BaseHandler(tornado.web.RequestHandler):
    """所有 JSON API Handler 的基类。

    统一处理 JSON 请求体解析与错误响应。
    """

    def write_json(self, data: Any, status: int = 200) -> None:
        """写 JSON 响应。

        Args:
            data: 可序列化对象。
            status: HTTP 状态码。
        """
        self.set_status(status)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.finish(json.dumps(data, ensure_ascii=False))

    def json_body(self) -> Dict[str, Any]:
        """解析请求体里的 JSON。

        Returns:
            解析后的字典；失败时返回空字典。
        """
        if not self.request.body:
            return {}
        try:
            data = json.loads(self.request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}
