#!/usr/bin/env python3
"""以守护进程方式启动 Pawread Web 服务。

macOS 没有 `setsid`，`nohup ... &` 在父 shell 退出时仍会被回收，
所以这里自己 fork 两次，脱离终端会话。

```bash
python3 tools/serve.py            # 启动（已在运行时则退出）
python3 tools/serve.py --stop     # 停止
python3 tools/serve.py --status   # 查看状态
```

绑定地址与端口缺省读环境变量 `PAWREAD_HOST` / `PAWREAD_PORT`
（见 `config/env.example`），命令行参数优先。

日志写到 `logs/server.log`。
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pawread.env import get_int, get_str, load_env  # noqa: E402

LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "server.log"
PID_FILE = LOG_DIR / "server.pid"

DEFAULT_PORT = 8026
DEFAULT_HOST = "127.0.0.1"


def read_pid() -> int:
    """读 PID 文件。

    Returns:
        进程号；文件不存在或内容无效时返回 0。
    """
    if not PID_FILE.exists():
        return 0
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def is_alive(pid: int) -> bool:
    """进程是否还活着。

    Args:
        pid: 进程号。

    Returns:
        存活返回 True。
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop() -> None:
    """停止服务。"""
    pid = read_pid()
    if not is_alive(pid):
        print("服务未在运行")
        if PID_FILE.exists():
            PID_FILE.unlink()
        return
    os.kill(pid, signal.SIGTERM)
    for _ in range(30):
        if not is_alive(pid):
            break
        time.sleep(0.1)
    if is_alive(pid):
        os.kill(pid, signal.SIGKILL)
    if PID_FILE.exists():
        PID_FILE.unlink()
    print(f"已停止（pid {pid}）")


def status() -> None:
    """打印服务状态。"""
    pid = read_pid()
    if is_alive(pid):
        print(f"运行中（pid {pid}）")
    else:
        print("未运行")


def start(port: int, host: str) -> None:
    """以守护进程方式启动。

    Args:
        port: 端口。
        host: 绑定地址。
    """
    pid = read_pid()
    if is_alive(pid):
        print(f"服务已在运行（pid {pid}）")
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # 文本模式 —— 二进制模式会让 sys.stdout 变成二进制流，
    # 应用里的 print(str) 会抛 TypeError，服务在启动横幅那行就死掉。
    log = open(LOG_FILE, "ab", buffering=0)
    text_log = open(LOG_FILE, "a", encoding="utf-8", buffering=1)

    # 清掉陈旧的 PID 文件 —— 否则下面会误读上一轮的 PID 当成启动成功
    if PID_FILE.exists():
        PID_FILE.unlink()

    # 第一次 fork —— 父进程退出，子进程继续
    if os.fork() > 0:
        os.wait()
        # 等待孙进程写 PID 文件
        for _ in range(50):
            new_pid = read_pid()
            if new_pid:
                print(f"已启动（pid {new_pid}）  http://{host}:{port}")
                return
            time.sleep(0.1)
        print("启动超时，见 logs/server.log")
        return

    # 子进程：脱离会话
    os.setsid()
    if os.fork() > 0:
        os._exit(0)

    # 孙进程：真正干活
    os.chdir(str(ROOT))
    os.umask(0o022)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

    # stdout/stderr 用文本模式 —— 应用里全是 print(str)
    sys.stdout = text_log
    sys.stderr = text_log
    sys.stdin = open(os.devnull)

    sys.path.insert(0, str(ROOT))
    try:
        from pawread.web.app import run
        run(port=port, address=host)
    except BaseException:
        import traceback
        traceback.print_exc(file=text_log)
        text_log.flush()
        os._exit(1)


def main() -> None:
    """解析参数并执行。"""
    ap = argparse.ArgumentParser(description="Pawread Web 守护进程")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--host", default=None)
    ap.add_argument("--stop", action="store_true", help="停止服务")
    ap.add_argument("--status", action="store_true", help="查看状态")
    args = ap.parse_args()

    load_env()
    host = args.host or get_str("PAWREAD_HOST", DEFAULT_HOST)
    port = args.port or get_int("PAWREAD_PORT", DEFAULT_PORT)

    if args.stop:
        stop()
    elif args.status:
        status()
    else:
        start(port, host)


if __name__ == "__main__":
    main()