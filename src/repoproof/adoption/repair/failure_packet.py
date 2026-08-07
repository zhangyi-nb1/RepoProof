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

_TYPE_RULES = [
    (SCOPE_EXCEEDED, ("protected path", "policy_denied", "越界", "保护路径", "scope")),
    (DEPENDENCY_ERROR, ("modulenotfounderror", "importerror", "no module named")),
    (API_MISMATCH, ("attributeerror", "typeerror: ", "unexpected keyword", "not callable")),
    (SCHEMA_ERROR, ("schema", "keys", "field", "keyerror", "missing")),
    (RESOURCE_MISSING, ("filenotfound", "no such file", "connection")),
]

_SUGGESTION = {
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


def build_failure_packets(
    failed_nodes: list[str],
    details: dict[str, str] | None = None,
    *,
    adapter_file: str = "adapter.py",
) -> list[FailurePacket]:
    """failed_nodes = 公开测试/回归的失败节点;details = 节点→断言摘要
    (可选,来自 junit message,已是摘要而非整段日志)。"""
    details = details or {}
    packets: list[FailurePacket] = []
    for node in failed_nodes:
        detail = details.get(node, "")
        ftype = _classify(node, detail)
        human = node.split("::")[-1].replace("test_", "").replace("_", " ")
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
