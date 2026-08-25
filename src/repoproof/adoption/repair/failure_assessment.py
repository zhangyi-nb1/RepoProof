"""FailureAssessmentV1 · 修复循环事实的 Local Tool 产品投影(Gate 2)。

指导 §6 Gate 2 的定位:**不是**第二套 repair loop,也不改写任何内部
stop reason / 历史 run / 台账 —— 本模块是纯读取侧投影:吃 run 的
report dict,确定性派生 owner / repairability / Product 终止码 / 修复
指标。同一份 report 任何时候投影结果逐字节一致;历史 run 与新 run 同
一条函数,不回写任何东西。

泄漏纪律:投影产物是 Product Mode 的公开呈现面 —— 一切自由文本经
`_sanitize` 规范化(去 held-out 期望、去路径、去具体值),只保留
稳定 reason class;fingerprint 只由公开面事实(verdict + 规范化
gate_reasons + 公开轮次曲线)构成。
"""

from __future__ import annotations

import hashlib
import re
from typing import Literal

from pydantic import BaseModel, Field

ProductStopCode = Literal[
    "NO_REPAIR_NEEDED",         # 初次候选即过,不计 repair rescue
    "REPAIR_SUCCEEDED",         # 修复后独立门通过
    "STOP_NON_REPAIRABLE",      # 失败类别不允许交给 Agent 修
    "STOP_NEEDS_HUMAN",         # 合同/样例/范围变化需要人决策
    "STOP_NO_PROGRESS",         # 连续无改善或同一公开根因重复
    "STOP_SCOPE_DRIFT",         # 实际越界/篡改保护面/硬 policy
    "STOP_BUDGET_EXHAUSTED",    # 轮次/token/patch 预算耗尽
    "STOP_HIDDEN_FAILURE",      # 隐藏验收面(held-out/采纳门)失败,不泄细节
    "STOP_HARNESS_OR_EXTERNAL", # harness/provider/网络/上游故障
]

FailureOwner = Literal["AGENT", "CONTRACT", "USER", "HARNESS", "UPSTREAM", "EXTERNAL"]
Repairability = Literal["REPAIRABLE", "NON_REPAIRABLE", "NEEDS_HUMAN"]
RecommendedAction = Literal["REPAIR", "STOP", "ASK_USER", "RETRY_INFRASTRUCTURE"]

_PASS = ("PASS_ADAPTED", "PASS_DIRECT")

# 呈现面净化:数字、十六进制、引号内容、绝对路径 → 占位。规范化后的
# 文本才允许进入 fingerprint 与 assessment 的任何字段。
_RE_QUOTED = re.compile(r"(['\"]).*?\1")
_RE_HEX = re.compile(r"\b[0-9a-f]{8,}\b")
_RE_NUM = re.compile(r"\b\d+\b")
_RE_PATH = re.compile(r"(/[\w.\-]+){2,}")


def _sanitize(text: str) -> str:
    t = _RE_QUOTED.sub("'…'", str(text))
    t = _RE_PATH.sub("<path>", t)
    t = _RE_HEX.sub("<hex>", t)
    t = _RE_NUM.sub("<n>", t)
    return " ".join(t.split())[:200]


class FailureAssessmentV1(BaseModel):
    schema_version: int = 1
    failure_owner: FailureOwner = "AGENT"
    repairability: Repairability = "NON_REPAIRABLE"
    reason_codes: list[str] = Field(default_factory=list)
    public_failure_fingerprint: str = ""
    progress_snapshot: dict = Field(default_factory=dict)
    allowed_feedback: list[str] = Field(default_factory=list)
    redacted_fields: list[str] = Field(default_factory=list)
    recommended_action: RecommendedAction = "STOP"
    product_stop_code: str = ""


# ------------------------------------------------------------ 事实抽取

def _repair(report: dict) -> dict:
    return report.get("repair") or {}


def _gate_reasons(report: dict) -> list[str]:
    return [str(x) for x in (report.get("gate_reasons") or [])]


