"""Pawread LLM 客户端。

**职责**：封装百炼（DashScope）模型调用，负责

1. 模型池与按模型维度的额度记账；
2. 额度用尽时自动切换到下一个模型（用尽即停）；
3. 原生端点调用，**搜索能力只在原生端点生效**；
4. 结构化 JSON 输出与用量记录。

**上游**：`pipeline.py` 的规范化、站点建议、总结三个阶段。
**下游**：`pipeline.py` 的各阶段返回值。

**为什么不用 compatible-mode**：实测 `extra_body.enable_search` 在
compatible-mode 端点被静默忽略 —— 不报错，但模型会自称不做实时搜索，
且 `usage.plugins.search` 缺失。原生端点
`/api/v1/services/aigc/text-generation/generation` 才返回
`usage.plugins.search.count`。详见 `pawread/MODELS.md`。

**免费额度**：按模型各 1M token 计，池内共 16 个已开通模型
（实测数据，见 `data/model_pool.json`）。本模块不使用任何付费 API。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .env import get_str, load_env

#: 项目根目录。
ROOT = Path(__file__).resolve().parent.parent

#: 模型池配置文件。
MODEL_POOL_PATH = Path(__file__).resolve().parent.parent / "data" / "model_pool.json"

#: 百炼原生端点。搜索能力只在这里生效。
NATIVE_ENDPOINT = ("https://dashscope.aliyuncs.com/api/v1/services/"
                   "aigc/text-generation/generation")


class LLMError(RuntimeError):
    """LLM 调用失败。

    字段:
        status: HTTP 状态码，0 表示网络层失败。
        error_type: 百炼返回的错误码，无则为 None。
        message: 错误消息。
    """

    def __init__(self, message: str, status: int = 0,
                 error_type: Optional[str] = None) -> None:
        super().__init__(message)
        self.status = status
        self.error_type = error_type
        self.message = message


@dataclass
class LLMUsage:
    """一次 LLM 调用的用量记录。

    字段:
        model: 实际使用的模型。
        prompt_tokens: 输入 token 数。
        completion_tokens: 输出 token 数。
        total_tokens: 总 token 数。
        search_count: 触发的搜索次数，0 表示未联网。
        latency_ms: 耗时毫秒。
        error: 失败时的错误消息，成功时为空串。
    """

    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    search_count: int = 0
    latency_ms: int = 0
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转为可 JSON 序列化的字典。

        Returns:
            用量字典。
        """
        return {
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "search_count": self.search_count,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass
class ModelBudget:
    """单个模型的额度记账。

    字段:
        model: 模型名。
        limit: 额度上限（token）。0 表示不限。
        used: 已消耗 token。
        calls: 调用次数。
        exhausted: 额度是否已用尽。
    """

    model: str
    limit: int = 0
    used: int = 0
    calls: int = 0
    exhausted: bool = False

    @property
    def remaining(self) -> int:
        """剩余额度。limit 为 0 时返回无限大的整数。

        Returns:
            剩余 token 数。
        """
        if self.limit <= 0:
            return 2 ** 62
        return max(0, self.limit - self.used)

    def can_afford(self, estimated: int) -> bool:
        """判断剩余额度是否够一次预估消耗的调用。

        额度已耗尽的模型一律不可用。注意 `estimated` 为 0 时
        仍要求剩余额度大于 0 —— 否则额度刚好用尽的模型会被反复选中。

        Args:
            estimated: 预估 token 消耗。

        Returns:
            够用时返回 True。
        """
        if self.exhausted:
            return False
        if self.limit <= 0:
            return True
        remaining = self.limit - self.used
        return remaining > 0 and remaining >= estimated


class ModelPool:
    """模型池。按档位顺序使用，额度用尽即停并切换下一���。

    档位定义在 `data/model_pool.json` 的 `tiers` 字段，
    每档是模型名列表。测试阶段用 `test` 档（`qwen-flash`）。
    """

    def __init__(self, pool_path: Path = MODEL_POOL_PATH) -> None:
        """初始化模型池。

        Args:
            pool_path: 模型池配置文件路径。
        """
        config = json.loads(pool_path.read_text(encoding="utf-8"))
        self._tiers: Dict[str, List[str]] = {}
        for tier, value in (config.get("tiers") or {}).items():
            if tier.startswith("_"):
                continue
            # 档位结构为 {"_desc": 说明, "models": [模型名, ...]}
            if isinstance(value, dict):
                names = value.get("models") or []
            else:
                names = value
            self._tiers[tier] = [str(m) for m in names
                                 if not str(m).startswith("_")]
        per_model = (config.get("budget") or {}).get("per_model_tokens", 0)
        self._budgets: Dict[str, ModelBudget] = {}
        for models in self._tiers.values():
            for name in models:
                self._budgets.setdefault(name, ModelBudget(model=name,
                                                          limit=per_model))

    @property
    def tiers(self) -> Dict[str, List[str]]:
        """可用档位。

        Returns:
            档位名到模型名列表的映射。
        """
        return self._tiers

    def models_for(self, tier: str) -> List[str]:
        """取指定档位的模型列表。

        Args:
            tier: 档位名。

        Returns:
            模型名列表；档位不存在时返回空列表。
        """
        return list(self._tiers.get(tier, []))

    def budget(self, model: str) -> ModelBudget:
        """取某模型的额度记录。

        Args:
            model: 模型名。

        Returns:
            额度记录；模型不在池内时新建一条不限额记录。
        """
        if model not in self._budgets:
            self._budgets[model] = ModelBudget(model=model, limit=0)
        return self._budgets[model]

    def pick(self, tier: str, estimate: int = 0) -> Optional[str]:
        """从档位里挑一个额度够用的模型。

        Args:
            tier: 档位名。
            estimate: 预估 token 消耗。

        Returns:
            模型名；档位内所有模型额度都不够时返回 None。
        """
        for name in self.models_for(tier):
            if self.budget(name).can_afford(estimate):
                return name
        return None

    def record(self, model: str, tokens: int) -> None:
        """记账一次调用的 token 消耗。

        Args:
            model: 模型名。
            tokens: 本次消耗的 token 数。
        """
        budget = self.budget(model)
        budget.used += max(0, tokens)
        budget.calls += 1
        if budget.limit > 0 and budget.used >= budget.limit:
            budget.exhausted = True

    def exhausted_models(self) -> List[str]:
        """列出额度用尽的模型。

        Returns:
            用尽的模型名列表。
        """
        return [b.model for b in self._budgets.values() if b.exhausted]

    def summary(self) -> Dict[str, Any]:
        """池的用量汇总。

        Returns:
            含总量与逐模型明细的字典。
        """
        return {
            "total_tokens": sum(b.used for b in self._budgets.values()),
            "total_calls": sum(b.calls for b in self._budgets.values()),
            "exhausted": self.exhausted_models(),
            "by_model": {
                b.model: {"used": b.used, "calls": b.calls,
                          "limit": b.limit, "exhausted": b.exhausted}
                for b in self._budgets.values() if b.calls
            },
        }


class LLMClient:
    """百炼模型客户端。

    用法：
        client = LLMClient(tier="test")
        text, usage = client.complete("你好")
    """

    def __init__(self, tier: str = "test",
                 pool: Optional[ModelPool] = None,
                 api_key: Optional[str] = None,
                 timeout: int = 180) -> None:
        """初始化客户端。

        Args:
            tier: 使用的模型档位。默认 `test`（`qwen-flash`）。
            pool: 模型池。缺省时按配置文件新建。
            api_key: 百炼 API Key。缺省读 `DASHSCOPE_API_KEY` 环境变量。
            timeout: 单次请求超时秒数。
        """
        self.tier = tier
        self.pool = pool or ModelPool()
        self.api_key = api_key or get_str("DASHSCOPE_API_KEY")
        self.timeout = timeout
        self.usages: List[LLMUsage] = []

    def _load_env(self) -> None:
        """从 `config/env.local` 补齐缺失的环境变量。

        只在变量缺失时写入，不覆盖已有值。

        Returns:
            无。
        """
        load_env()

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """向原生端点发起一次请求。

        Args:
            payload: 请求体。

        Returns:
            解析后的响应体。

        Raises:
            LLMError: 缺少凭据或请求失败时抛出。
        """
        if not self.api_key:
            self._load_env()
            self.api_key = get_str("DASHSCOPE_API_KEY")
        if not self.api_key:
            raise LLMError("缺少 DASHSCOPE_API_KEY，无法调用百炼模型")
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            NATIVE_ENDPOINT, data=body,
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = json.loads(exc.read()).get("message", "")
            except Exception:  # noqa: BLE001 - 错误体可能不是 JSON
                detail = ""
            raise LLMError(
                f"{exc.code} {detail or exc.reason}", status=exc.code) from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"网络错误：{exc.reason}") from exc

    def complete(self, prompt: str,
                 model: Optional[str] = None,
                 search: bool = False,
                 json_output: bool = False,
                 max_tokens: int = 2048,
                 temperature: float = 0.3,
                 estimate: int = 0) -> tuple:
        """调用模型生成文本。

        额度不足时自动切换到档位内的下一个模型。
        档位内所有模型额度用尽时抛出 `LLMError`。

        Args:
            prompt: 用户提示词。
            model: 指定模型。缺省时按档位自动挑选。
            search: 是否开启联网搜索。
            json_output: 是否要求 JSON 输出。
            max_tokens: 最大输出 token。
            temperature: 采样温度。
            estimate: 预估 token 消耗，用于选模型时判断额度。

        Returns:
            `(文本, LLMUsage)` 二元组。

        Raises:
            LLMError: 无可用模型或调用失败时抛出。
        """
        import time

        target = model
        if target is None:
            target = self.pool.pick(self.tier, estimate)
            if target is None:
                raise LLMError(
                    f"档位 {self.tier} 内所有模型额度已用尽："
                    f"{self.pool.exhausted_models()}")

        params: Dict[str, Any] = {
            "result_format": "message",
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if search:
            params["enable_search"] = True
        if json_output:
            params["response_format"] = {"type": "json_object"}

        payload = {
            "model": target,
            "input": {"messages": [{"role": "user", "content": prompt}]},
            "parameters": params,
        }

        started = time.monotonic()
        try:
            data = self._post(payload)
        except LLMError as exc:
            usage = LLMUsage(model=target, latency_ms=int(
                (time.monotonic() - started) * 1000), error=exc.message)
            self.usages.append(usage)
            raise

        latency = int((time.monotonic() - started) * 1000)
        raw_usage = data.get("usage") or {}
        plugins = raw_usage.get("plugins") or {}
        search_count = ((plugins.get("search") or {}).get("count")) or 0
        total = int(raw_usage.get("total_tokens") or 0)

        self.pool.record(target, total)
        usage = LLMUsage(
            model=target,
            prompt_tokens=int(raw_usage.get("input_tokens")
                              or raw_usage.get("prompt_tokens") or 0),
            completion_tokens=int(raw_usage.get("output_tokens")
                                  or raw_usage.get("completion_tokens") or 0),
            total_tokens=total,
            search_count=int(search_count),
            latency_ms=latency,
        )
        self.usages.append(usage)

        try:
            content = data["output"]["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            usage.error = f"响应结构异常：{exc}"
            raise LLMError(f"响应结构异常：{exc}") from exc
        return content, usage

    def complete_json(self, prompt: str, **kwargs: Any) -> tuple:
        """调用模型并解析 JSON 输出。

        模型可能在 JSON 前后包裹 ```json 标记或解释文字，
        这里做容错提取。

        Args:
            prompt: 用户提示词。
            **kwargs: 透传给 `complete`。

        Returns:
            `(解析后的对象, LLMUsage)` 二元组。

        Raises:
            LLMError: 输出无法解析为 JSON 时抛出。
        """
        kwargs.setdefault("json_output", True)
        content, usage = self.complete(prompt, **kwargs)
        parsed = extract_json(content)
        if parsed is None:
            usage.error = "输出无法解析为 JSON"
            raise LLMError("输出无法解析为 JSON", error_type="parse")
        return parsed, usage

    def summary(self) -> Dict[str, Any]:
        """本次会话的用量汇总。

        Returns:
            含池汇总与逐次调用的字典。
        """
        return {
            "tier": self.tier,
            "pool": self.pool.summary(),
            "calls": [u.to_dict() for u in self.usages],
        }


def extract_json(text: str) -> Optional[Any]:
    """从模型输出里提取 JSON。

    容忍 ```json 代码块包裹与前后杂音。

    Args:
        text: 模型原始输出。

    Returns:
        解析出的对象；无法解析时返回 None。
    """
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?", "", text)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start == -1 or end <= start:
            return None
    try:
        return json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return None
