"""Failure Packet(RFC-006)— 把测试失败翻译成结构化修复输入。

铁律:不把原始 pytest 日志直接给 Agent——转成
{type, summary, affected_files, expected, actual, suggestion, owner}。
类型与建议由确定性规则映射。
"""

from __future__ import annotations

import re

from pydantic import BaseModel

DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
API_MISMATCH = "API_MISMATCH"
SCHEMA_ERROR = "SCHEMA_ERROR"
TEST_FAILURE = "TEST_FAILURE"
REGRESSION_FAILURE = "REGRESSION_FAILURE"
RESOURCE_MISSING = "RESOURCE_MISSING"
SCOPE_EXCEEDED = "SCOPE_EXCEEDED"
UNKNOWN = "UNKNOWN"
# 2026-08-13(LESSONS #36):同源级联与超时各自成型。
# 实录 order-55:15 项检查全死在同一句 setup 超时,却被摊成 15 枚几乎
# 一样的包,建议还统一写"阅读该项公开测试的断言语义"——测试压根没走到
# 断言。信息量 1 句、噪声 60 行、且指错方向。
TIMEOUT = "TIMEOUT"
SHARED_ROOT_CAUSE = "SHARED_ROOT_CAUSE"
# 循环层事件包(2026-08-12,LESSONS #33):回滚不得静默——
# 060126 实录里 agent 三轮不知道自己 12/12 的一轮为何消失。
ROLLBACK = "ROLLBACK"

_TYPE_RULES = [
    # 超时优先于一切:它常挂在 setup 上,任何按测试**名字**分类的规则
    # (如名里有"字段"→SCHEMA_ERROR)都会把它认错(order-55 实录)。
    (TIMEOUT, ("未在", "内终结", "timed out", "timeout", "timeouterror")),
    (SCOPE_EXCEEDED, ("protected path", "policy_denied", "越界", "保护路径", "scope")),
    (DEPENDENCY_ERROR, ("modulenotfounderror", "importerror", "no module named")),
    (API_MISMATCH, ("attributeerror", "typeerror: ", "unexpected keyword", "not callable")),
    (SCHEMA_ERROR, ("schema", "keys", "field", "keyerror", "missing")),
    (RESOURCE_MISSING, ("filenotfound", "no such file", "connection")),
]

_SUGGESTION = {
    # 措辞注意:不要在这里写出"断言语义"四字,哪怕是否定式提及——钉死用
    # 子串判据分不清"提及"与"主张"(同 claims 检查器的老问题,处置一律是
    # 改措辞而不是放宽检查器)。
    TIMEOUT: "作业没在公开测试给定的时限内终结——先让作业能稳定终结,再谈各项"
             "检查的正确性:缩短单个作业的端到端时间(复用浏览器会话而非每作业"
             "冷启、减少每步 LLM 往返、确保终态一定被写入)",
    SHARED_ROOT_CAUSE: "先修这一个根因:下列检查是它的连带伤亡,根因消掉后应一并转绿"
                       "——不要逐项去改各自的断言",
    DEPENDENCY_ERROR: "检查依赖导入:只允许使用任务环境中已安装的包,不要引入新依赖",
    API_MISMATCH: "对照目标仓库真实接口签名调整调用方式,不要猜测参数",
    SCHEMA_ERROR: "对照公开合同的输出字段修正映射:字段名、类型与嵌套结构都必须一致",
    TEST_FAILURE: "阅读该项公开测试的断言语义,修正适配逻辑而不是修改测试",
    REGRESSION_FAILURE: "你的修改影响了宿主项目原有行为——收缩修改范围,只动适配区",
    RESOURCE_MISSING: "缺少运行资源:确认只使用任务内提供的文件与环境",
    SCOPE_EXCEEDED: "修改超出允许范围——回到适配区内解决",
    UNKNOWN: "从失败测试的语义出发定位;不要重复相同的无效修改",
}


class FailurePacket(BaseModel):
    type: str
    summary: str
    affected_files: list[str] = []
    expected: str = ""
    actual: str = ""
    suggestion: str
    owner: str = "AGENT_ADAPTER"

    def to_dict(self) -> dict:
        return self.model_dump()


