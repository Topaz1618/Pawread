"""书单数据的读写。

**为什么要单独的模块**：书单是「配置」，运行状态是「产物」，
两者写在不同文件里（见 `data/booklists/` 与 `data/state/`）。
混在一起会因为读写冲突丢数据 —— 前端保存书单可能覆盖掉
流水线刚写下的下载结果。

**书单结构**（见 `data/booklists/_template.json`）：

```json
{
  "version": 1,
  "languages": { "cn": { "name": "简体中文", "script": "han" } },
  "lists": [{
    "id": "personal",
    "default_lang": "cn",
    "priority_levels": [{ "value": 0, "label": "P0" }],
    "books": [{
      "id": "thinking-in-systems",
      "title": { "text": "Thinking in Systems", "lang": "en", "script": "latin" },
      "priority": 0,
      "translations": { "cn": "系统之美" },
      "chapters": [{ "title": "A Portrait of Charles T. Munger", "translations": { "cn": "芒格传略" } }]
    }]
  }]
}
```

**章节名的三级来源**（方案 C）：
1. 配置里的 `chapters` —— 准确，来自权威目录
2. 独立的标题调用（`prompts/reader/title-v1.txt`）——
   **必须独立成一次调用**，不能混进生成提示词。
   实测 v4 把「附上章节标题」加进生成提示词后，模型切到
   「按格式交作业」的短模式，小节标题从 7 个掉到 0 个
3. 切分时的运行头 —— 最不可靠，可能是正文句子
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

#: 书单目录。
BOOKLISTS_DIR = Path(__file__).resolve().parent.parent / "data" / "booklists"


def slugify(text: str) -> str:
    """把书名转成 slug。

    撇号要**去掉**而不是换成连字符 —— 否则
    `Poor Charlie's Almanack` 会变成 `poor-charlie-s-almanack`，
    那个 `s` 是多余的。

    Args:
        text: 原始书名。

    Returns:
        小写连字符连接的 slug。
    """
    s = text.lower()
    # 撇号与首字母缩写点：去掉，但保留单词间的空格
    s = re.sub(r"[''`]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def load_booklist_doc(path: str | Path) -> Dict[str, Any]:
    """读取一份书单文件。

    Args:
        path: 文件路径。

    Returns:
        解析后的字典；文件不存在或格式错误时返回空字典。
    """
    file = Path(path)
    if not file.exists():
        return {}
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def list_books(doc: Dict[str, Any],
               list_id: str = "personal") -> List[Dict[str, Any]]:
    """从书单文档里取出某一份书单的条目。

    Args:
        doc: 书单文档。
        list_id: 书单 id。

    Returns:
        条目列表；找不到该书单时返回空列表。
    """
    for entry in doc.get("lists", []):
        if entry.get("id") == list_id:
            return entry.get("books", [])
    return []


def load_books(path: str | Path,
               list_id: str = "personal") -> List[Dict[str, Any]]:
    """读取书单文件里的条目。

    Args:
        path: 书单文件路径。
        list_id: 书单 id。

    Returns:
        条目列表。
    """
    return list_books(load_booklist_doc(path), list_id)


def display_title(entry: Dict[str, Any], lang: str = "cn") -> str:
    """取条目在指定语言下的显示名。

    查不到该语言的译名时退回原名。

    Args:
        entry: 书单条目。
        lang: 目标语言代码。

    Returns:
        显示用的书名。
    """
    translations = entry.get("translations") or {}
    if lang in translations:
        return translations[lang]
    title = entry.get("title") or {}
    return title.get("text", "") if isinstance(title, dict) else str(title)


def chapter_titles_for(entry: Dict[str, Any],
                       lang: str = "cn") -> List[Tuple[str, str]]:
    """取条目配置的章节表。

    Args:
        entry: 书单条目。
        lang: 译名语言。

    Returns:
        `[(原名, 译名), ...]`；没有配置时返回空列表。
    """
    out: List[Tuple[str, str]] = []
    for ch in entry.get("chapters") or []:
        name = ch.get("title", "")
        zh = (ch.get("translations") or {}).get(lang, "")
        out.append((name, zh))
    return out


def find_by_id(doc: Dict[str, Any],
               book_id: str,
               list_id: str = "personal") -> Optional[Dict[str, Any]]:
    """按 id 找书单条目。

    Args:
        doc: 书单文档。
        book_id: 条目 id。
        list_id: 书单 id。

    Returns:
        条目；找不到时返回 None。
    """
    for entry in list_books(doc, list_id):
        if entry.get("id") == book_id:
            return entry
    return None
