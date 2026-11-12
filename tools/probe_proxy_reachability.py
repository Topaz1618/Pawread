#!/usr/bin/env python3
"""探测海外免费资源站在 SmartProxy 住宅代理下的可达性。

背景：Pawread 要从海外免费资源站抓取电子书。初测发现 annas-archive、
libgen、manybooks、gutenberg.org 经 SmartProxy 全部 `ProxyError`，
而直连正常。SmartProxy 的 session ID 决定出口 IP，
换 session 即可换出口，因此需要实测「换 session 重试」能否绕过。

用法：

```bash
python3 tools/probe_proxy_reachability.py
python3 tools/probe_proxy_reachability.py --rotations 3 --timeout 30
```

输出为 JSON 数组，每条记录一次真实请求的结果，字段含义：

| 字段 | 含义 |
|---|---|
| `site` | 被测站点标识 |
| `url` | 实际请求的 URL |
| `rotation` | 第几次重建代理会话（0 起） |
| `status` | `ok` / `http_error` / `proxy_error` / `timeout` / `error` |
| `http_status` | HTTP 状态码，非 200 时有意义 |
| `elapsed_ms` | 耗时毫秒 |
| `bytes` | 响应体字节数 |
| `error` | 异常类型与消息，失败时给出 |
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pawread.fetcher import make_session  # noqa: E402

#: 被测站点。列表以「确定性爬虫实际会用的站」为准。
PROBE_TARGETS: List[Dict[str, str]] = [
    {"site": "archive.org", "url": "https://archive.org/advancedsearch.php?q=mediatype:texts&rows=1&output=json"},
    {"site": "openlibrary.org", "url": "https://openlibrary.org/search.json?q=Atomic+Habits&limit=1"},
    {"site": "gutendex.com", "url": "https://gutendex.com/books?search=Art+of+War"},
    {"site": "gutenberg.org", "url": "https://www.gutenberg.org/ebooks/search/?query=Art+of+War"},
    {"site": "standardebooks.org", "url": "https://standardebooks.org/ebooks"},
    {"site": "manybooks.net", "url": "https://manybooks.net/search?q=Atomic+Habits"},
    {"site": "annas-archive.org", "url": "https://annas-archive.org/search?q=Atomic+Habits"},
    {"site": "libgen.is", "url": "https://libgen.is/fiction/?q=Atomic+Habits"},
    {"site": "books.google.com", "url": "https://books.google.com/books?q=Atomic+Habits"},
    {"site": "books.googleusercontent.com", "url": "https://books.google.com/books/content?id=test&printsec=frontcover"},
]

#: 请求头。与 fetch_pawread_books.UA 一致。
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/131.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}


def probe_once(url: str, timeout: int) -> Dict[str, Any]:
    """发起一次探测请求。

    每次调用都重建会话，因此每次都是不同的 SmartProxy 出口 IP。

    Args:
        url: 目标地址。
        timeout: 单次请求超时秒数。

    Returns:
        探测结果字典。字段见模块文档。
    """
    record: Dict[str, Any] = {
        "url": url,
        "status": "ok",
        "http_status": None,
        "elapsed_ms": 0,
        "bytes": 0,
        "error": None,
    }
    started = time.monotonic()
    try:
        session = make_session()
        resp = session.get(url, timeout=timeout, headers=HEADERS)
        record["http_status"] = resp.status_code
        record["bytes"] = len(resp.content)
        if resp.status_code != 200:
            record["status"] = "http_error"
    except Exception as exc:  # noqa: BLE001 - 探测需记录任意失败
        name = type(exc).__name__
        message = str(exc)
        if "ProxyError" in name:
            record["status"] = "proxy_error"
        elif "Timeout" in name:
            record["status"] = "timeout"
        else:
            record["status"] = "error"
        record["error"] = f"{name}: {message[:160]}"
    record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return record


def main() -> None:
    """按站点 × 轮次执行探测，打印 JSON 结果。"""
    parser = argparse.ArgumentParser(description="探测海外免费资源站的代理可达性")
    parser.add_argument("--rotations", type=int, default=3,
                        help="每个站点重建几次代理会话（默认 3）")
    parser.add_argument("--timeout", type=int, default=30,
                        help="单次请求超时秒数（默认 30）")
    parser.add_argument("--out", type=str, default="",
                        help="结果 JSON 的写出路径，缺省只打印")
    args = parser.parse_args()

    results: List[Dict[str, Any]] = []
    for target in PROBE_TARGETS:
        for rotation in range(args.rotations):
            record = probe_once(target["url"], args.timeout)
            record["site"] = target["site"]
            record["rotation"] = rotation
            results.append(record)
            print(f"{target['site']:26} rot={rotation} "
                  f"status={record['status']:12} "
                  f"http={record['http_status']} "
                  f"{record['elapsed_ms']:>6}ms "
                  f"{record['bytes']:>8}B "
                  f"{record['error'] or ''}", flush=True)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"\nwritten: {out}")

    summary: Dict[str, Dict[str, int]] = {}
    for record in results:
        bucket = summary.setdefault(record["site"], {})
        bucket[record["status"]] = bucket.get(record["status"], 0) + 1
    print("\n=== 汇总 ===")
    for site, bucket in summary.items():
        total = sum(bucket.values())
        ok = bucket.get("ok", 0)
        print(f"{site:26} ok {ok}/{total}  {bucket}")


if __name__ == "__main__":
    main()
