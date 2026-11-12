#!/usr/bin/env python3
"""Pawread 笔记后处理的自检。

**为什么需要这个**：笔记后处理（去开场白、去自我交代、去清单）本质上是
**删除文本**。删错了就是丢内容 —— 而「不丢内容」是这个工具的第一要求。

实测踩过的坑：清理「本笔记严格遵守要求」的正则，所有分组都写成可选的，
结果能匹配空串，把整篇笔记从第一行删到文末。笔记从 1317 行变成 137 行。

所以每条过滤规则都必须有一条「不该被删」的对照用例。

**用法**：`python3 tools/check_notes.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pawread.reader import (  # noqa: E402
    _preview,
    demote_headings,
    is_chinese_heavy,
    strip_preamble,
)

#: 每条用例：(用例名, 输入, 必须保留的片段列表, 必须删掉的片段列表)
CASES = [
    (
        "开场白被剥掉，正文保留",
        "以下是按照要求生成的详细笔记。\n\n"
        "### 一、定义\n"
        "系统是由相互连接的要素构成的整体。\n",
        ["### 一、定义", "系统是由相互连接的要素构成的整体"],
        ["以下是按照要求生成的详细笔记"],
    ),
    (
        "结尾自我交代被剥掉",
        "### 一、定义\n"
        "系统是整体。\n\n"
        "（笔记至此结束，内容完整、未压缩、未删减、未修改原意。）\n",
        ["### 一、定义", "系统是整体"],
        ["笔记至此结束"],
    ),
    (
        "下一章预告被整段删掉",
        "### 一、定义\n"
        "系统是整体。\n\n"
        "---\n"
        "📌 **下一章预告：**\n"
        "第二章将探讨存量与流量。\n",
        ["### 一、定义", "系统是整体"],
        ["下一章预告", "第二章将探讨"],
    ),
    (
        "自我检查清单被删掉",
        "### 一、定义\n"
        "系统是整体。\n\n"
        "✅ **本笔记严格遵守要求：**\n"
        "- 未压缩信息；\n"
        "- 未偷懒；\n",
        ["### 一、定义", "系统是整体"],
        ["本笔记严格遵守要求", "未偷懒"],
    ),
    (
        "长句式自我检查被删掉",
        "### 一、定义\n"
        "系统是整体。\n\n"
        "✅ **本章笔记完整无删减，内容忠实原文，未压缩、未省略、"
        "未修改原意，严格遵循简体中文输出要求。**\n",
        ["### 一、定义", "系统是整体"],
        ["本章笔记完整无删减"],
    ),
    (
        "正常正文里的「要求」字样不被误删",
        "### 一、需求\n"
        "系统必须满足三个要求：元素、连接、目的。\n",
        ["系统必须满足三个要求"],
        [],
    ),
    (
        "正文里的「笔记」字样不被误删",
        "### 一、说明\n"
        "这份笔记记录了作者对系统的全部论述。\n",
        ["这份笔记记录了作者对系统的全部论述"],
        [],
    ),
    (
        "正文里的「作者在本章要求读者…」不被误删",
        "### 一、说明\n"
        "作者在本章要求读者注意反馈延迟。\n",
        ["作者在本章要求读者注意反馈延迟"],
        [],
    ),
]

#: preview 用例：(用例名, 笔记, 期望包含的片段)
PREVIEW_CASES = [
    (
        "优先取最靠前的原文引用",
        "> “管理者管理的是混乱。”\n"
        "> ——拉塞尔·阿科夫\n"
        "\n"
        "> “后面的引用更长更长更长更长更长更长更长。”\n",
        "管理者管理的是混乱",
    ),
    (
        "跳过引文署名行",
        "> ——拉塞尔·阿科夫（Russell Ackoff），运筹学理论家\n",
        "",
    ),
    (
        "无引用时取带标签的行",
        "- **系统定义**：由相互连接的要素构成的整体。\n",
        "系统定义",
    ),
]


def run() -> int:
    """跑全部用例。

    Returns:
        失败用例数；0 表示全部通过。
    """
    failures = 0

    print("=== strip_preamble ===")
    for name, text, must_keep, must_drop in CASES:
        result = strip_preamble(text)
        problems = []
        for keep in must_keep:
            if keep not in result:
                problems.append(f"丢失了「{keep}」")
        for drop in must_drop:
            if drop in result:
                problems.append(f"残留了「{drop}」")
        # 长度守卫：单次过滤不该砍掉超过一半的内容。
        # 只对足够长的输入生效 —— 短输入本来就大半是噪音。
        if len(text) > 120 and len(result) < len(text) * 0.5:
            problems.append(
                f"内容被砍掉过多（{len(text)} → {len(result)} 字符）")
        if problems:
            failures += 1
            print(f"  [FAIL] {name}")
            for p in problems:
                print(f"         {p}")
            print(f"         输出：{result[:120]!r}")
        else:
            print(f"  [OK] {name}")

    print("\n=== _preview ===")
    for name, note, expect in PREVIEW_CASES:
        result = _preview(note)
        if expect and expect not in result:
            failures += 1
            print(f"  [FAIL] {name}")
            print(f"         期望包含「{expect}」，实际「{result}」")
        elif not expect and result:
            failures += 1
            print(f"  [FAIL] {name}")
            print(f"         期望空，实际「{result}」")
        else:
            print(f"  [OK] {name}")

    print("\n=== demote_headings ===")
    demote_cases = [
        ("# 一、标题\n正文", "## 一、标题\n正文"),
        ("### 三、标题\n正文", "#### 三、标题\n正文"),
        ("```\n# 代码里的井号\n```\n", "```\n# 代码里的井号\n```\n"),
    ]
    for text, expect in demote_cases:
        result = demote_headings(text)
        if result != expect:
            failures += 1
            print(f"  [FAIL] {text!r} → {result!r}，期望 {expect!r}")
        else:
            print(f"  [OK] {text!r}")

    print("\n=== is_chinese_heavy ===")
    zh_cases = [
        ("这是一个中文句子，包含了足够多的汉字用于通过判定。", True),
        ("This is entirely English text with no Chinese characters.", False),
    ]
    for text, expect in zh_cases:
        result = is_chinese_heavy(text)
        if result != expect:
            failures += 1
            print(f"  [FAIL] {text[:30]!r} → {result}，期望 {expect}")
        else:
            print(f"  [OK] {text[:30]!r}")

    print()
    if failures:
        print(f"失败 {failures} 项")
    else:
        print("全部通过")
    return failures


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
