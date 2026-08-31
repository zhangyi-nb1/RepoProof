"""Deterministic Product-intent safety classification.

This gate handles only explicit delivery requirements that are outside every
currently supported local, offline, per-invocation Product profile.  It runs
before repository access and before any model call.  The vocabulary describes
generic operating-system and external-system effects; repository names and
task-specific output fields do not belong here.

The classifier intentionally favours precision over recall.  Ambiguous prose
continues to the normal contract-authoring flow, where structured delivery
requirements are checked again.  An explicit high-risk intent, however, must
not consume repository, provider, or Agent work merely to be rejected later.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict


class IntentDeliveryRiskV1(BaseModel):
    """Public, value-free risk dimensions inferred from explicit user prose."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    credentials: Literal["none", "required"] = "none"
    network: Literal["offline", "required"] = "offline"
    browser: Literal["none", "required"] = "none"
    lifecycle: Literal["per_invocation", "long_running"] = "per_invocation"
    runtime: Literal["local_cpu", "gpu", "remote_service"] = "local_cpu"
    external_side_effects: Literal["none", "reversible", "irreversible"] = "none"
    reason_codes: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    @property
    def supported(self) -> bool:
        return not self.reason_codes


_POLARITY_BOUNDARY = re.compile(
    r"[。！？!?；;，,]|\b(?:but|however)\b|(?:但是|但|却)"
)
_ENGLISH_NEGATED_SUFFIX = re.compile(
    r"(?:\bdo not\b|\bdon't\b|\bdoes not\b|\bmust not\b|"
    r"\bshould not\b|\bwithout\b|\bnever\b|\bno(?:\s+need\s+to)?\b)"
    r"(?:[\s\w'/-]{0,64})$"
)
_CHINESE_NEGATED_SUFFIX = re.compile(
    r"(?:无需|无须|不要|不需要|不必|不得|禁止|避免|不)"
    r"(?:再|使用|进行|要求|主动|自动)?[^，。；;,.!?]{0,20}$"
)


def _match_is_explicitly_negated(text: str, start: int) -> bool:
    """Read polarity only inside the clause immediately preceding a match.

    Negation is deliberately lexical and local.  It prevents a statement such
    as ``不要联网`` from becoming an online-runtime requirement, while clause
    and contrast boundaries keep ``不需要浏览器，但是要上传`` classified as an
    external write.  Ambiguous prose continues to contract authoring instead
    of being promoted to a positive unsupported requirement.
    """

    prefix = text[max(0, start - 96):start]
    clause = _POLARITY_BOUNDARY.split(prefix)[-1]
    return bool(
        _ENGLISH_NEGATED_SUFFIX.search(clause)
        or _CHINESE_NEGATED_SUFFIX.search(clause)
    )


def _matches(patterns: tuple[re.Pattern[str], ...], text: str) -> bool:
    for pattern in patterns:
        for match in pattern.finditer(text):
            if not _match_is_explicitly_negated(text, match.start()):
                return True
    return False


_CREDENTIAL_PATTERNS = (
    re.compile(r"\b(?:log\s*in|login|sign\s*in|authenticate)\b"),
    re.compile(r"\b(?:use|access)\s+(?:my|a|the)\s+(?:private\s+)?account\b"),
    re.compile(r"(?:登录|登陆|身份认证|访问(?:我的|私人|私有)?(?:账户|账号)|使用(?:我的)?(?:账户|账号))"),
)
_NETWORK_PATTERNS = (
    re.compile(r"\b(?:fetch|download|query)\s+.+\s+from\s+(?:the\s+)?(?:online\s+)?(?:internet|web|api)\b"),
    re.compile(r"\b(?:live|online)\s+(?:website|api|service|data)\b"),
    re.compile(
        r"(?:联网|在线抓取|从(?:在线|远程)?\s*(?:网址|网站|接口|api)"
        r"\s*(?:下载|获取|读取|查询)|调用(?:在线|远程)?\s*api|实时查询(?:网站|接口))"
    ),
)
_BROWSER_PATTERNS = (
    re.compile(r"\b(?:browser automation|automate (?:a |the )?browser)\b"),
    re.compile(r"\b(?:open|click|fill|submit)\s+.+\s+(?:on|in)\s+(?:a |the )?(?:website|web page|browser)\b"),
    re.compile(r"(?:浏览器自动化|在(?:网页|网站|浏览器)(?:里|中)?(?:打开|点击|填写|提交))"),
)
_LONG_RUNNING_PATTERNS = (
    re.compile(r"\b(?:daemon|long[- ]running|keep running|run continuously|background listener)\b"),
    re.compile(r"\b(?:watch|monitor)\s+.+\s+(?:continuously|in real time|forever)\b"),
    re.compile(
        r"(?:常驻(?:服务|进程)?|持续运行|一直运行|后台监听|实时监听|"
        r"持续监控|一直监控|实时监控)"
    ),
)
_GPU_PATTERNS = (
    re.compile(r"\b(?:gpu|cuda|rocm)\b"),
    re.compile(r"(?:显卡加速|必须使用显卡|需要\s*gpu)"),
)
_REMOTE_RUNTIME_PATTERNS = (
    re.compile(r"\b(?:deploy|run)\s+.+\s+(?:as|to|on)\s+(?:a )?(?:cloud service|remote server|serverless function)\b"),
    re.compile(r"(?:部署到(?:云端|远程服务器)|作为(?:云服务|在线服务)运行)"),
)
_IRREVERSIBLE_PATTERNS = (
    re.compile(r"\b(?:make|execute|complete|send|submit|place|publish|delete|remove)\b.{0,48}\b(?:payment|transfer|transaction|order|message|post|record|resource|data)\b"),
    re.compile(r"\birreversible\s+(?:external\s+)?(?:action|operation|transaction|change)\b"),
    re.compile(r"(?:处理|执行|发起|完成|进行|提交|发送|发布|删除|购买|下单).{0,16}(?:付款|支付|转账|交易|订单|消息|内容|记录|资源|数据)"),
)
_REVERSIBLE_EXTERNAL_PATTERNS = (
    re.compile(
        r"\b(?:upload|sync|create|update|edit)\b.{0,48}\b(?:cloud\s+drive|"
        r"cloud\s+storage|calendar|ticket|issue|remote\s+service|website|web\s+page)\b"
    ),
    re.compile(
        r"(?:(?:上传|同步).{0,24}(?:云盘|云端|网站|远程服务)|"
        r"在(?:云盘|网站|远程服务|日历|工单系统).{0,24}(?:创建|更新|修改))"
    ),
)


