"""CapabilityPlanV1 · 证据化能力表面 + 确定性执行路由(RFC-013,Gate 1)。

在「仓库大致可处理」(admission)与「开始写代码」之间补上正式产物:
发现了什么能力表面(带 file:line 证据与三档 confidence)、为什么支持、
走哪条实现路线(DIRECT_WRAP / AGENT_ADAPT / NONE)。

可信边界(RFC-013 §4):
  - 零模型零网络:AST 静态扫描,不执行 setup.py,不 import 目标仓代码;
  - 同 commit 同意图重复生成逐字节一致(排序键固定,canonical json);
  - LLM 只能给排序建议与草稿;`apply_llm_advice` 是唯一入口,状态/路由/
    理由码不可被建议改动 —— 违规建议整体忽略并记入 risks;
  - `confirmed=False` 的计划不得冻结、不得触发真实模型。
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from repoproof.adoption.admission.support_policy import PolicyResult
from repoproof.adoption.analysis.repository_analyzer import RepositoryReport

SCHEMA_VERSION = 1
DELIVERY_PROFILE = "cli_v2"

Confidence = Literal["HIGH", "MEDIUM", "LOW"]
SupportStatus = Literal["SUPPORTED", "REVIEW_REQUIRED", "UNSUPPORTED", "EXPERIMENTAL"]
Route = Literal["DIRECT_WRAP", "AGENT_ADAPT", "NONE"]

# service 形态信号(仓库形状判定,与 analyzer 的"外部服务客户端"不同轴)
_SERVICE_FRAMEWORKS = frozenset({
    "flask", "fastapi", "uvicorn", "django", "starlette", "aiohttp",
    "tornado", "sanic", "gunicorn"})

_DEFAULT_CONFIRMATIONS = [
    "callable locator",
    "input mapping",
    "output contract and representative examples",
]


class DetectedSurface(BaseModel):
    kind: Literal["python_callable", "cli_entry", "http_service"]
    locator: str
    signature: str = ""
    evidence: list[str] = Field(default_factory=list)
    confidence: Confidence = "LOW"
    exclusion_reason: str = ""


class CapabilityPlanV1(BaseModel):
    schema_version: int = SCHEMA_VERSION
    source: dict = Field(default_factory=dict)          # {url, commit}
    capability_goal: str = ""
    detected_surfaces: list[DetectedSurface] = Field(default_factory=list)
    support_status: SupportStatus = "REVIEW_REQUIRED"
    implementation_route: Route = "NONE"
    delivery_profile: str = DELIVERY_PROFILE
    reason_codes: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    human_confirmations: list[str] = Field(default_factory=list)
    confirmed: bool = False
    plan_sha256: str = ""

    # ------------------------------------------------------------ 指纹与落盘
    def compute_sha256(self) -> str:
        body = self.model_dump()
        body.pop("plan_sha256", None)
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def seal(self) -> CapabilityPlanV1:
        self.plan_sha256 = self.compute_sha256()
        return self


# ------------------------------------------------------ AST surface 检测器

def _iter_py_files(root: Path) -> list[Path]:
    out = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        parts = rel.parts
        if any(s.startswith(".") for s in parts):
            continue
        if parts[0] in {"tests", "test", "docs", "examples", "build", "dist"}:
            continue
        if p.is_symlink():
            continue                       # symlink 不追(RFC-013 §7.1 同律)
        try:
            if p.stat().st_size > 512 * 1024:
                continue                   # 超大文件不读,不猜
        except OSError:
            continue
        out.append(p)
    return out


def _module_of(root: Path, path: Path) -> str:
    rel = path.relative_to(root)
    parts = list(rel.parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    if not parts:
        return ""
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]
    return ".".join(p for p in parts if p)


def _signature_of(fn: ast.FunctionDef) -> str:
    bits = []
    a = fn.args
    n_defaults = len(a.defaults)
    positional = list(a.posonlyargs) + list(a.args)
    n_required = len(positional) - n_defaults
    for i, arg in enumerate(positional):
        s = arg.arg
        if arg.annotation is not None:
            s += f": {ast.unparse(arg.annotation)}"
        if i >= n_required:
            s += "=…"
        bits.append(s)
    if a.vararg:
        bits.append("*" + a.vararg.arg)
    for kw in a.kwonlyargs:
        bits.append(kw.arg + "=…")
    if a.kwarg:
        bits.append("**" + a.kwarg.arg)
    ret = f" -> {ast.unparse(fn.returns)}" if fn.returns is not None else ""
    return f"({', '.join(bits)}){ret}"


def _single_required_arg(fn: ast.FunctionDef) -> bool:
    a = fn.args
    if a.vararg or a.kwarg:
        return False
    if any(kw for kw in a.kwonlyargs
           if a.kw_defaults[a.kwonlyargs.index(kw)] is None):
        return False
    positional = list(a.posonlyargs) + list(a.args)
    n_required = len(positional) - len(a.defaults)
    return n_required == 1


def detect_surfaces(root: Path, report: RepositoryReport) -> list[DetectedSurface]:
    """把 analyzer 的符号级候选升级为带签名/行号证据的 surface 清单。

    确定性:文件按排序遍历;同名符号取首个定义;输出按 (kind, locator)
    排序 —— 遍历顺序漂移不改变产物(RFC-013 §4)。
    """
    root = Path(root)
    wanted = {str(f.value) for f in report.public_api}
    found: dict[str, DetectedSurface] = {}
    for path in _iter_py_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        mod = _module_of(root, path)
        if not mod:
            continue
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name.startswith("_") or node.name not in wanted:
                continue
            locator = f"{mod}:{node.name}"
            if locator in found:
                continue
            rel = path.relative_to(root)
            single = _single_required_arg(node)
            found[locator] = DetectedSurface(
                kind="python_callable",
                locator=locator,
                signature=_signature_of(node),
                evidence=[f"{rel}:{node.lineno}"],
                confidence="HIGH" if single else "MEDIUM",
                exclusion_reason="" if single else
                "签名不是单必选参数,机械映射不成立(可走 AGENT_ADAPT)")
        del tree

    surfaces = list(found.values())
    for f in report.cli_entry_points:
        surfaces.append(DetectedSurface(
            kind="cli_entry", locator=str(f.value), signature="",
            evidence=[f.evidence] if f.evidence else [],
            confidence="MEDIUM",
            exclusion_reason="首版不做任意 CLI 直包,仅作检测信号(RFC-013 §3)"))
    svc = sorted(set(report.dependencies) & _SERVICE_FRAMEWORKS)
    if svc:
        surfaces.append(DetectedSurface(
            kind="http_service", locator=f"framework:{','.join(svc)}",
            signature="", evidence=[report.dependencies_evidence or "dependencies"],
            confidence="MEDIUM",
            exclusion_reason="service 形态属 EXPERIMENTAL(M7 未关闭)"))
    surfaces.sort(key=lambda s: (s.kind, s.locator))
    return surfaces


# ------------------------------------------------------------ 确定性路由

def _route(report: RepositoryReport, policy: PolicyResult,
           surfaces: list[DetectedSurface]) -> tuple[SupportStatus, Route, list[str]]:
    codes: list[str] = []
    # 规则 1:硬 blocker(GPU / secret / 无法 pin / 非公开)
    if policy.blockers or report.is_public.value is False:
        for b in policy.blockers:
            # 用 blocker 的特征短语精确分类:泛子串会误伤 ——
            # "GPUISH_API_KEY" 含 "GPU",secret blocker 曾被抢成
            # GPU_REQUIRED(fixture4 实测)。
            if "需要 GPU" in b:
                codes.append("GPU_REQUIRED")
            elif "环境密钥" in b:
                codes.append("SECRET_REQUIRED")
            elif "无法固定" in b:
                codes.append("UNPINNABLE")
            else:
                codes.append("ADMISSION_BLOCKED")
        if report.is_public.value is False:
            codes.append("NOT_PUBLIC")
        return "UNSUPPORTED", "NONE", sorted(set(codes))

    callables = [s for s in surfaces if s.kind == "python_callable"]
    clis = [s for s in surfaces if s.kind == "cli_entry"]
    services = [s for s in surfaces if s.kind == "http_service"]
    license_unresolved = any("许可证" in q for q in policy.questions)

    # 规则 5(前置于 2 的空判):纯 service 形态
    if services and not callables:
        return "EXPERIMENTAL", "NONE", ["SERVICE_SHAPE"]

    # 规则 2:没有可定位 python surface,或 license 未识别
    if not callables:
        codes.append("NO_PUBLIC_SURFACE")
        if clis:
            codes.append("CLI_SIGNAL_ONLY")
        if license_unresolved:
            codes.append("LICENSE_UNRESOLVED")
        return "REVIEW_REQUIRED", "NONE", sorted(set(codes))
    if license_unresolved:
        return "REVIEW_REQUIRED", "NONE", ["LICENSE_UNRESOLVED"]

    codes.append("PINNED_PUBLIC_PYTHON")
    high = [s for s in callables if s.confidence == "HIGH"]
    # 规则 3:恰一个 HIGH(单必选参数)callable → 机械映射成立
    if len(high) == 1:
        return "SUPPORTED", "DIRECT_WRAP", sorted(
            set(codes + ["SINGLE_CALLABLE_MAPPED"]))
    # 规则 4:callable 明确但需要 glue
    codes.append("CALLABLE_NEEDS_GLUE")
    if len(high) > 1:
        codes.append("AMBIGUOUS_SURFACE")
    if clis:
        codes.append("CLI_SIGNAL_ONLY")
    return "SUPPORTED", "AGENT_ADAPT", sorted(set(codes))


def build_capability_plan(root: Path, report: RepositoryReport,
                          policy: PolicyResult, *, goal: str) -> CapabilityPlanV1:
    surfaces = detect_surfaces(Path(root), report)
    status, route, codes = _route(report, policy, surfaces)
    # 规则 3 的选中标记:DIRECT_WRAP 时唯一 HIGH callable 清空排除理由
    if route == "DIRECT_WRAP":
        for s in surfaces:
            if s.kind == "python_callable" and s.confidence == "HIGH":
                s.exclusion_reason = ""
    plan = CapabilityPlanV1(
        source={"url": report.repository,
                "commit": str(report.commit.value or "")},
        capability_goal=goal,
        detected_surfaces=surfaces,
        support_status=status,
        implementation_route=route,
        reason_codes=codes,
        risks=list(report.risks),
        human_confirmations=list(_DEFAULT_CONFIRMATIONS),
        confirmed=False,
    )
    if not str(report.commit.value or ""):
        plan.reason_codes = sorted(set(plan.reason_codes + ["COMMIT_UNRESOLVED"]))
    return plan.seal()


# ------------------------------------------------- LLM 建议守卫(唯一入口)

_ADVICE_MUTABLE = frozenset({"surface_preference", "goal_summary"})


def apply_llm_advice(plan: CapabilityPlanV1, advice: dict) -> CapabilityPlanV1:
    """LLM 建议的唯一注入口:只允许排序偏好与摘要草稿。

    任何试图改 support_status / implementation_route / reason_codes /
    confirmed 的建议:整体忽略,并把这一事实记进 risks —— 建议不能把
    REVIEW_REQUIRED 变成 SUPPORTED(RFC-013 §2)。
    """
    illegal = sorted(set(advice) - _ADVICE_MUTABLE)
    if illegal:
        plan.risks = plan.risks + [
            f"LLM 建议试图修改受保护字段 {illegal} —— 已整体忽略"]
        return plan.seal()
    pref = advice.get("surface_preference")
    if isinstance(pref, list):
        order = {loc: i for i, loc in enumerate(pref)}
        plan.detected_surfaces.sort(
            key=lambda s: (order.get(s.locator, len(order)), s.kind, s.locator))
    summary = advice.get("goal_summary")
    if isinstance(summary, str) and summary.strip():
        plan.capability_goal = f"{plan.capability_goal}\n[LLM 摘要草稿] {summary.strip()}"
    return plan.seal()


# ------------------------------------------------------------ 确认与冻结门

class PlanError(RuntimeError):
    pass


def confirm_plan(plan: CapabilityPlanV1, *, acks: list[str]) -> CapabilityPlanV1:
    """人闸:逐项确认后翻 confirmed。缺一项即拒,不许部分确认。

    空确认清单同样拒:build_capability_plan 生成的计划恒带默认三项,
    清单为空只可能是手搓/剥离 —— 「没有可确认的东西」不等于「都确认
    过了」,放行它就把人闸变成真空(执行闸 assert_may_execute 重查
    同一条,双层同律)。"""
    if not plan.human_confirmations:
        raise PlanError("human_confirmations 为空 —— 没有确认项清单的"
                        "计划不具备被确认的资格")
    missing = [c for c in plan.human_confirmations if c not in acks]
    if missing:
        raise PlanError(f"未确认项:{missing} —— 计划不得冻结")
    if plan.support_status != "SUPPORTED":
        raise PlanError(
            f"support_status={plan.support_status} 不可确认执行 —— "
            "只有 SUPPORTED 计划可进入实现路线")
    plan.confirmed = True
    return plan.seal()


def assert_may_execute(plan: CapabilityPlanV1) -> None:
    """真发前的硬闸:全部语义前提在执行点**重查**,不信任上游状态。

    只查 confirmed+sha 是不够的(外部审计实证):手工构造
    `support_status=UNSUPPORTED, confirmed=true` 再重算普通 SHA 即可绕过
    —— sha 防的是「确认后被改动」,防不了「从未合法确认过」。故本闸
    把 confirm_plan 的全部前提原样重查:任何一条不满足即拒,
    UNSUPPORTED/REVIEW_REQUIRED/EXPERIMENTAL 路径保持零模型调用。"""
    if not plan.confirmed:
        raise PlanError("计划未经用户确认(confirmed=false)—— 禁止执行")
    if plan.support_status != "SUPPORTED":
        raise PlanError(
            f"support_status={plan.support_status} —— 非 SUPPORTED 计划"
            "禁止执行(confirmed 标记不构成豁免)")
    if plan.implementation_route not in ("DIRECT_WRAP", "AGENT_ADAPT"):
        raise PlanError(
            f"implementation_route={plan.implementation_route} 不是可执行"
            "路线 —— 拒绝执行")
    if not plan.human_confirmations:
        raise PlanError("human_confirmations 为空 —— 没有确认项清单的计划"
                        "不具备被确认的资格,拒绝执行")
    if plan.compute_sha256() != plan.plan_sha256:
        raise PlanError("plan_sha256 与内容不符 —— 计划被改动过,拒绝执行")


def assert_plan_matches_source(plan: CapabilityPlanV1, *, url: str,
                               commit: str) -> None:
    """plan 与 draft 上游身份绑定:拿别的仓/别的版本的计划冒充即拒。"""
    plan_commit = str((plan.source or {}).get("commit") or "")
    plan_url = str((plan.source or {}).get("url") or "")
    if plan_commit and commit and plan_commit != commit:
        raise PlanError(
            f"计划绑定的 commit({plan_commit[:12]})与 draft 上游"
            f"({str(commit)[:12]})不一致 —— 拒绝执行")
    def _norm(u: str) -> str:
        return u.rstrip("/").removesuffix(".git").lower()
    if plan_url and url and _norm(plan_url) != _norm(url):
        raise PlanError(
            f"计划绑定的仓库({plan_url})与 draft 上游({url})不一致 —— "
            "拒绝执行")