def _has(report: dict, *needles: str) -> bool:
    blob = " ".join(_gate_reasons(report)) + " " + str(report.get("policy") or "")
    return any(n in blob for n in needles)


def _held_out_failed(report: dict) -> bool:
    blob = " ".join(_gate_reasons(report)) + " " + str(report.get("capability") or "")
    return "test_held_" in blob


def _receipt_failed(report: dict) -> bool:
    rv = report.get("receipt_verification")
    return isinstance(rv, dict) and rv.get("ok") is False


# ------------------------------------------------------ Product 终止码投影

def product_stop_code(report: dict) -> str:
    """§2.5 映射表的确定性实现。输入=report dict(历史或新 run 同函)。

    映射按特异性排序:人决策 > 系统层 > 越界 > 隐藏面 > 预算 > 停滞;
    成功侧按 rounds_run 分「无需修复 / 修复成功」。表未覆盖的 FAIL 兜底
    到 STOP_NO_PROGRESS(最保守:不虚构类别,也不发明新码)。
    """
    verdict = str(report.get("verdict") or report.get("final_verdict") or "")
    rep = _repair(report)
    rounds = int(rep.get("rounds_run") or 0)
    stop = str(rep.get("stop_reason") or "")

    if verdict in _PASS:
        return "NO_REPAIR_NEEDED" if rounds <= 1 else "REPAIR_SUCCEEDED"

    if rep.get("pending_scope_change") or stop == "scope_change_pending_user" \
            or str(report.get("state") or "") == "SCOPE_CHANGE_PENDING_USER":
        return "STOP_NEEDS_HUMAN"

    if verdict == "BLOCKED" or str(report.get("state") or "").startswith("CRASHED"):
        return "STOP_HARNESS_OR_EXTERNAL"
    if _has(report, "RECEIPT_VERIFIER_ERROR", "UPSTREAM_EXECUTION_ERROR",
            "missing_external"):
        return "STOP_HARNESS_OR_EXTERNAL"

    if _has(report, "PolicyVerifier", "INSTRUMENT_TAMPERED",
            "PUBLIC_SURFACE_TAMPERED", "OUT_OF_WORKSPACE_ACCESS",
            "max_patch_files", "max_patch_lines"):
        return "STOP_SCOPE_DRIFT"

    # 隐藏面失败的语义前提:公开面已全绿、循环正常收束后才进独立门 ——
    # 公开面本身就红的 run(如骨架 noop)哪怕 detail 里出现 held 节点字样,
    # 也属公开失败形态,按停滞/预算归类(E2E noop 实测)。
    if stop == "all_public_green_pending_verification" and (
            _held_out_failed(report) or _receipt_failed(report)):
        return "STOP_HIDDEN_FAILURE"

    if stop in ("max_rounds", "budget_exhausted") or report.get("budget_exhausted"):
        return "STOP_BUDGET_EXHAUSTED"
    if stop == "stagnation":
        return "STOP_NO_PROGRESS"
    return "STOP_NO_PROGRESS"


# ------------------------------------------------------------ 全量投影

_OWNER_BY_CODE: dict[str, tuple[FailureOwner, Repairability, RecommendedAction]] = {
    "NO_REPAIR_NEEDED": ("AGENT", "REPAIRABLE", "STOP"),
    "REPAIR_SUCCEEDED": ("AGENT", "REPAIRABLE", "STOP"),
    "STOP_NON_REPAIRABLE": ("CONTRACT", "NON_REPAIRABLE", "STOP"),
    "STOP_NEEDS_HUMAN": ("USER", "NEEDS_HUMAN", "ASK_USER"),
    "STOP_NO_PROGRESS": ("AGENT", "NON_REPAIRABLE", "STOP"),
    "STOP_SCOPE_DRIFT": ("AGENT", "NON_REPAIRABLE", "STOP"),
    "STOP_BUDGET_EXHAUSTED": ("AGENT", "NON_REPAIRABLE", "STOP"),
    "STOP_HIDDEN_FAILURE": ("AGENT", "NON_REPAIRABLE", "STOP"),
    "STOP_HARNESS_OR_EXTERNAL": ("HARNESS", "NON_REPAIRABLE",
                                 "RETRY_INFRASTRUCTURE"),
}


