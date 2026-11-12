"""环境变量加载。

**职责**：从 `config/` 下的 env 文件补齐缺失的环境变量。

**为什么单独成模块**：`pawread.llm` 与 `pawread.fetcher` 都需要读
`config/env.local`，`server.py` 也需要读端口配置。三处各写一遍
解析逻辑迟早会漂。

**规则**：只在变量缺失时写入，**不覆盖**已有的环境变量。
进程环境里的值优先级最高 —— 这样容器部署时用环境变量注入，
本地开发时用 `config/env.local`，两者可以共存。

**上游**：`pawread/llm.py`、`pawread/fetcher.py`、`server.py`。
**下游**：`os.environ`。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, Optional

#: 项目根目录。
ROOT = Path(__file__).resolve().parent.parent

#: 依次尝试的 env 文件。前面的优先。
ENV_FILES = ("env.local", "env_local", "env.prod", "env")


def env_path(name: str) -> Path:
    """取 env 文件路径。

    Args:
        name: 文件名，如 `env.local`。

    Returns:
        `config/` 下的路径。
    """
    return ROOT / "config" / name


def parse_env_text(text: str) -> List[tuple]:
    """解析 dotenv 风格的文本。

    Args:
        text: 文件内容。

    Returns:
        `[(键, 值), ...]`；空行与注释行被跳过。
    """
    pairs: List[tuple] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key:
            pairs.append((key, val.strip().strip("'\"")))
    return pairs


def load_env(names: Optional[Iterable[str]] = None,
             files: Optional[Iterable[str]] = None,
             prefixes: Optional[Iterable[str]] = None) -> None:
    """从 env 文件补齐缺失的环境变量。

    Args:
        names: 只加载这些键。`None` 表示不限。
        files: 依次尝试的 env 文件名。缺省用 `ENV_FILES`。
        prefixes: 只加载以这些前缀开头的键。`None` 表示不限。

    Returns:
        无。
    """
    wanted = set(names) if names is not None else None
    pref = tuple(prefixes) if prefixes else None
    for name in (files or ENV_FILES):
        path = env_path(name)
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for key, val in parse_env_text(text):
            if wanted is not None and key not in wanted:
                continue
            if pref is not None and not key.startswith(pref):
                continue
            if not key:
                continue
            # 空值视为未设置 —— 模板文件里留空的项不该把代码里的缺省值覆盖掉。
            if not val:
                continue
            if not os.environ.get(key):
                os.environ[key] = val
        break


def get_int(name: str, default: int) -> int:
    """取一个整数型环境变量。

    Args:
        name: 变量名。
        default: 缺省值。

    Returns:
        整数值；变量缺失或不是合法整数时返回 `default`。
    """
    raw = os.environ.get(name, "")
    try:
        return int(raw.strip())
    except (AttributeError, ValueError):
        return default


def get_str(name: str, default: str = "") -> str:
    """取一个字符串型环境变量。

    Args:
        name: 变量名。
        default: 缺省值。

    Returns:
        变量值；缺失时返回 `default`。
    """
    return os.environ.get(name, "").strip() or default