_RE_RAW_LOG = re.compile(r'(File "[^"]+", line \d+|^\s*(FAILED|ERROR)\b|Traceback \(|^={3,}|pytest)', re.MULTILINE)


def _sanitize(detail: str) -> str:
    """F4: 强制清洗——剔除原始 pytest/traceback 痕迹,保留首个断言语义行。"""
    lines = [ln.strip() for ln in detail.splitlines() if ln.strip()]
    kept = [ln for ln in lines if not _RE_RAW_LOG.search(ln)]
    return (kept[0] if kept else "断言失败(原始日志已按规则滤除)")[:200]


def _classify(node: str, detail: str) -> str:
    low = f"{node} {detail}".lower()
    if "regression" in low:
        return REGRESSION_FAILURE
    for ftype, keys in _TYPE_RULES:
        if any(k in low for k in keys):
            return ftype
    return TEST_FAILURE if "test" in low else UNKNOWN


_RE_VOLATILE = re.compile(r"\b[0-9a-f]{8,}\b|\d+(?:\.\d+)?")


def _root_signature(detail: str) -> str:
    """把断言摘要归一成"根因指纹":抹掉作业 id、哈希与数字。

    order-55 的 15 条摘要只差一个作业 id,归一后完全相同 —— 这正是
    "同一处失败被摊成 15 枚包"的机器判据。
    """
    return _RE_VOLATILE.sub("#", _sanitize(detail)).strip()


COLLAPSE_MIN = 3   # 同签名达此数量才合并;2 条不值得抽象


def build_failure_packets(
    failed_nodes: list[str],
    details: dict[str, str] | None = None,
    *,
    adapter_file: str = "adapter.py",
) -> list[FailurePacket]:
    """failed_nodes = 公开测试/回归的失败节点;details = 节点→断言摘要
    (可选,来自 junit message,已是摘要而非整段日志)。

    同根因折叠(LESSONS #36):≥COLLAPSE_MIN 项共享同一根因指纹时,合并成
    **一枚** SHARED_ROOT_CAUSE 包并列出全部受连累的检查项——信息一条不丢,
    只是不再把一句话抄 15 遍、也不再给出"去读各自断言"的错误指引。
    """
    details = details or {}
    groups: dict[str, list[str]] = {}
    for node in failed_nodes:
        detail = details.get(node, "")
        if detail:
            groups.setdefault(_root_signature(detail), []).append(node)

    collapsed = {n for sig, ns in groups.items() if len(ns) >= COLLAPSE_MIN for n in ns}
    packets: list[FailurePacket] = []
    emitted: set[str] = set()

    for node in failed_nodes:
        detail = details.get(node, "")
        human = node.split("::")[-1].replace("test_", "").replace("_", " ")
        if node in collapsed:
            sig = _root_signature(detail)
            if sig in emitted:
                continue
            emitted.add(sig)
            peers = groups[sig]
            names = [n.split("::")[-1].replace("test_", "").replace("_", " ")
                     for n in peers]
            cause = _classify(node, detail)
            packets.append(FailurePacket(
                type=SHARED_ROOT_CAUSE,
                # 全量列名:折叠是"不重复抄同一句根因",不是截断受害者名单
                # (自咬实录:初版写 names[:6],被 H6-c 零信息丢失判据当场抓住)
                summary=(f"{len(peers)} 项检查倒在**同一个根因**上"
                         f"(判定类型 {cause}):" + "、".join(names)),
                affected_files=[adapter_file],
                expected="消除该根因后这些检查应一并转绿",
                actual=_sanitize(detail),
                suggestion=(f"{_SUGGESTION[SHARED_ROOT_CAUSE]}。"
                            f"该根因的处置:{_SUGGESTION[cause]}"),
                owner="HOST" if cause == REGRESSION_FAILURE else "AGENT_ADAPTER",
            ))
            continue
        ftype = _classify(node, detail)
        packets.append(FailurePacket(
            type=ftype,
            summary=f"检查项「{human}」未通过",
            affected_files=[adapter_file],
            expected=f"满足公开合同中与「{human}」对应的要求",
            actual=(_sanitize(detail) if detail else "该检查项断言失败"),
            suggestion=_SUGGESTION[ftype],
            owner="HOST" if ftype == REGRESSION_FAILURE else "AGENT_ADAPTER",
        ))
    return packets