def _fingerprint(report: dict) -> str:
    """公开失败指纹:verdict + 规范化 gate_reasons + 公开轮次曲线。
    只吃公开面事实;规范化把具体值(路径/数字/引号内容)全部抹平,
    同根因 → 同指纹,不泄任何真值。"""
    basis = "|".join([
        str(report.get("verdict") or ""),
        ";".join(sorted(_sanitize(g) for g in _gate_reasons(report))),
        ",".join(str(x) for x in (report.get("public_passed_by_round") or [])),
    ])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def assess_report(report: dict) -> FailureAssessmentV1:
    code = product_stop_code(report)
    owner, repairable, action = _OWNER_BY_CODE[code]

    reasons: list[str] = []
    if _held_out_failed(report):
        reasons.append("HIDDEN_ACCEPTANCE_FAILED")
    if _receipt_failed(report):
        reasons.append("UPSTREAM_ADOPTION_FAILED")
        # 归因细化:采纳失败的 harness 侧已被 stop code 分流;走到这里的
        # 属被测方 —— owner 保持 AGENT。
    if _has(report, "INSTRUMENT_TAMPERED", "PUBLIC_SURFACE_TAMPERED",
            "OUT_OF_WORKSPACE_ACCESS"):
        reasons.append("PROTECTED_SURFACE_TAMPERED")
    if _has(report, "OUTPUT_CONTRACT_MISMATCH", "tool-output-contract"):
        reasons.append("OUTPUT_CONTRACT_MISMATCH")
        owner, repairable, action = "CONTRACT", "NEEDS_HUMAN", "ASK_USER"
    if code == "STOP_HARNESS_OR_EXTERNAL" and _has(report, "provider", "network"):
        owner = "EXTERNAL"
    if _has(report, "UPSTREAM_EXECUTION_ERROR"):
        owner = "UPSTREAM"

    pbr = [int(x) for x in (report.get("public_passed_by_round") or [])]
    rep = _repair(report)
    snapshot = {
        "public_passed_by_round": pbr,
        "rounds_run": int(rep.get("rounds_run") or 0),
        "best_round": rep.get("best_round"),
        "stop_reason_internal": _sanitize(str(rep.get("stop_reason") or "")),
    }

    return FailureAssessmentV1(
        failure_owner=owner,
        repairability=repairable,
        reason_codes=sorted(set(reasons)),
        public_failure_fingerprint=_fingerprint(report),
        progress_snapshot=snapshot,
        allowed_feedback=[
            "public contract", "public examples", "failed public nodes",
            "sanitized error class", "remaining budgets"],
        redacted_fields=[
            "held-out inputs/expected", "oracle source", "hidden receipts",
            "signing keys", "raw private stdout", "release ledger internals"],
        recommended_action=action,
        product_stop_code=code,
    )


# ------------------------------------------------------------ §2.7 修复指标

def derive_repair_metrics(report: dict) -> dict:
    """确定性派生,不建第二份手工账。Product run 不入 Lab 模型成绩。"""
    verdict = str(report.get("verdict") or "")
    rep = _repair(report)
    rounds = int(rep.get("rounds_run") or 0)
    pbr = [int(x) for x in (report.get("public_passed_by_round") or [])]
    passed = verdict in _PASS
    initial_public_pass = bool(rounds == 1 and passed)
    rescued_at = None
    if passed and rounds > 1:
        rescued_at = rounds - 1                 # 第 N 轮通过 = 第 N-1 次修复
    return {
        "initial_public_pass": initial_public_pass,
        "repair_attempted": rounds > 1,
        "rescued_at_attempt": rescued_at,
        "rounds_used": rounds,
        "public_passed_by_round": pbr,
        "product_stop_code": product_stop_code(report),
    }
