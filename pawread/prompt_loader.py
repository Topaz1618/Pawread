"""Pawread 提示词版本管理。

**职责**：从 `pawread/prompts/<节点>/<版本>.txt` 加载提示词文本，
并做缓存。

**为什么单独成文件**：提示词是内容，不是代码逻辑。放在独立文件里
才能做版本化（A/B 对比、回滚），也避免把大段中英文提示词埋在
Python 代码中。

**目录结构**：
    10|pawread/prompts/
      reader/v1.txt     读书笔记（分块笔记）
      normalize/v1.txt  书名规范化
      sources/v1.txt    站点检索建议
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

#: 提示词根目录。
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


class PromptLoader:
    """提示词加载器。

    用法：
        loader = PromptLoader()
        text = loader.load("reader", "v1")
    """

    def __init__(self, prompts_dir: Optional[Path] = None) -> None:
        """初始化加载器。

        Args:
            prompts_dir: 提示词根目录。缺省用模块同级的 `prompts/`。
        """
        self.prompts_dir = prompts_dir or PROMPTS_DIR
        self._cache: Dict[str, str] = {}

    def load(self, node: str, version: str = "v1") -> str:
        """加载指定节点的提示词。

        Args:
            node: 节点名，例如 `reader`。
            version: 版本号，例如 `v1`。

        Returns:
            提示词文本。

        Raises:
            FileNotFoundError: 提示词文件不存在时抛出。
        """
        key = f"{node}:{version}"
        if key in self._cache:
            return self._cache[key]
        path = self.prompts_dir / node / f"{version}.txt"
        if not path.exists():
            raise FileNotFoundError(f"提示词文件不存在：{path}")
        text = path.read_text(encoding="utf-8")
        self._cache[key] = text
        return text

    def render(self, node: str, version: str = "v1", **kwargs: object) -> str:
        """加载提示词并填充占位符。

        Args:
            node: 节点名。
            version: 版本号。
            **kwargs: 占位符键值对。占位符形如 `{title}`。

        Returns:
            填充后的提示词文本。

        Raises:
            KeyError: 提示词里有未被填充的占位符时抛出。
        """
        return self.load(node, version).format(**kwargs)


_global_loader: Optional[PromptLoader] = None


def get_prompt_loader() -> PromptLoader:
    """取全局提示词加载器。

    Returns:
        加载器单例。
    """
    global _global_loader
    if _global_loader is None:
        _global_loader = PromptLoader()
    return _global_loader
