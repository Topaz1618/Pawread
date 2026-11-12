"""Pawread 结构化日志。

**职责**：把执行过程写成机器可读的 JSONL，让「为什么这本书没下到」
可追溯。

**设计要点**：

1. **一次运行一个 run_id**，贯穿全链，便于把多本书的日志串起来。
2. **请求级记录**：方法、URL、代理出口、状态码、字节数、耗时。
3. **响应体不丢**：搜索结果、站点元数据落到 `logs/raw/<run_id>/`，
   日志里记路径与 sha256。
4. **敏感字段掩码**：代理密码、API Key 只记前 6 位与 sha256。
5. **空结果也记**：`search_result_count=0` 必须落日志，不允许静默跳过。
6. **降级路径显式记**：走过的回退、重试、降级都要写出来。

**上游**：`pawread/pipeline.py`。
**下游**：`pawread/pipeline.py` 的报告阶段。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

#: 项目根目录。
ROOT = Path(__file__).resolve().parent.parent

#: 日志根目录。
LOG_DIR = ROOT / "logs"

#: 原始响应体目录。
RAW_DIR = LOG_DIR / "raw"

#: 需要掩码的键名。匹配不区分大小写。
SENSITIVE_KEYS = (
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "authorization", "proxy_password", "credential",
)


def mask(value: str) -> str:
    """把敏感值掩码。

    只保留前 6 位与 sha256 摘要 —— 既能人工核对是不是同一个凭据，
    又不会泄露原文。

    Args:
        value: 原始值。

    Returns:
        掩码后的字符串；空值返回空串。
    """
    if not value:
        return ""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{value[:6]}...sha256:{digest}"


def redact(data: Any) -> Any:
    """递归掩码字典里的敏感字段。

    Args:
        data: 任意结构的数据。

    Returns:
        掩码后的副本。
    """
    if isinstance(data, dict):
        out: Dict[str, Any] = {}
        for key, value in data.items():
            if any(mark in str(key).lower() for mark in SENSITIVE_KEYS):
                out[key] = mask(str(value))
            else:
                out[key] = redact(value)
        return out
    if isinstance(data, list):
        return [redact(item) for item in data]
    return data


def new_run_id(prefix: str = "run") -> str:
    """生成运行标识。

    Args:
        prefix: 标识前缀。

    Returns:
        形如 `run_20261112_132530_ab12` 的标识。
    """
    from datetime import datetime
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}_{os.getpid() & 0xffff:04x}"


@dataclass
class RunLogger:
    """一次运行的日志记录器。

    用法：
        logger = RunLogger()
        logger.event("discover", "ok", site="archive.org")
        logger.finish()
    """

    run_id: str = field(default_factory=new_run_id)
    log_dir: Path = field(default_factory=lambda: LOG_DIR)
    extra: Dict[str, Any] = field(default_factory=dict)
    _file: Any = field(default=None, init=False, repr=False)
    _raw_dir: Optional[Path] = field(default=None, init=False, repr=False)
    _seq: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        """准备日志文件与原始响应目录。

        Returns:
            无。
        """
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._raw_dir = self.log_dir / "raw" / self.run_id
        self._raw_dir.mkdir(parents=True, exist_ok=True)
        self._file = open(self.log_dir / f"{self.run_id}.jsonl",
                          "a", encoding="utf-8")

    def _write(self, record: Dict[str, Any]) -> None:
        """写一条日志。

        Args:
            record: 日志记录。

        Returns:
            无。
        """
        self._seq += 1
        record = {"seq": self._seq, "ts": round(time.time(), 3),
                  **record}
        self._file.write(json.dumps(record, ensure_ascii=False,
                                    default=str) + "\n")
        self._file.flush()

    def event(self, stage: str, status: str, **fields: Any) -> Dict[str, Any]:
        """记一条阶段事件。

        Args:
            stage: 阶段名，例如 `discover`、`download`、`read`。
            status: 状态，例如 `ok`、`failed`、`skipped`。
            **fields: 附加字段。

        Returns:
            写入的记录。
        """
        record = {
            "run_id": self.run_id,
            "level": "error" if status == "failed" else "info",
            "stage": stage,
            "status": status,
            **redact(fields),
        }
        self._write(record)
        return record

    def request(self, method: str, url: str, status_code: Optional[int] = None,
                bytes_len: int = 0, elapsed_ms: int = 0,
                proxy_exit: str = "", attempt: int = 1,
                **fields: Any) -> Dict[str, Any]:
        """记一次 HTTP 请求。

        Args:
            method: HTTP 方法。
            url: 请求地址。
            status_code: 状态码。
            bytes_len: 响应字节数。
            elapsed_ms: 耗时毫秒。
            proxy_exit: 代理出口标识（session ID）。
            attempt: 第几次尝试。
            **fields: 附加字段。

        Returns:
            写入的记录。
        """
        return self.event(
            "request", "ok" if status_code == 200 else "failed",
            method=method, url=url, status_code=status_code,
            bytes=bytes_len, elapsed_ms=elapsed_ms,
            proxy_exit=proxy_exit, attempt=attempt, **fields)

    def save_raw(self, name: str, payload: Any) -> Dict[str, Any]:
        """保存原始响应体。

        Args:
            name: 文件名（不含扩展名）。
            payload: 要保存的内容，JSON 可序列化则存 JSON，否则存文本。

        Returns:
            含路径与 sha256 的记录。
        """
        assert self._raw_dir is not None
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:120]
        if isinstance(payload, (dict, list)):
            path = self._raw_dir / f"{safe}.json"
            body = json.dumps(payload, ensure_ascii=False, indent=2,
                             default=str)
        else:
            path = self._raw_dir / f"{safe}.txt"
            body = str(payload)
        path.write_text(body, encoding="utf-8")
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        self.event("raw", "ok", name=safe, path=str(path),
                   bytes=len(body.encode("utf-8")), sha256=digest)
        return {"path": str(path), "sha256": digest,
                "bytes": len(body.encode("utf-8"))}

    def finish(self, summary: Optional[Dict[str, Any]] = None) -> None:
        """结束本次运行并写入汇总。

        Args:
            summary: 汇总数据。

        Returns:
            无。
        """
        if summary is not None:
            self.event("summary", "ok", **summary)
        self._write({"run_id": self.run_id, "level": "info",
                     "stage": "run", "status": "finished"})
        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self) -> "RunLogger":
        """进入上下文。

        Returns:
            自身。
        """
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """退出上下文，异常时也要收尾。

        Args:
            exc_type: 异常类型。
            exc: 异常实例。
            tb: 回溯。

        Returns:
            无。
        """
        if exc_type is not None:
            self.event("run", "failed", error=f"{exc_type.__name__}: {exc}")
        self.finish()


def read_run(run_id: str, log_dir: Path = LOG_DIR) -> List[Dict[str, Any]]:
    """读取一次运行的日志。

    Args:
        run_id: 运行标识。
        log_dir: 日志目录。

    Returns:
        日志记录列表；文件不存在时返回空列表。
    """
    path = log_dir / f"{run_id}.jsonl"
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records
