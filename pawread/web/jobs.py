"""下载与读书的任务队列。

**为什么需要队列**：抓取要走住宅代理，一次只能开有限的并发；
读书要调 LLM，token 消耗大。串行处理最稳，也不会把代理打挂。

**状态机**（每本书独立推进）：

```
pending → searching → downloading → verifying → noting → noted
                     ↘                  ↘           ↘
                        unavailable ←────┴───────────┘
```

**实时推送**：状态变化通过 `on_change` 回调广播给 WebSocket 连接。
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..booklists import slugify
from .state import (ROOT, load_state, note_path, save_state,
                    ensure_book_entry)

#: 书籍文件目录。
BOOKS_DIR = ROOT / "books"

#: 笔记目录。
NOTES_DIR = ROOT / "notes"

#: 单次提交的最大书数。
MAX_BATCH = 100


class Job:
    """一本书的处理任务。

    字段:
        book_id: 条目 id。
        title: 原书名。
        author: 作者。
        state: 当前状态。
        detail: 状态说明（失败原因等）。
        progress: 进度百分比 0-100。
        reasons: 失败理由列表。
        error: 异常信息。
    """

    def __init__(self, book_id: str, title: str, author: str = "") -> None:
        self.book_id = book_id
        self.title = title
        self.author = author
        self.state = "pending"
        self.detail = ""
        self.progress = 0
        self.reasons: List[Dict[str, Any]] = []
        self.error = ""
        self.source = ""
        self.source_url = ""
        self.license = ""
        self.file: Optional[str] = None
        self.bytes = 0
        self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转为可 JSON 序列化的字典。

        Returns:
            任务字典。
        """
        return {
            "book_id": self.book_id,
            "title": self.title,
            "author": self.author,
            "state": self.state,
            "detail": self.detail,
            "progress": self.progress,
            "reasons": self.reasons,
            "error": self.error,
            "source": self.source,
            "source_url": self.source_url,
            "license": self.license,
            "bytes": self.bytes,
            "created_at": self.created_at,
        }


