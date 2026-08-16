"""deepseek-native 适配器(EXECUTOR-UPGRADE-PLAN §6 P-D)。

直连 DeepSeek 官方 API(OpenAI 兼容面),但**不**复用 openai-compatible
通道的默认假设——五条卫生规则由本适配器**own**,不依赖 litellm 猜:

  R1 assistant content 非 null(None→"",官方拒 null content);
  R2 reasoning_content 回传按 profile 旋钮走:``tool_loop`` = 只在带
     tool_calls 的 assistant 消息上保留(思考模式工具轮官方语义),
     其余位置一律剥除;``strip`` = 全剥(canary-2 实测裁定用哪个);
  R3 绝不发送 tool_choice(官方思考模式不兼容)——构造期即拒;
  R4 SSE 流式 + include_usage,**流内绝不续传/半重试**:任何中途
     异常整支请求作废,由外层 retry 决定是否整发重来;
  R5 输入消息白名单化:assistant 只保留 role/content/tool_calls/
     reasoning_content(条件),tool 只保留 role/content/tool_call_id/
     name;model_dump 带出的 provider_specific_fields / annotations /
     function_call / index 等一律不上行。

哈希纪律(Gate 4B):DeepSeekProviderConfig.normalized() 在父类字段
之外并入全部行为旋钮(top_p / reasoning_effort / reasoning_passback),
两条消融 profile(§55)因此各得独立 provider_config_sha256——
单变量可比性由哈希层保证,不靠台账备注。

API key 永不入 config/model_kwargs(二者会被 serialize() 落盘):
与 openai 路一致走进程 env(DEEPSEEK_API_KEY / DEEPSEEK_API_BASE),
litellm 的 ``deepseek/`` 前缀按官方路由读取。
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal

# litellm DEV 模式(默认)在 import 时把 CWD .env 全量 load_dotenv 进
# os.environ —— 秘密静默入环境 + 配置来源失守(Gate 4A:官方运行只读
# 宿主显式 env)。必须先于 litellm import 钉死;setdefault 可显式覆盖。
os.environ.setdefault("LITELLM_MODE", "PRODUCTION")

import litellm  # noqa: E402
from minisweagent.models.litellm_model import LitellmModel, LitellmModelConfig  # noqa: E402

from repoproof.agents.provider_gate import ProviderConfig

logger = logging.getLogger("deepseek_native")

# 适配器 own 的调用面:这些 kwargs 由 _query 统一注入或明令禁止,
# 出现在 model_kwargs 里即配置错误(R3/R4),构造期抛错不静默丢弃。
FORBIDDEN_MODEL_KWARGS = ("tool_choice", "tools", "stream", "stream_options", "n")


@dataclass(frozen=True)
class DeepSeekProviderConfig(ProviderConfig):
    """ProviderConfig + DeepSeek 行为旋钮(全部进 normalized() 哈希)。"""

    top_p: str = "unset"                 # "unset" | 十进制字符串,如 "0.95"
    reasoning_effort: str = "unset"      # "unset" | "high" | "max"(§55 候选)
    reasoning_passback: str = "tool_loop"  # "tool_loop" | "strip"(R2)

    PROVIDER_TYPE = "deepseek-native"

    def normalized(self) -> dict:
        return {
            **super().normalized(),
            "top_p": self.top_p,
            "reasoning_effort": self.reasoning_effort,
            "reasoning_passback": self.reasoning_passback,
        }


# §55 两候选 profile(§66:官方 Flash 参数只是候选,不是 Pro 的答案;
# 谁当正选由 DQ 消融 + 后续 WH/HB 实测裁,不在此处预设)。
DS_PROFILES: dict[str, dict[str, str]] = {
    "DS-NATIVE-HIGH-DET": {
        "temperature_policy": "0",
        "top_p": "unset",
        "reasoning_effort": "high",
        "reasoning_passback": "tool_loop",
    },
    "DS-NATIVE-MAX-OFFICIAL-LIKE": {
        "temperature_policy": "1.0",
        "top_p": "0.95",
        "reasoning_effort": "max",
        "reasoning_passback": "tool_loop",
    },
}


def build_deepseek_provider(
    *, profile: str, api_base: str, api_key: str, model_name: str
) -> DeepSeekProviderConfig:
    """按命名 profile 构造 provider(action_protocol 冻结为 native:
    DQ 只认 function-calling 面;native 探针不过即 BLOCKED,不落回
    textbased——那是另一个协议,不是本资格的对象)。"""
    if profile not in DS_PROFILES:
        raise ValueError(f"unknown deepseek profile {profile!r}; valid: {sorted(DS_PROFILES)}")
    return DeepSeekProviderConfig(
        provider="deepseek-native",
        model_name=model_name,
        api_base=api_base.rstrip("/"),
        api_key=api_key,
        action_protocol="native",
        **DS_PROFILES[profile],
    )


def build_model_kwargs(cfg: DeepSeekProviderConfig, call_timeout_s: float | None) -> dict:
    """provider 旋钮 → litellm completion kwargs(unset 即不上行)。"""
    kw: dict[str, Any] = {}
    if cfg.temperature_policy != "provider_default":
        kw["temperature"] = float(cfg.temperature_policy)
    if cfg.top_p != "unset":
        kw["top_p"] = float(cfg.top_p)
    if cfg.reasoning_effort != "unset":
        kw["reasoning_effort"] = cfg.reasoning_effort
    if call_timeout_s is not None:
        kw["timeout"] = call_timeout_s
    return kw


def list_models(api_base: str, api_key: str, timeout_s: float = 20.0) -> list[dict]:
    """GET /models —— canary 取证 alias 与 resolved release 分开记
    (§6:跑的是别名还是钉死版本,证据层必须能说清)。"""
    req = urllib.request.Request(
        api_base.rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = json.loads(resp.read())
    data = body.get("data") or []
    return [d for d in data if isinstance(d, dict)]


class DeepSeekNativeModelConfig(LitellmModelConfig):
    reasoning_passback: Literal["tool_loop", "strip"] = "tool_loop"
    """R2 旋钮;进 config dump(serialize/get_template_vars),无秘密。"""


class DeepSeekNativeModel(LitellmModel):
    """LitellmModel 的 DeepSeek 直连变体。

    只改两处:``_prepare_messages_for_api``(R1/R2/R5 消息卫生)与
    ``_query``(R4 流式传输)。retry 骨架、FormatError 时响应+成本
    必留痕、``extra.response.usage`` 同步记账形状(TokenBudgetedModel
    契约)全部继承基类——与 GPT 六发同一套已实弹验证的骨架。
    """

    _ASSISTANT_KEEP = ("role", "content", "tool_calls", "reasoning_content")
    _TOOL_KEEP = ("role", "content", "tool_call_id", "name")

    def __init__(self, *, config_class: type = DeepSeekNativeModelConfig, **kwargs):
        super().__init__(config_class=config_class, **kwargs)
        bad = [k for k in FORBIDDEN_MODEL_KWARGS if k in self.config.model_kwargs]
        if bad:
            raise ValueError(
                f"deepseek-native owns {bad} — remove from model_kwargs (R3/R4)"
            )
        if not self.config.model_name.startswith("deepseek/"):
            raise ValueError(
                f"model_name must carry the deepseek/ litellm route, got {self.config.model_name!r}"
            )

    # ---- R1/R2/R5:输入消息卫生(适配器 own,不依赖上游猜) ----
    def _prepare_messages_for_api(self, messages: list[dict]) -> list[dict]:
        prepared: list[dict] = []
        for msg in messages:
            role = msg.get("role")
            if role == "assistant":
                m = {k: msg[k] for k in self._ASSISTANT_KEEP if k in msg}
                if m.get("content") is None:
                    m["content"] = ""                       # R1
                if m.get("tool_calls"):
                    m["tool_calls"] = [
                        {k: v for k, v in tc.items() if k != "index"}
                        for tc in m["tool_calls"]
                    ]
                else:
                    m.pop("tool_calls", None)
                in_tool_loop = bool(m.get("tool_calls"))
                if self.config.reasoning_passback != "tool_loop" or not in_tool_loop:
                    m.pop("reasoning_content", None)        # R2
                elif m.get("reasoning_content") is None:
                    m.pop("reasoning_content", None)
            elif role == "tool":
                m = {k: msg[k] for k in self._TOOL_KEEP if k in msg}
                if m.get("content") is None:
                    m["content"] = ""
            else:
                m = {k: v for k, v in msg.items() if k != "extra"}
            prepared.append(m)
        return prepared

    # ---- R4:SSE 流式;流内零重试,整支失败整支重来(外层 retry) ----
    def _query(self, messages: list[dict[str, str]], **kwargs):
        merged = self.config.model_kwargs | kwargs
        bad = [k for k in FORBIDDEN_MODEL_KWARGS if k in merged]
        if bad:
            raise ValueError(f"deepseek-native owns {bad}; refusing to send (R3/R4)")
        stream = litellm.completion(
            model=self.config.model_name,
            messages=messages,
            tools=[self._bash_tool()],
            stream=True,
            stream_options={"include_usage": True},
            **merged,
        )
        chunks: list[Any] = []
        reasoning_parts: list[str] = []
        for chunk in stream:  # 中途异常直接冒泡:不续传、不半重试
            chunks.append(chunk)
            try:
                rc = getattr(chunk.choices[0].delta, "reasoning_content", None)
            except (AttributeError, IndexError):
                rc = None
            if rc:
                reasoning_parts.append(rc)
        response = litellm.stream_chunk_builder(chunks, messages=messages)
        if response is None or not getattr(response, "choices", None):
            raise RuntimeError("deepseek stream yielded no usable chunks")
        # builder 版本差异兜底:delta 里见过 reasoning_content 而组装件
        # 丢了 → 注回消息对象(litellm Message extra=allow,dump 会带出)。
        message = response.choices[0].message
        if reasoning_parts and not getattr(message, "reasoning_content", None):
            message.reasoning_content = "".join(reasoning_parts)
        return response

    @staticmethod
    def _bash_tool() -> dict:
        from minisweagent.models.utils.actions_toolcall import BASH_TOOL

        return BASH_TOOL