def classify_product_intent_risk(capability_goal: str) -> IntentDeliveryRiskV1:
    """Classify only explicit unsupported topology and side-effect intent."""

    text = unicodedata.normalize("NFKC", capability_goal or "").casefold()
    credentials: Literal["none", "required"] = (
        "required" if _matches(_CREDENTIAL_PATTERNS, text) else "none"
    )
    network: Literal["offline", "required"] = (
        "required" if _matches(_NETWORK_PATTERNS, text) else "offline"
    )
    browser: Literal["none", "required"] = (
        "required" if _matches(_BROWSER_PATTERNS, text) else "none"
    )
    lifecycle: Literal["per_invocation", "long_running"] = (
        "long_running" if _matches(_LONG_RUNNING_PATTERNS, text) else "per_invocation"
    )
    runtime: Literal["local_cpu", "gpu", "remote_service"] = "local_cpu"
    if _matches(_GPU_PATTERNS, text):
        runtime = "gpu"
    elif _matches(_REMOTE_RUNTIME_PATTERNS, text):
        runtime = "remote_service"
    external_side_effects: Literal["none", "reversible", "irreversible"] = "none"
    if _matches(_IRREVERSIBLE_PATTERNS, text):
        external_side_effects = "irreversible"
    elif _matches(_REVERSIBLE_EXTERNAL_PATTERNS, text):
        external_side_effects = "reversible"

    # The compound class is intentionally dominant: it communicates the real
    # safety boundary instead of presenting two weaker topology mismatches.
    if credentials == "required" and external_side_effects != "none":
        return IntentDeliveryRiskV1(
            credentials=credentials,
            network=network,
            browser=browser,
            lifecycle=lifecycle,
            runtime=runtime,
            external_side_effects=external_side_effects,
            reason_codes=("UNSUPPORTED_CREDENTIALLED_EXTERNAL_SIDE_EFFECT",),
            blockers=(
                "需求明确要求身份凭证并执行外部写操作；当前 Product profile "
                "只交付无凭证、离线、无外部副作用的本地工具。",
            ),
        )

    reasons: list[str] = []
    blockers: list[str] = []
    if credentials == "required":
        reasons.append("UNSUPPORTED_CREDENTIALS_REQUIRED")
        blockers.append("需求明确要求身份凭证；当前 Product profile 不接收或代管凭证。")
    if external_side_effects == "irreversible":
        reasons.append("UNSUPPORTED_IRREVERSIBLE_EXTERNAL_SIDE_EFFECT")
        blockers.append("需求明确要求不可逆外部操作；当前 Product profile 仅允许无外部副作用的本地运行。")
    elif external_side_effects == "reversible":
        reasons.append("UNSUPPORTED_REVERSIBLE_EXTERNAL_SIDE_EFFECT")
        blockers.append(
            "需求明确要求向外部系统写入；即使可以撤销，当前 Product profile "
            "也只允许在新建的本地产物目录内写入。"
        )
    if network == "required":
        reasons.append("UNSUPPORTED_RUNTIME_NETWORK_REQUIRED")
        blockers.append("需求明确要求运行期联网；当前 Product profile 固定为运行期离线。")
    if browser == "required":
        reasons.append("UNSUPPORTED_BROWSER_REQUIRED")
        blockers.append("需求明确要求浏览器交互；当前 Product profile 不包含浏览器运行时。")
    if lifecycle == "long_running":
        reasons.append("UNSUPPORTED_LONG_RUNNING_LIFECYCLE")
        blockers.append("需求明确要求常驻运行；当前 Product profile 只支持单次调用。")
    if runtime == "gpu":
        reasons.append("UNSUPPORTED_GPU_RUNTIME")
        blockers.append("需求明确要求 GPU；当前 Product profile 固定为本地 CPU。")
    elif runtime == "remote_service":
        reasons.append("UNSUPPORTED_REMOTE_SERVICE_RUNTIME")
        blockers.append("需求明确要求远程服务运行；当前 Product profile 只交付本地工具。")

    return IntentDeliveryRiskV1(
        credentials=credentials,
        network=network,
        browser=browser,
        lifecycle=lifecycle,
        runtime=runtime,
        external_side_effects=external_side_effects,
        reason_codes=tuple(sorted(set(reasons))),
        blockers=tuple(blockers),
    )