class JobQueue:
    """串行任务队列。

    一个 worker 依次处理队列里的书，每本书推进到终态。
    状态变化通过回调广播，前端用 WebSocket 接收。
    """

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._order: List[str] = []
        self._queue: "asyncio.Queue[str]" = asyncio.Queue()
        self._lock = threading.RLock()
        self._listeners: List[Callable[[Dict[str, Any]], None]] = []
        self._worker: Optional[asyncio.Task] = None

    # ---------------------------------------------------------------- 订阅

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """订阅状态变化。

        Args:
            callback: 收到任务字典的回调。
        """
        with self._lock:
            self._listeners.append(callback)

    def unsubscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """取消订阅。

        Args:
            callback: 之前注册的回调。
        """
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _broadcast(self, job: Job) -> None:
        """广播任务状态变化。

        Args:
            job: 变化的任务。
        """
        payload = job.to_dict()
        with self._lock:
            listeners = list(self._listeners)
        for callback in listeners:
            try:
                callback(payload)
            except Exception:  # noqa: BLE001 - 单个订阅者出错不影响别人
                pass

    # ---------------------------------------------------------------- 查询

    def snapshot(self) -> List[Dict[str, Any]]:
        """取全部任务的快照。

        Returns:
            任务字典列表，按提交顺序。
        """
        with self._lock:
            return [self._jobs[jid].to_dict() for jid in self._order
                    if jid in self._jobs]

    def get(self, book_id: str) -> Optional[Job]:
        """按 id 取任务。

        Args:
            book_id: 条目 id。

        Returns:
            任务；不存在时返回 None。
        """
        with self._lock:
            return self._jobs.get(book_id)

    # ---------------------------------------------------------------- 提交

    def submit(self, titles: List[str],
               authors: Optional[List[str]] = None) -> List[Job]:
        """提交一批书名。

        Args:
            titles: 书名列表。
            authors: 与书名一一对应的作者，可缺省。

        Returns:
            创建的任务列表。超过上限时只取前 `MAX_BATCH` 个。
        """
        created: List[Job] = []
        for i, title in enumerate(titles[:MAX_BATCH]):
            title = title.strip()
            if not title:
                continue
            author = authors[i] if authors and i < len(authors) else ""
            book_id = slugify(title)
            ensure_book_entry(title, author=author)
            with self._lock:
                if book_id in self._jobs:
                    job = self._jobs[book_id]
                else:
                    job = Job(book_id, title, author)
                    self._jobs[book_id] = job
                    self._order.append(book_id)
            created.append(job)
            self._queue.put_nowait(book_id)
        return created

    def start(self) -> None:
        """启动 worker。"""
        if self._worker is None or self._worker.done():
            self._worker = asyncio.get_event_loop().create_task(self._run())

    async def _run(self) -> None:
        """worker 主循环。"""
        while True:
            book_id = await self._queue.get()
            job = self.get(book_id)
            if job is not None and job.state == "pending":
                await self._process(job)
            self._queue.task_done()

    # ---------------------------------------------------------------- 执行

    def _set_state(self, job: Job, state: str, progress: int = 0,
                   detail: str = "") -> None:
        """更新任务状态并广播。

        Args:
            job: 任务。
            state: 新状态。
            progress: 进度百分比。
            detail: 状态说明。
        """
        job.state = state
        job.progress = progress
        if detail:
            job.detail = detail
        self._persist(job)
        self._broadcast(job)

    def _persist(self, job: Job) -> None:
        """把任务状态写进状态文件。

        Args:
            job: 任务。
        """
        doc = load_state()
        books = doc.setdefault("books", {})
        entry = books.get(job.book_id) or {}
        entry.update({
            "state": job.state,
            "detail": job.detail,
            "progress": job.progress,
            "reasons": job.reasons,
            "source": job.source,
            "source_url": job.source_url,
            "license": job.license,
        })
        if job.file:
            entry["file"] = {"path": job.file, "bytes": job.bytes}
        books[job.book_id] = entry
        save_state(doc)

    async def _process(self, job: Job) -> None:
        """处理一本书：检索 → 下载 → 校验 → 读书。

        阻塞的 IO 放到线程池里跑，不阻塞事件循环 ——
        否则 WebSocket 推送会被下载卡住。

        Args:
            job: 任务。
        """
        loop = asyncio.get_event_loop()
        try:
            self._set_state(job, "searching", 10, "正在检索资源")
            await loop.run_in_executor(None, self._discover_and_download, job)

            if job.state == "unavailable":
                return

            self._set_state(job, "verifying", 60, "正在校验内容")
            await loop.run_in_executor(None, self._verify, job)
            if job.state == "failed":
                return

            self._set_state(job, "noting", 70, "正在生成笔记")
            await loop.run_in_executor(None, self._read, job)
        except Exception as exc:  # noqa: BLE001 - 单本失败不阻断队列
            job.error = f"{type(exc).__name__}: {exc}"
            job.reasons.append({"site": "-", "reason": "internal_error",
                                 "detail": job.error})
            self._set_state(job, "failed", 0, job.error)

    def _discover_and_download(self, job: Job) -> None:
        """检索并下载。

        Args:
            job: 任务。
        """
        from ..discover import discover
        from ..fetcher import download, make_session
        from ..pipeline import download_candidate, find_existing_file

        session = make_session()
        existing = find_existing_file(job.title)
        if existing:
            job.file = str(existing)
            job.source = "本地已有"
            job.bytes = existing.stat().st_size
            self._set_state(job, "verifying", 60)
            return

        found = discover(session, job.title, job.author, "")
        job.reasons = (found.get("failures", [])
                        + found.get("empty_sites", []))
        candidates = found.get("candidates", [])
        if not candidates:
            job.detail = "未找到可下载的完整文件"
            self._set_state(job, "unavailable", 0, job.detail)
            return

        from ..logging_setup import RunLogger
        logger = RunLogger()
        for cand in candidates[:3]:
            got = download_candidate(session, cand, job.title, job.author,
                                     BOOKS_DIR, logger)
            if got:
                job.file = got.get("path")
                job.source = got.get("source", "")
                job.source_url = got.get("source_url", "")
                job.bytes = int(got.get("bytes", 0) or 0)
                self._set_state(job, "verifying", 60)
                return
            job.reasons.append({
                "site": cand.get("site"),
                "reason": "verify_failed",
                "detail": f"候选「{(cand.get('title') or '')[:40]}」下载或校验失败",
            })
        job.detail = "所有候选都下载或校验失败"
        self._set_state(job, "unavailable", 0, job.detail)

    def _verify(self, job: Job) -> None:
        """校验已下载的文件。

        Args:
            job: 任务。
        """
        from ..fetcher import verify_file
        if not job.file:
            job.detail = "没有文件可校验"
            self._set_state(job, "failed", 0, job.detail)
            return
        path = Path(job.file)
        result = verify_file(path, {"title": job.title,
                                    "author": job.author})
        status = result.get("status", "")
        if status not in ("ok", "correct", "match"):
            job.detail = result.get("detail", "内容校验不通过")
            job.reasons.append({"site": job.source or "-",
                                 "reason": "verify_failed",
                                 "detail": job.detail})
            self._set_state(job, "failed", 0, job.detail)
            return
        job.license = result.get("license", "")
        self._set_state(job, "noting", 70)

    def _read(self, job: Job) -> None:
        """生成笔记。

        Args:
            job: 任务。
        """
        from ..extract import build_chunks
        from ..llm import LLMClient
        from ..reader import BookNotes, read_chunks

        if not job.file:
            self._set_state(job, "failed", 0, "没有文件可读书")
            return

        chunks = build_chunks(Path(job.file))
        client = LLMClient(tier="test")
        notes = read_chunks(client, job.title, chunks)
        written = [n for n in notes if not n.skipped and n.note]
        if not written:
            job.detail = "没有产出任何笔记"
            self._set_state(job, "failed", 0, job.detail)
            return

        book_notes = BookNotes(
            title=job.title, chunks=notes,
            stats={
                "skipped": sum(1 for n in notes if n.skipped),
                "total_tokens": client.summary()["pool"]["total_tokens"],
            })
        NOTES_DIR.mkdir(parents=True, exist_ok=True)
        out = NOTES_DIR / f"{job.book_id}.md"
        out.write_text(book_notes.render_markdown(job.file),
                       encoding="utf-8")
        self._set_state(job, "noted", 100, "已完成")


#: 全局队列实例。
QUEUE = JobQueue()
