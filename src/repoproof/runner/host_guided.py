"""宿主级 GUIDED 运行驱动(TESTPLAN-V2 Phase 1,T1+ 形态;RFC-009 §六)。

样例管线(guided_repair.py,Docker+adaptation 区)不动;本模块是宿主级
形态的对应物:agent 直接在**宿主快照树内**工作(editable_zones=host),
执行后端 = LocalWorktreeBackend(模式 L),快照/回滚 = 会话内 git。

链条(每步与 TESTPLAN 条款对应):

    HostContract 加载(冻结 YAML,sha 入 trace)
    → 保护目录指纹 pre(§4-6)
    → 会话装配:宿主快照(排除+替身,§4-5)+ PII 出口扫描必须 0 命中
      + 上游固定快照 + 公开测试入 host 树 + oracle 会话外持有(哈希守护)
    → 会话内 git S0 基线提交(快照/回滚/diff 计量的锚)
    → per-run venv **重建**(冻结 wheelhouse,PIP_NO_INDEX;预注册教训:
      venv 不可复制)+ 合成语料重建索引
    → Host Baseline Gate:pytest 全量不达基线 → BLOCKED 零预算(§4-3)
    → guided ≤max_rounds 轮(RepairLoop 编排;公开测试+宿主回归每轮全量,
      失败→FailurePacket;劣化→git 回滚到最佳)
    → 冻结适配 = git diff S0..best(patch 预算核查)
    → 独立验证:隐藏 oracle(会话外路径)/宿主回归(不降于基线)/Policy
      (oracle+上游+公开测试三树不变、因果链、token/patch 预算)
    → 全过 → clean_adoption 重放:全新会话 + git apply + **从修改后的
      requirements.txt 重建 venv**(依赖必须被声明,否则重放如实失败)
    → Completion Gate 判定 → 保护目录指纹 post 对账
    → benchmarks/v2/runs.jsonl 记账(§9;BLOCKED 也记)。

循环永不宣布成功;最终结论只出自 Completion Gate。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from repoproof.adoption.repair.failure_packet import FailurePacket, build_failure_packets
from repoproof.adoption.repair.repair_budget import RepairBudget
from repoproof.adoption.repair.repair_loop import RepairLoop, RoundResult


def host_score(r: RoundResult) -> list[float]:
    """宿主任务排序:**不含连续 diff 项**(2026-08-09 用户决策,run -211400
    实证:"同分取小 diff"把脚手架中间态当退步回滚,销毁两轮进度)。
    diff 大小只在完全同分时经 RepairLoop 的先到先得(F8)决定最终快照;
    回滚触发另由 run_round 的硬信号退步判据控制。

    2026-08-13(LESSONS #37)补一位**二元合规**项:`fatal_violations` 为空
    (即 patch 未超限、无不可解析钉版)。位置刻意排在通过数**之后**——
    它只做平局裁决,不许拿合规去换测试进度(那正是 -211400 的老病)。

    不补这一位就会自相矛盾:#33 的 H3 逼着循环为"修剪超限 patch"多跑一轮,
    而修剪轮与超重轮通过数相同、score 逐位相等 → 判平局 → "先到先得"
    选中超重的那轮 → 终局政策闸以同一个数字击杀。实录 order-57:
    round-2 12/12 但 2682 行、round-3 12/12 且 325 行,best 选了 round-2,
    盖棺 `adaptation lines 2682 > max_patch_lines 1800`。**循环做完了修剪,
    又把成果扔了。**
    """
    return [
        1.0 if r.collected_ok else 0.0,
        1.0 if r.policy_violations == 0 else 0.0,
        1.0 if r.regression_failed == 0 else 0.0,
        float(r.passed),
        float(r.passed),
        1.0 if not r.fatal_violations else 0.0,
        1.0 if r.within_budget else 0.0,
    ]


def hard_signals(*, collected_ok: bool, policy_violations: int,
                 regression_failed: int, passed: int) -> tuple:
    """真退步判据的硬信号元组(可比较):收集/策略/回归/通过数。"""
    return (collected_ok, policy_violations == 0, regression_failed == 0, passed)


def obs_cap() -> int | None:
    """观察限流阈值(修订④,2026-08-10):默认 8000 字符(~2k tokens)。

    证据:deepseek 三发每轮 460-540k 读入的主因是整文件观察随全历史
    重发平方放大(E1 跨任务同画像,满足 §38.2 重复证据);gpt-5.6 定向
    读取 19 调用 451k 即通,证明该难度下限流不构成信息瓶颈。全模型
    统一、预算不变。消融/调参:REPOPROOF_OBS_CAP(0=关闭)。"""
    import os

    raw = os.environ.get("REPOPROOF_OBS_CAP", "").strip()
    if raw:
        v = int(raw)
        return v if v > 0 else None
    return 8000


def call_timeout_s() -> float | None:
    """单模型调用超时(修订⑤,2026-08-10):默认 300s。

    证据:T2v2 order-13——provider 降速时段一次不返回的 API 调用把
    runner 冻结 20+ 分钟,wall 预算只在调用间隙有检查点 → 被单点挂死
    架空,只能人工终止(INFRA_ABORTED)。litellm 超时异常走既有重试/
    崩溃报告路径,挂死变快败。消融/调参:REPOPROOF_CALL_TIMEOUT_S
    ("0"/空 = 关闭)。全模型统一,预算不变。"""
    import os

    raw = os.environ.get("REPOPROOF_CALL_TIMEOUT_S", "300").strip()
    if not raw or raw == "0":
        return None
    return float(raw)


def collect_nested_meter(run_dir: Path) -> dict | None:
    """嵌套 runtime_browser_agent 计量汇总(增强③,2026-08-11 用户批准)。

    证据:T3 首轮预注册承诺"嵌套双计量分列入账"(源 §19),但 fake
    `/_meter` 计数器活在会话进程内,run 结束随会话销毁,四发全部缺数。
    机制:harness 对**自己发起**的公开面/oracle/replay pytest 注入
    RP_METER_DIR/RP_METER_TAG,任务包 fixture(T3v2 起)把计数原子落盘
    到 run_dir/nested_meter/,此处按 tag 聚合;agent 自跑的套件不注入、
    不计入。无文件 → None(入账 UNKNOWN,绝不写 0 冒充——§9 纪律)。
    """
    d = run_dir / "nested_meter"
    if not d.is_dir():
        return None
    by_phase: dict[str, int] = {}
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            by_phase[str(data.get("tag", "untagged"))] = (
                by_phase.get(str(data.get("tag", "untagged")), 0)
                + int(data.get("requests", 0)))
        except (OSError, ValueError):
            continue
    if not by_phase:
        return None
    return {"total_requests": sum(by_phase.values()), "by_phase": by_phase}


def append_oracle_log(run_dir: Path, stdout: str, exit_code: int) -> None:
    """oracle stdout 全文归档(修订⑥,2026-08-10):追加式单日志。

    证据:T2 的 h5/h1 断言层取证两次被迫用 bundle diff 现场重建——
    bundle 只存 junit 计数不存 stdout,失败断言原文无处可查。capability
    与 replay 两次调用共用一个日志,哨兵密钥为合成值无泄漏面。"""
    with (run_dir / "oracle_stdout.log").open("a", encoding="utf-8") as f:
        f.write(f"\n===== oracle run @{time.strftime('%Y-%m-%dT%H:%M:%S')} "
                f"exit={exit_code} =====\n{stdout}\n")


def replay_eligible(cap, reg, pol) -> bool:
    """clean replay 准入 = 能力/回归/策略三绿;额度标记不参与
    (终轮撞线与成功可共存——耗尽的职责是约束 agent,不是取消验证)。"""
    return bool(cap and reg and pol and cap.passed and reg.passed and pol.passed)
from repoproof.agents.provider_gate import PreflightResult, ProviderConfig
from repoproof.domain.models import (
    AdaptationManifest,
    Budgets,
    VerificationResult,
    sha256_bytes,
    sha256_file,
)
from repoproof.execution.local_worktree_backend import LocalWorktreeBackend
from repoproof.harness.host_guard import (
    HostGuardError,
    bench_root_strays,
    is_protected,
    snapshot_protected,
    verify_protected_unchanged,
)
from repoproof.harness import postflight
from repoproof.harness.host_snapshot import prepare_host_snapshot, scan_for_pii
from repoproof.harness.oracle_guard import hash_tree, make_read_only, trees_equal
from repoproof.harness.policy import OUT_OF_WORKSPACE
from repoproof.harness.trace import verify_chain
from repoproof.persistence.bench_records import append_run
from repoproof.persistence.run_store import FileRunStore
from repoproof.runner.guided_repair import (
    SCOPE_MARKER,
    RepairRoundRecord,
    extract_scope_change,
    render_packets,
)
from repoproof.verification import completion_gate
from repoproof.verification.junit import parse_junit_xml
from repoproof.verification.verifiers import (
    REPLAY_MODE_CLEAN,
    parse_pytest,
    policy_result,
    replay_result,
)

_ROUND_HEADER = (
    "\n\n==== GUIDED REPAIR ROUND {idx}/{max_rounds} ====\n"
    "This is a bounded repair round on the SAME host working tree (the best\n"
    "state so far has been restored if an earlier round regressed; a ROLLBACK\n"
    "packet below explains any such restore). Address the failure packets\n"
    "below; they summarise the PUBLIC acceptance tests, the host regression\n"
    "suite, and any policy/budget/dependency violations that the final\n"
    "acceptance gate WILL enforce — an all-green test run still fails\n"
    "acceptance while such violations remain. If — and only if — the task\n"
    "cannot proceed without a scope change (new large dependency, network\n"
    "access, changing success criteria, touching forbidden paths), print one\n"
    "line starting with `{marker}` followed by the reason, then submit.\n"
    "Never invent test results.\n"
)


# --------------------------------------------------------------- 冻结契约
class HostInfo(BaseModel):
    repo: str
    commit: str
    copy_path: str
    baseline_manifest: str = "HOST_BASELINE_MANIFEST.json"
    regression_command: list[str]
    regression_baseline: str = ""


class HostSourceRepo(BaseModel):
    url: str
    resolved_commit: str
    distribution: str
    import_module: str
    license: str = ""


class HostRequirement(BaseModel):
    id: str
    text: str


class HostCapability(BaseModel):
    statement: str
    requirements: list[HostRequirement]


class HostConstraints(BaseModel):
    editable_zones: list[str] = Field(default_factory=lambda: ["."])
    forbidden: list[str] = Field(default_factory=list)
    network_at_test_time: bool = False


class HostBudgets(BaseModel):
    """semantics="total":calls/commands/tokens 为全 run 上限(v1);
    semantics="per_round":上述三类**每轮重置**(2026-08-09 用户决定,
    动机=总额语义下首轮烧光额度、修复轮空转)。patch/wall 恒为全 run。"""

    semantics: str = "total"
    max_rounds: int
    max_model_calls: int
    max_commands: int
    max_patch_files: int
    max_patch_lines: int
    max_wall_time_minutes: int
    max_input_tokens_total: int
    max_output_tokens_total: int

    @property
    def per_round(self) -> bool:
        return self.semantics == "per_round"

    def as_budgets(self) -> Budgets:
        """映射到既有 Budgets 模型(policy/token 复用的公共语言)。"""
        return Budgets(
            max_agent_steps=self.max_model_calls,
            max_wall_time_minutes=self.max_wall_time_minutes,
            max_patch_files=self.max_patch_files,
            max_patch_lines=self.max_patch_lines,
            max_input_tokens_total=self.max_input_tokens_total,
            max_output_tokens_total=self.max_output_tokens_total,
        )


class HostAcceptance(BaseModel):
    public_test_command: list[str]
    hidden_oracle_command: list[str]


class HostContract(BaseModel):
    """宿主级任务契约(benchmarks/v2/tasks/*/contract.yaml,冻结对象)。"""

    task_id: str
    task_version: str
    kind: str
    host: HostInfo
    source_repo: HostSourceRepo
    capability: HostCapability
    constraints: HostConstraints = HostConstraints()
    budgets: HostBudgets
    acceptance: HostAcceptance
    task_shape: dict = Field(default_factory=dict)
    failure_taxonomy_expected: list[str] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> tuple["HostContract", str]:
        raw = Path(path).read_bytes()
        data = yaml.safe_load(raw)
        contract = cls.model_validate(data)
        if contract.kind != "host_integrated":
            raise ValueError(f"kind 必须是 host_integrated,得到 {contract.kind!r}")
        return contract, sha256_bytes(raw)


class HostRunError(RuntimeError):
    pass


# 依赖可复现性(2026-08-12,LESSONS #31)。冻结环境里 pip 只从本地轮仓解析,
# 而**最终验收从 requirements.txt 干净重建**——这两条都写在给 agent 的提示里。
# 适配若声明了轮仓解析不到的钉版(典型:`browser-use==0.13.7` 指向 PyPI,而
# 它只以源码形式躺在 ../upstream),会话内能跑、重建装不上 = 经典"在我机器上
# 能跑"。此前这类失败被一律标成 `replay infrastructure failure(wheelhouse
# 不全?)`——**harness 替模型认领了错**,使真实的模型缺陷看起来像机器故障。
_UNRESOLVED_DIST_RE = re.compile(
    r"(?:No matching distribution found for|"
    r"Could not find a version that satisfies the requirement)\s+"
    r"([A-Za-z0-9][A-Za-z0-9._-]*)")

DEPENDENCY_NOT_REPRODUCIBLE = "DEPENDENCY_NOT_REPRODUCIBLE"


def _norm_dist(name: str) -> str:
    """PEP 503 归一:大小写与 -_. 等价(`Browser_Use` == `browser-use`)。"""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirement_dists(text: str) -> frozenset[str]:
    """requirements.txt → 分发名集合(PEP 503 归一);跳过注释与 `-e`/`-r` 行。"""
    names = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if m:
            names.add(_norm_dist(m.group(1)))
    return frozenset(names)


def added_unresolvable_dists(pip_output: str, baseline: frozenset[str]) -> list[str]:
    """pip 报错里解析不到、**且不在基线里**的分发名(排序)。

    空列表有两种含义,调用方都当作"非 agent 缺陷":①没解析失败;②失败的
    分发本来就在基线 requirements.txt 里 —— 那是轮仓不全,harness 自己的锅。
    """
    unresolved = {_norm_dist(d) for d in _UNRESOLVED_DIST_RE.findall(pip_output)}
    return sorted(d for d in unresolved if d not in baseline)


# pip 的**第二种**离线死法(2026-08-13,LESSONS #38):版本冲突。
# 与"找不到分发"完全不同的措辞,order-59 实录:
#   Cannot install requests==2.32.5 and requests>=2.31.0 because these
#   package versions have conflicting dependencies. / ResolutionImpossible
_CONFLICT_RE = re.compile(
    r"Cannot install (.+?) because these package versions have conflicting",
    re.IGNORECASE | re.DOTALL)


def conflicting_dists(pip_output: str) -> list[str]:
    """从 pip 冲突报告里剥出参与冲突的分发名(PEP 503 归一,去重保序)。"""
    out: list[str] = []
    for m in _CONFLICT_RE.finditer(pip_output):
        for tok in re.split(r"\s+and\s+|,", m.group(1)):
            name = re.split(r"[=<>!~\[ ]", tok.strip(), maxsplit=1)[0].strip()
            if name:
                out.append(_norm_dist(name))
    return list(dict.fromkeys(out))


def added_problem_dists(pip_output: str, baseline: frozenset[str]) -> list[str]:
    """两种死法合一:解析不到 + 版本冲突,均只报**适配新增**的分发。

    基线里本就有的分发出问题 = 轮仓/宿主自身的事(harness);新增的 = agent。
    """
    dists = added_unresolvable_dists(pip_output, baseline)
    if dists:
        return dists
    return [d for d in conflicting_dists(pip_output) if d not in baseline]


class DependencyNotReproducible(HostRunError):
    """适配声明了在冻结离线环境中解析不到的依赖 —— **归因于 agent,不是 harness**。

    与之相对:若解析不到的分发本来就在基线 requirements.txt 里,那才是轮仓
    确实不全(harness 侧),仍抛 HostRunError。
    """

    def __init__(self, dists: list[str], detail: str) -> None:
        self.dists = dists
        super().__init__(detail)


# ---- 轮内约束反馈(2026-08-12,LESSONS #33:约束只筛不教) ----
# 实录:最新任务版上 5 发真实模型失败,全部倒在"提示里披露过、循环里
# 却从不反馈"的约束上——061522 全绿+patch 2630>1800、181550 全绿+46 文件
# >25、030156/054108 全绿+钉版离线解析不到,四发都在第 1 轮全绿即停,
# 剩余轮次全部浪费,盖棺时被最终政策/重放击杀;060126 的 12/12 轮因 1 条
# 被拒命令被静默回滚,agent 三轮不知因果。公开测试在教,其余约束全在伏击。
POLICY_VIOLATION = "POLICY_VIOLATION"
PATCH_BUDGET_EXCEEDED = "PATCH_BUDGET_EXCEEDED"


def round_violation_report(
    *,
    denied_delta: int,
    tampered: list[str],
    patch_files: int,
    patch_lines: int,
    max_patch_files: int,
    max_patch_lines: int,
    unresolvable_dists: list[str],
    dependency_probe_failed: bool = False,
    dependency_detail: str = "",
    upstream_touched: list[str] | None = None,
    answer_key_hits: list[str] | None = None,
) -> tuple[list[FailurePacket], list[str], int]:
    """本轮违规 → (结构化失败包, 致命违规名单, 计入排序的违规数)。

    **排序只对齐终局判据,其余一律教**(LESSONS #35,批 6 实证):
    - `tampered`(改公开测试)计入排序 —— 终局 PolicyVerifier 以
      `PUBLIC_TESTS_TAMPERED` 树哈希比对直接击杀,排序必须同向;
    - `denied`(命令被拦下、**零执行**)**不计入排序** —— 终局
      `policy_result` 根本不数它。旧写法让循环拿着一把比终局更严的尺子,
      把终局本会接受的最好一轮扔掉:order-53 round-3 公开 21/23 仅因一条
      `xargs … sh -c` 调试命令被拦,整轮回滚,最终交付 round-2 的 3/23;
      060126 round-2 的 12/12 同因被弃(n=2)。它改走教学面(违规包)。
    - patch 超限/依赖不可解析同样不计入排序,改进 fatal 名单 —— 全绿
      超重轮是最有价值的修剪底座,滚掉等于逼 agent 重做;fatal 阻止
      "全绿即停",把剩余轮次留给修剪,因为终局会以同一判据击杀。
    denied 仍取**本轮增量**:跨轮累计会让一轮违规永久拖累后续所有轮
    (060126 实录:round-3 自身零违规却背着 round-2 的 1)。
    """
    packets: list[FailurePacket] = []
    fatal: list[str] = []
    if denied_delta > 0:
        packets.append(FailurePacket(
            type=POLICY_VIOLATION,
            summary=f"{denied_delta} command(s) were DENIED by the policy guard this round",
            expected="only commands inside the allowed workspace and toolset",
            actual=f"{denied_delta} denied command(s); this round ranks below any clean round",
            suggestion="被拒的命令不会执行、也不会拖累本轮排序,但白白吃掉命令"
                       "预算——换成允许的等价做法(避开 sh -c 等被拦的构造)"))
    if tampered:
        packets.append(FailurePacket(
            type="SCOPE_EXCEEDED",
            summary=f"public acceptance surface was modified: {', '.join(sorted(tampered)[:5])}",
            affected_files=sorted(tampered),
            expected="./public_tests and ./fixtures unchanged",
            actual=f"{len(tampered)} file(s) under public_tests/ or fixtures/ "
                   "differ from baseline",
            suggestion="恢复原样——公开测试与 fixtures 都是验收量具(隐藏验收也"
                       "import fixtures),改动的轮会被回滚、不计成绩;需要不同的"
                       "假模型行为请走 scope-change 请求,别改量具"))
    if patch_files > max_patch_files:
        fatal.append("patch_files")
        packets.append(FailurePacket(
            type=PATCH_BUDGET_EXCEEDED,
            summary=f"adaptation files {patch_files} > max_patch_files {max_patch_files}",
            expected=f"<= {max_patch_files} changed files (whole run)",
            actual=f"{patch_files} changed files",
            suggestion="最终政策闸会以同一数字拒绝——收缩适配范围:合并新文件、"
                       "撤销与需求无关的改动;不要为凑数删除必要实现"))
    if patch_lines > max_patch_lines:
        fatal.append("patch_lines")
        packets.append(FailurePacket(
            type=PATCH_BUDGET_EXCEEDED,
            summary=f"adaptation lines {patch_lines} > max_patch_lines {max_patch_lines}",
            expected=f"<= {max_patch_lines} diff lines (whole run)",
            actual=f"{patch_lines} diff lines",
            suggestion="最终政策闸会以同一数字拒绝——精简 diff:删掉调试残留、"
                       "重复代码与无关重排,保住已通过的测试"))
    keys = list(answer_key_hits or [])
    if keys:
        fatal.append("out_of_workspace")
        packets.append(FailurePacket(
            type="OUT_OF_WORKSPACE_ACCESS",
            summary=f"referenced protected benchmark material outside the workspace: "
                    f"{', '.join(keys[:5])}",
            expected="every path you touch stays inside the host workspace "
                     "(./ and the read-only ../upstream)",
            actual=f"{len(keys)} denied reference(s) to the benchmark tree, "
                   "reference solutions, or hidden acceptance material",
            suggestion="这些命令**没有执行**,但终局会以 OUT_OF_WORKSPACE_ACCESS "
                       "直接击杀这一发——答案树、负控、隐藏验收都不是你的工作面。"
                       "只用 ./ 与只读的 ../upstream 解题"))
    touched = list(upstream_touched or [])
    if touched:
        fatal.append("upstream")
        packets.append(FailurePacket(
            type="SCOPE_EXCEEDED",
            summary=f"pinned upstream tree modified: {', '.join(touched[:5])}"
                    + (f" (+{len(touched) - 5} more)" if len(touched) > 5 else ""),
            affected_files=touched,
            expected="../upstream stays byte-identical to the pinned snapshot",
            actual=f"{len(touched)} path(s) differ from the pinned snapshot",
            suggestion="终局 PolicyVerifier 以树哈希比对直接击杀——把改动移出"
                       "上游快照,改在宿主适配区内解决(需要上游行为不同时,"
                       "在适配层包一层,别改钉版源码)"))

    # 探针只要失败就必须成包 —— **哪怕认不出错误形状**(LESSONS #38)。
    # 反例 order-59:探针 exit_code=1 但归因正则只认"找不到分发"、认不出
    # ResolutionImpossible,于是吐出空清单 → 该轮被当成干净 → 全绿即停 →
    # 干净重放以同一条冲突击杀。**沉默比误报危险得多。**
    if unresolvable_dists or dependency_probe_failed:
        fatal.append("dependency")
        named = ", ".join(unresolvable_dists)
        packets.append(FailurePacket(
            type=DEPENDENCY_NOT_REPRODUCIBLE,
            summary=(f"requirements.txt 在离线轮仓里装不起来:{named}" if named
                     else "requirements.txt 在离线轮仓里装不起来(pip 离线 dry-run 失败,"
                          "具体分发名无法从输出中判定)"),
            expected="every requirements.txt pin installs from the local wheelhouse",
            actual=(f"unresolvable/conflicting: {named}" if named
                    else (dependency_detail or "pip 非零退出,原文未捕获")),
            suggestion="最终验收会从 requirements.txt 离线重建环境并以同样方式失败"
                       "——移除或放宽冲突的钉版,或改用轮仓/../upstream 快照里"
                       "真实可装的形态;可自己跑 `pip install --dry-run -r "
                       "requirements.txt` 复现"))
    return packets, fatal, len(tampered) + len(touched) + len(keys)


def enforcement_input_cap(budgets: "HostBudgets") -> int:
    """执法用输入上限 = 契约值本身,**不再内移**(LESSONS #39)。

    沿革:2026-08-09 的用户决策把 per_round 的执法线内移 50k,因为当时
    只能"调用后记账、下次调用前拦",越线发生在最后一次调用上,过与不过
    取决于边界运气(run -200448 两轮各超 8%/2%)。那个决策的**意图**是
    "别让越线取决于运气",内移只是当时能想到的手段。

    order-63 证明这个手段不成立:内移 50,000,而该轮单次最大调用 51,067
    —— 拍出来的常数总会遇到比它大的调用。现在由
    `TokenBudgetedModel` 的**调用前投影**保证不越线(见该模块文档),
    意图被更严格地满足,于是这里不再收税:agent 拿到的恰是契约承诺的
    额度。**政策判据仍是契约值,一字不动。**
    """
    return budgets.max_input_tokens_total


# 公开验收面 = 公开测试 + fixtures(LESSONS #40)。fixtures 不是实现面,
# 是**量具**:公开套件 import 它,**隐藏 oracle 也 import 它**。此前只有
# public_tests 有树哈希对账,fixtures 落在 agent 可写树里、提示里也没说过
# 不许改——量具由被测者提供,结论就不独立。
PROTECTED_PUBLIC_DIRS = ("public_tests", "fixtures")


def tampered_public_surface(changed_files: object) -> list[str]:
    """改动清单 → 落在公开验收面里的那些(排序与终局同向计入)。"""
    prefixes = tuple(f"{d}/" for d in PROTECTED_PUBLIC_DIRS)
    return sorted(p for p in (changed_files or []) if str(p).startswith(prefixes))


def hash_public_surface(host_root: Path) -> dict[str, str]:
    """公开验收面的合并指纹(键名带目录前缀,免得两树同名文件互相遮蔽)。

    缺目录不是错误——T1 就没有 fixtures。"""
    out: dict[str, str] = {}
    for name in PROTECTED_PUBLIC_DIRS:
        d = Path(host_root) / name
        if d.is_dir():
            out.update({f"{name}/{rel}": h for rel, h in hash_tree(d).items()})
    return out


# ------------------------------------------------ H9(LESSONS #41)工作区封闭
# order-21 三步拿到答案:`find /` 发现 → `sed` 通读 → `cp` 整文件。
# H9-a 管"答案不在盘上",H9-b 管"引用即杀",H9-c 管"先教"。

ANSWER_KEY_SCAN_ROOTS = ("~/RepoProofBench", "~/RepoProofBench-quarantine", "/tmp")
"""H9-a 扫描根。三处都是实录里真的出现过残留的地方:
`~/RepoProofBench/_scratch_t2_positive`(T2 v1 期)、
`~/RepoProofBench-quarantine/_scratch_t2_positive`(order-21 抄的那棵)、
`/private/tmp/t2v4_direct/fixtures`(任务工程期)。"""

PROTECTED_TASK_DIRS = ("controls", "oracle", "fixtures", "public_tests")
_SESSION_DIR = "_sessions"


def reachable_answer_keys(
    task_dir: Path, roots: tuple[str, ...] = ANSWER_KEY_SCAN_ROOTS, max_depth: int = 3,
) -> list[str]:
    """H9-a:开跑前列出运行主机上**可达的答案残留**(查到即拒开)。

    残留 = 工作区之外的、任务包受保护材料(controls/oracle/fixtures/
    public_tests)的**内容副本**,或任务工程期的 `_scratch_t*` 安装树。
    会话工作区自身(`_sessions/<run_id>/…`)是**合法注入**,显式跳过 ——
    否则每一发都会拒开自己。

    **按内容比对,不按文件名**:任务包里有 `README.md`,宿主快照里也有,
    只看名字会把 `~/RepoProofBench/offerclaw-t1-fastapi-mcp/README.md`
    这类完全无辜的文件报成残留 —— 那样这道闸门会立刻被当噪声关掉。
    先比大小、撞了才哈希,免去几乎全部读盘。

    这是 H9 里**不可绕过的那一半**:H9-b 的路径检测可以被拼接/编码绕过,
    但答案不在盘上就抄不到。
    """
    by_size: dict[int, set[str]] = {}
    for name in PROTECTED_TASK_DIRS:
        d = Path(task_dir) / name
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if p.is_file():
                raw = p.read_bytes()
                by_size.setdefault(len(raw), set()).add(hashlib.sha256(raw).hexdigest())
    found: list[str] = []
    for root in roots:
        base = Path(root).expanduser()
        if not base.is_dir():
            continue
        stack = [(base, 0)]
        while stack:
            cur, depth = stack.pop()
            try:
                entries = list(cur.iterdir())
            except OSError:          # 权限/竞态:扫不到就跳过,不是残留证据
                continue
            for e in entries:
                if e.name == _SESSION_DIR:
                    continue
                if e.is_dir():
                    if e.name.startswith("_scratch_t"):
                        found.append(str(e))
                        continue     # 整棵树已判残留,不必逐文件再报
                    if depth + 1 <= max_depth:
                        stack.append((e, depth + 1))
                    continue
                try:
                    digests = by_size.get(e.stat().st_size)
                    if digests and hashlib.sha256(e.read_bytes()).hexdigest() in digests:
                        found.append(str(e))
                except OSError:          # 同上:读不到不算证据
                    continue
    return sorted(set(found))


def answer_key_access(denial_reasons: object) -> list[str]:
    """政策拒绝原因 → **引用受保护基准物路径**的那些(H9-b 击杀依据)。

    根扫描(`filesystem_root_sweep`)刻意不在此列:它只教不杀。历史 27 发
    越界里 24 发只是在找 wheelhouse,把它们判死是 #35 的反面错误。
    """
    pref = f"{OUT_OF_WORKSPACE}:"
    return sorted({str(r) for r in (denial_reasons or []) if str(r).startswith(pref)})


def round_usage(model: object, bucket: dict) -> tuple[int, int]:
    """轮内用量以**同步记账**为准(LESSONS #39 H7-d)。

    litellm 用线程池派发 success_callback,回调落地时下一轮可能已经开始
    ——上一轮末次调用的 token 会被记进下一轮的桶。而 per_round 语义下,
    终局政策比的正是"单轮最大用量":串了账就会拿别人的 token 杀这一轮,
    与 order-63 同型的伏击。

    同步记账拿不到用量时(注入的假模型、provider 沉默)才回落到桶,
    以免"我没记到"被写成 0(H7-e:不许假零、不许少报)。
    """
    if getattr(model, "seen", False):
        used_in = getattr(model, "used_in", None)
        used_out = getattr(model, "used_out", None)
        if used_in is not None and used_out is not None:
            return int(used_in), int(used_out)
    return int(bucket.get("in", 0) or 0), int(bucket.get("out", 0) or 0)


# --------------------------------------------------------------- 工具函数
def _expected_regression_passed(baseline: str) -> int:
    """'591 passed, 7 skipped, 0 failed' → 591(回归判据=不降于基线)。"""
    import re

    m = re.search(r"(\d+)\s+passed", baseline)
    return int(m.group(1)) if m else 0


def integrity_scope(project_root: Path) -> list[str]:
    """指纹对账集 = 保护目录去掉 RepoProof 自身(§4-6 主目录语义)。

    RepoProof 仍在写护栏黑名单(会话根不得落于其中),但 run 合法写
    自己的 runs/ 与 benchmarks/,对其拍指纹必然自误报。"""
    import os as _os

    from repoproof.harness.host_guard import protected_dirs

    self_norm = _os.path.realpath(str(project_root)).lower().rstrip("/")
    return [d for d in protected_dirs() if d != self_norm]


def _read_substitutes(host_copy: Path) -> dict[str, str]:
    """替身内容取自副本内文件(引导手册保证其为合成;PII 扫描兜底)。

    快照默认排除这些文件后再写入替身——直接用副本里经 591 基线锚定的
    精细替身,而非 host_snapshot 的极简默认(后者会挂档案格式测试)。"""
    from repoproof.harness.host_snapshot import DEFAULT_SUBSTITUTES

    subs: dict[str, str] = {}
    for name, fallback in DEFAULT_SUBSTITUTES.items():
        src = host_copy / name
        subs[name] = src.read_text(encoding="utf-8") if src.exists() else fallback
    return subs


def build_host_prompt(contract: HostContract, *, wheel_note: str) -> str:
    """契约 → agent 提示的唯一投影(不含任何 oracle/隐藏信息)。"""
    cap = contract.capability
    req_lines = [f"[{r.id}] {' '.join(r.text.split())}" for r in cap.requirements]
    forbidden = [f"- {' '.join(f.split())}" for f in contract.constraints.forbidden]
    b = contract.budgets
    parts = [
        "You are integrating a capability from a pinned open-source repo into a\n"
        "REAL host project (OfferClaw). You work directly inside the host tree.",
        f"GOAL\n{cap.statement.strip()}",
        "REQUIREMENTS (each is verified)\n" + "\n".join(req_lines),
        "YOUR ENVIRONMENT\n"
        "- You start in the host project root (a disposable snapshot; git is\n"
        "  available and the baseline is already committed).\n"
        "- ../upstream          read-only pinned source checkout of "
        f"{contract.source_repo.distribution} @ {contract.source_repo.resolved_commit[:12]}\n"
        "- ./public_tests       PUBLIC acceptance tests — run them yourself:\n"
        "    .venv/bin/python -m pytest public_tests/ -q\n"
        "- ./.venv              host virtualenv with all host deps preinstalled\n"
        "- ./tests              host regression suite (MUST stay green):\n"
        "    .venv/bin/python -m pytest tests/ -q\n"
        f"- pip is OFFLINE: it resolves ONLY from a local wheel index ({wheel_note}).\n"
        "  Install the target library with .venv/bin/pip install <dist>; resolve any\n"
        "  dependency conflict yourself (diagnose, then pin what you need).\n"
        "- DECLARE new dependencies in requirements.txt with working version pins:\n"
        "  final acceptance rebuilds a CLEAN environment strictly from\n"
        "  requirements.txt + your committed files; undeclared deps will fail there.\n"
        "- Command outputs beyond ~8000 chars are TRUNCATED (head+tail) with a notice.\n"
        "  Read files in targeted ranges (sed -n '120,180p' FILE, grep -n PATTERN FILE)\n"
        "  instead of dumping whole files — every char you read is re-sent on every\n"
        "  later call and burns your per-round token allowance quadratically.",
        "HARD RULES\n" + "\n".join(forbidden)
        + "\n- Do not modify ./public_tests, ./fixtures or ../upstream. The fixtures\n"
          "  are the acceptance instruments (the hidden acceptance imports them too);\n"
          "  changing them is treated exactly like changing the public tests."
        # H9-c(#33 闸门要杀的先教):终局会以 OUT_OF_WORKSPACE_ACCESS 击杀,
        # 提示就必须先说边界。历史上 27 发越界,一发也没被告知过。
        + "\n- STAY INSIDE THE WORKSPACE. Everything you need is here: ./ and the\n"
          "  read-only ../upstream. Do NOT read anything else on this machine —\n"
          "  no filesystem-wide sweeps (find / ...), and never touch the benchmark\n"
          "  tree, reference solutions or hidden acceptance material. Such commands\n"
          "  are DENIED, and referencing that material ends the run.",
        "BUDGETS\n"
        + (f"- PER ROUND (reset each round): model calls {b.max_model_calls}, "
           f"executed commands {b.max_commands}, "
           f"input/output token allowance {b.max_input_tokens_total}/{b.max_output_tokens_total}; "
           if b.per_round else
           f"- WHOLE RUN (single pool, no per-round reset): model calls {b.max_model_calls}, "
           f"executed commands {b.max_commands}, "
           f"input/output token allowance {b.max_input_tokens_total}/{b.max_output_tokens_total}; ")
        + f"patch budget: {b.max_patch_files} files / {b.max_patch_lines} lines (whole run); "
        f"wall time: {b.max_wall_time_minutes} minutes (whole run).\n"
        "Acceptance is judged AFTER you finish by additional tests you cannot see;\n"
        "there is no partial credit for claims.\n"
        "When done, submit with: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
    ]
    return "\n\n".join(parts)


class _Session:
    """一次装配好的宿主会话(主 run 与 clean replay 各一个)。"""

    def __init__(self, backend: LocalWorktreeBackend, session: str, root: Path,
                 venv_py: str) -> None:
        self.backend = backend
        self.id = session
        self.root = root
        self.venv_py = venv_py  # 会话内 venv python(相对 host 的路径)


class HostGuidedRunner:
    """宿主级 guided runner。所有 exec 走 LocalWorktreeBackend(净化环境/
    假 HOME/护栏/cwd 钉死焊在后端);oracle 路径永不进入会话与 agent 环境。"""

    def __init__(
        self,
        contract_path: Path,
        project_root: Path,
        *,
        runs_root: Path | None = None,
        wheelhouse: Path | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.contract_path = Path(contract_path)
        self.contract, self.contract_sha = HostContract.load(self.contract_path)
        self.task_dir = self.contract_path.parent
        self.host_copy = Path(self.contract.host.copy_path).expanduser().resolve()
        if is_protected(self.host_copy):
            raise HostGuardError(f"宿主副本命中受保护目录:{self.host_copy}")
        if not self.host_copy.is_dir():
            raise HostRunError(f"宿主副本不存在:{self.host_copy}")
        self.oracle_src = self.task_dir / "oracle"
        self.public_tests_src = self.task_dir / "public_tests"
        for p in (self.oracle_src, self.public_tests_src):
            if not p.is_dir():
                raise HostRunError(f"任务包目录缺失:{p}")
        self.upstream_src = (
            self.project_root / "upstream-cache"
            / f"upstream-{self.contract.source_repo.resolved_commit[:12]}"
        )
        self.wheelhouse = Path(
            wheelhouse
            or Path("~/RepoProofBench").expanduser()
            / f"wheelhouse-offerclaw-{self.contract.host.commit[:7]}"
        ).expanduser().resolve()
        self.run_id = f"{self.contract.task_id}-{time.strftime('%Y%m%d-%H%M%S')}"
        self.budgets = self.contract.budgets.as_budgets()
        self.timings: dict[str, float] = {}
        self._browser_pids_before: set[int] | None = None   # 增强①:run 起点快照
        # 先核验后建店(LESSONS #35 · F3,批 6 期间实证):建店在护栏之前
        # 会给**被拒绝的**调用也留下 runs/<task>-<ts>/ 空壳,混在真实证据里
        # 像一发夭折的官方 run;跑测试套件时更会直接污染证据树。
        self._verify_static_resources()
        self.store = FileRunStore((runs_root or self.project_root / "runs") / self.run_id)

    # ------------------------------------------------------------ 静态核验
    def _verify_static_resources(self) -> None:
        if not self.upstream_src.is_dir():
            raise HostRunError(
                f"上游固定快照缺失:{self.upstream_src}(引导期先克隆并 detach)")
        head = subprocess.run(  # noqa: S603 — 固定 argv,只读查询
            ["git", "-C", str(self.upstream_src), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False)
        if head.stdout.strip() != self.contract.source_repo.resolved_commit:
            raise HostRunError(
                f"上游快照 HEAD {head.stdout.strip()[:12]} != 契约 pinned "
                f"{self.contract.source_repo.resolved_commit[:12]}")
        if not self.wheelhouse.is_dir():
            raise HostRunError(f"冻结 wheelhouse 缺失:{self.wheelhouse}")
        manifest = self.wheelhouse / "wheelhouse_manifest.json"
        if not manifest.is_file():
            raise HostRunError(f"wheelhouse manifest 缺失:{manifest}")
        self.env_baseline_hash = json.loads(
            manifest.read_text(encoding="utf-8"))["env_baseline_hash"]

    # ------------------------------------------------------------ 会话装配
    def _git(self, s: _Session, *args: str, timeout_s: int = 120):
        return s.backend.exec(
            s.id,
            ["git", "-c", "user.name=repoproof-harness",
             "-c", "user.email=harness@repoproof.invalid",
             "-c", "commit.gpgsign=false", *args],
            timeout_s=timeout_s, workdir="host")

    def _assemble(self, backend: LocalWorktreeBackend, label: str) -> _Session:
        """装配一个会话:快照+替身+PII 扫描+上游+公开测试+S0 提交。"""
        ev = self.store.append_event
        session = backend.start(name_prefix=f"rp-host-{label}", env={
            "PIP_NO_INDEX": "1",
            "PIP_FIND_LINKS": str(self.wheelhouse),
            # A 类只读缓存共享(TESTPLAN §4-3):共享 + 离线开关;假 HOME 不变
            "MODELSCOPE_CACHE": str(Path("~/.cache/modelscope").expanduser()),
            "PYTHONHASHSEED": "0",
        })
        root = backend.session_root(session)
        snap = prepare_host_snapshot(
            self.host_copy, root / "host",
            substitutes=_read_substitutes(self.host_copy))
        pii = scan_for_pii(root / "host")
        if pii:
            backend.destroy(session)
            raise HostRunError(f"PII 出口扫描命中 {len(pii)} 条,拒绝开跑:{pii[:3]}")
        shutil.copytree(self.upstream_src, root / "upstream", symlinks=False,
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(self.public_tests_src, root / "host" / "public_tests",
                        ignore=shutil.ignore_patterns("__pycache__"))
        # T3 批 1 实证修复:任务包 fixtures 是公开测试面的一部分(公开
        # 套件/oracle 都 import 它),必须与 public_tests 一同注入会话——
        # 否则零适配态公开套件即收集失败,正控验证环境≠会话环境。
        fixtures_src = self.task_dir / "fixtures"
        if fixtures_src.is_dir():
            shutil.copytree(fixtures_src, root / "host" / "fixtures",
                            dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__"))
        s = _Session(backend, session, root, ".venv/bin/python")
        r = self._git(s, "add", "-A")
        if r.exit_code != 0:
            backend.destroy(session)
            raise HostRunError(f"git add 失败:{r.stderr.decode(errors='replace')[-300:]}")
        r = self._git(s, "commit", "-q", "--allow-empty", "-m", "rp-host S0 baseline")
        if r.exit_code != 0:
            backend.destroy(session)
            raise HostRunError(f"S0 提交失败:{r.stderr.decode(errors='replace')[-300:]}")
        head = self._git(s, "rev-parse", "HEAD")
        s.base_commit = head.stdout.decode().strip()  # type: ignore[attr-defined]
        ev(f"host.session_assembled.{label}", actor="harness", payload={
            "files": snap["files"], "excluded": len(snap["excluded"]),
            "substituted": snap["substituted"], "pii_hits": 0,
            "base_commit": s.base_commit,
        })
        return s

    def _baseline_dists(self) -> frozenset[str]:
        """**未适配**宿主副本 requirements.txt 里的分发名(PEP 503 归一)。

        归因基准:在这份名单里的解析失败 = 轮仓不全(harness);不在的 =
        适配自己加的钉版(agent)。读的是宿主副本原件,不是会话里被改过的那份。
        """
        if getattr(self, "_baseline_dists_cache", None) is None:
            req = self.host_copy / "requirements.txt"
            self._baseline_dists_cache = parse_requirement_dists(
                req.read_text(encoding="utf-8", errors="replace") if req.is_file() else "")
        return self._baseline_dists_cache

    def _build_env_in_session(self, s: _Session, *, timeout_s: int = 900) -> dict:
        """per-run venv 重建(预注册教训:绝不复制)+ 合成语料建索引。"""
        t0 = time.monotonic()
        r1 = s.backend.exec(s.id, ["python3", "-m", "venv", ".venv"],
                            timeout_s=300, workdir="host")
        if r1.exit_code != 0:
            raise HostRunError(f"venv 创建失败:{r1.stderr.decode(errors='replace')[-300:]}")
        r2 = s.backend.exec(
            s.id, [".venv/bin/pip", "install", "-q", "-r", "requirements.txt"],
            timeout_s=timeout_s, workdir="host")
        if r2.exit_code != 0:
            full = (r2.stdout + r2.stderr).decode(errors="replace")
            tail = full[-500:]
            # 归因:解析不到的分发是**适配新增的**(agent 侧缺陷),还是本来就在
            # 基线里(轮仓确实不全,harness 侧)?两者判然不同,不许混为一谈。
            # 判据读**全文**不读尾巴——截断会把归因变成"报错够不够靠后"。
            # 两种死法都归因(#38):找不到分发 + 版本冲突。order-59 实录:
            # 冲突里的 requests==2.32.5 是适配自己加的,旧写法认不出这条
            # 措辞,于是又一次由 harness 替模型认领(#31 换皮复发)。
            added = added_problem_dists(full, self._baseline_dists())
            if added:
                raise DependencyNotReproducible(
                    added,
                    f"适配声明了冻结环境装不起来的依赖:{', '.join(added)}"
                    f"(轮仓 {self.wheelhouse.name} 无此分发,且不在基线 "
                    f"requirements.txt 中)。会话内可用不等于可复现——最终验收"
                    f"从 requirements.txt 干净重建。原始 pip 输出:{tail}")
            raise HostRunError("宿主依赖安装失败(wheelhouse 不全?):" + tail)
        venv_s = round(time.monotonic() - t0, 1)
        t1 = time.monotonic()
        r3 = s.backend.exec(s.id, [".venv/bin/python", "rag_ingest.py"],
                            timeout_s=600, workdir="host")
        if r3.exit_code != 0:
            raise HostRunError(
                "合成语料建索引失败:" + (r3.stdout + r3.stderr).decode(errors="replace")[-500:])
        return {"venv_s": venv_s, "ingest_s": round(time.monotonic() - t1, 1)}

    # ------------------------------------------------------------ 基线与测量
    def _pytest_counts(self, s: _Session, xml_name: str, stdout: str) -> dict:
        """结构化计数:junitxml 优先(pytest 9 的 -q 失败态不打总结行,
        正则解析会漏计——首次冒烟实测),正则仅作兜底。"""
        xml_path = s.root / xml_name
        junit = parse_junit_xml(xml_path.read_bytes() if xml_path.exists() else None)
        if junit.get("junit_present") and not junit.get("junit_parse_error"):
            nodes = junit.get("nodes", [])
            failed = sorted(n["node_id"] for n in nodes if n["outcome"] in ("failed", "error"))
            passed = sum(1 for n in nodes if n["outcome"] == "passed")
            return {"passed_checks": passed, "failed_checks": len(failed),
                    "total_checks": len(nodes), "failed_tests": failed}
        return {k: v for k, v in parse_pytest(stdout).items()}

    def _run_regression(self, s: _Session, *, timeout_s: int = 900) -> dict:
        cmd = self.contract.host.regression_command
        argv = ([s.venv_py, *cmd[1:]] if cmd and cmd[0] == "python"
                else [s.venv_py, "-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider"])
        xml_name = "rp_reg.xml"
        (s.root / xml_name).unlink(missing_ok=True)
        argv = [*argv, "--junitxml", f"../{xml_name}"]
        res = s.backend.exec(s.id, argv, timeout_s=timeout_s, workdir="host")
        stdout = res.stdout.decode(errors="replace")
        return {"exit_code": res.exit_code, "stdout": stdout,
                **self._pytest_counts(s, xml_name, stdout)}

    def _meter_env(self, tag: str) -> dict[str, str]:
        """嵌套计量注入(增强③):只对 harness 自己发起的套件生效。"""
        return {"RP_METER_DIR": str(self.store.run_dir / "nested_meter"),
                "RP_METER_TAG": tag}

    def _run_public(self, s: _Session, *, timeout_s: int = 600,
                    meter_tag: str = "public") -> dict:
        xml_path = s.root / "rp_public.xml"
        if xml_path.exists():
            xml_path.unlink()
        res = s.backend.exec(
            s.id,
            [s.venv_py, "-m", "pytest", "public_tests/", "-q", "-p", "no:cacheprovider",
             "--junitxml", "../rp_public.xml"],
            timeout_s=timeout_s, workdir="host", env=self._meter_env(meter_tag))
        junit = parse_junit_xml(xml_path.read_bytes() if xml_path.exists() else None)
        junit["pytest_exit"] = res.exit_code
        junit["stdout_tail"] = res.stdout.decode(errors="replace")[-600:]
        return junit

    def _run_oracle(self, s: _Session, oracle_snap: Path, *, timeout_s: int = 600,
                    meter_tag: str = "oracle_capability") -> dict:
        """隐藏验收:oracle 目录在会话外(run_dir 下),路径只在 harness 手里。"""
        xml_name = "rp_oracle.xml"
        (s.root / xml_name).unlink(missing_ok=True)
        res = s.backend.exec(
            s.id,
            [s.venv_py, "-m", "pytest", str(oracle_snap), "-q", "-p", "no:cacheprovider",
             "--junitxml", f"../{xml_name}"],
            timeout_s=timeout_s, workdir="host",
            env={"PYTHONPATH": str(s.root / "host"),
                 "OFFERCLAW_HOST_ROOT": str(s.root / "host"),
                 **self._meter_env(meter_tag)})
        stdout = res.stdout.decode(errors="replace")
        append_oracle_log(self.store.run_dir, stdout, res.exit_code)   # 修订⑥
        return {"exit_code": res.exit_code, "stdout": stdout,
                **self._pytest_counts(s, xml_name, stdout)}

    def _baseline_gate(self, s: _Session) -> tuple[bool, dict]:
        """Host Baseline Gate(§4-3):不达基线 → BLOCKED 零预算。"""
        report: dict = {}
        reg = self._run_regression(s)
        expected = _expected_regression_passed(self.contract.host.regression_baseline)
        report["pytest"] = {
            "exit_code": reg["exit_code"], "passed": reg["passed_checks"],
            "failed": reg["failed_checks"], "expected_passed": expected,
        }
        ok = reg["exit_code"] == 0 and reg["passed_checks"] >= expected
        r = s.backend.exec(s.id, [s.venv_py, "verify_pipeline.py"],
                           timeout_s=300, workdir="host")
        report["verify_pipeline.py"] = {"exit_code": r.exit_code,
                                        "tail": r.stdout.decode(errors="replace")[-200:]}
        ok = ok and r.exit_code == 0
        # verify_docs 的基线判据 = "0 处未围栏裸露" 不退化(Manifest
        # known_deviations:chunks 交叉核对 112 vs 3538 因合成语料重建,
        # 其非零退出码是已知预期差异,不作门禁)——实测本判据由首次冒烟
        # BLOCKED 校准(2026-08-09)。
        rd = s.backend.exec(s.id, [s.venv_py, "verify_docs.py"],
                            timeout_s=300, workdir="host")
        rd_out = rd.stdout.decode(errors="replace")
        docs_ok = rd.exit_code == 0 or "0 处未围栏" in rd_out
        report["verify_docs.py"] = {"exit_code": rd.exit_code, "bare_ok": docs_ok,
                                    "tail": rd_out[-200:]}
        ok = ok and docs_ok
        rdoc = s.backend.exec(s.id, [s.venv_py, "doctor.py"], timeout_s=300, workdir="host")
        report["doctor"] = {"exit_code": rdoc.exit_code,
                            "tail": rdoc.stdout.decode(errors="replace")[-300:],
                            "note": "已知预期差异(chunks 口径/合成密钥 WARN),不作门禁"}
        return ok, report

    # ------------------------------------------------------------ diff 计量
    def _diff_stats(self, s: _Session, base: str, head: str = "HEAD") -> dict:
        num = self._git(s, "diff", "--numstat", f"{base}..{head}")
        files: list[str] = []
        lines = 0
        for row in num.stdout.decode(errors="replace").splitlines():
            parts = row.split("\t")
            if len(parts) != 3:
                continue
            a, d, path = parts
            files.append(path)
            lines += (int(a) if a.isdigit() else 0) + (int(d) if d.isdigit() else 0)
        return {"files": files, "total_files": len(files), "total_lines": lines}

    # ------------------------------------------------------------------ 主流程
    def run(
        self,
        provider: ProviderConfig | None,
        preflight: PreflightResult | None,
        *,
        model_factory: Callable[[dict], object] | None = None,
        run_order: int | str = "UNKNOWN",
        run_index: int | str = "UNKNOWN",
        batch: str = "UNKNOWN",
        keep_session: bool = False,
    ) -> dict:
        import os as _os

        ev = self.store.append_event
        t0 = time.monotonic()
        try:  # 增强①:run 起点浏览器 PID 快照(收尾清扫的差集基准)
            self._browser_pids_before = postflight.browser_pids()
        except Exception:  # noqa: BLE001 — 快照失败只关闭清扫,不阻断 run
            self._browser_pids_before = None
        contract = self.contract
        b = contract.budgets
        model_name = provider.model_name if provider else "fake-scripted"
        ev("run.start", actor="runner", payload={
            "run_id": self.run_id, "mode": "host-guided-repair",
            "task_id": contract.task_id, "max_rounds": b.max_rounds,
            "execution_backend": "local-worktree",
            "env_baseline_hash": self.env_baseline_hash,
            "model": model_name,
            "provider_config_sha256": preflight.provider_config_sha256 if preflight else None,
        })
        ev("contract.frozen", actor="harness",
           payload={"task_id": contract.task_id, "sha256": self.contract_sha})

        integrity_before = snapshot_protected(integrity_scope(self.project_root))
        # 会话根不得落在保护目录内(RepoProof 自身也是保护目录),
        # 放 RepoProofBench 工作区;产物/trace 仍在 runs/<id>/ 下。
        sessions_root = Path("~/RepoProofBench/_sessions").expanduser() / self.run_id
        backend = LocalWorktreeBackend(sessions_root=sessions_root)
        oracle_snap = self.store.run_dir / "oracle_snapshot"
        shutil.copytree(self.oracle_src, oracle_snap,
                        ignore=shutil.ignore_patterns("__pycache__"))
        make_read_only(oracle_snap)
        oracle_before = hash_tree(oracle_snap)
        ev("oracle.hashed", actor="harness", payload={"files": len(oracle_before)})

        verdict_record: dict = {}
        missing_external: list[str] = []
        budget_exhausted: str | None = None
        agent_metrics: dict = {"model_calls": 0, "commands": 0, "denied": 0,
                               "exit_status": None, "cost": "UNKNOWN"}
        repair_summary: dict = {}
        records: list[RepairRoundRecord] = []
        public_by_round: list[int] = []
        regression_by_round: list[int] = []
        adaptation_manifest: AdaptationManifest | None = None
        cap = reg = pol = rep = None
        first_outcome: dict = {}
        s: _Session | None = None
        upstream_before: dict = {}
        public_before: dict = {}
        # H9-b(LESSONS #41):全会话累计的越界引用。一轮碰过答案树,后续
        # 轮次也洗不白 —— 这一发整体不再是干净测量。
        out_of_workspace: set[str] = set()

        try:
            # 环境卫生门(批 1 教训):bench 根白名单外条目 → 零预算 BLOCKED。
            strays = bench_root_strays()
            ev("host.bench_hygiene", actor="harness",
               payload={"ok": not strays, "strays": strays[:10]})
            if strays:
                missing_external.append(f"BENCH_ROOT_CONTAMINATED:{strays[:5]}")
                raise _BenchContaminated(strays)

            s = self._assemble(backend, "agent")
            upstream_before = hash_tree(s.root / "upstream")
            public_before = hash_public_surface(s.root / "host")
            self.timings["env_build"] = 0.0
            t_env = time.monotonic()
            env_report = self._build_env_in_session(s)
            self.timings["env_build"] = round(time.monotonic() - t_env, 1)
            ev("host.env_built", actor="harness", payload=env_report)

            t_gate = time.monotonic()
            gate_ok, gate_report = self._baseline_gate(s)
            self.timings["baseline_gate_s"] = round(time.monotonic() - t_gate, 1)
            ev("host.baseline_gate", actor="harness",
               payload={"ok": gate_ok, **gate_report})
            if not gate_ok:
                missing_external.append("HOST_BASELINE_UNHEALTHY(会话内基线不达标,零预算)")
                raise _BaselineUnhealthy(gate_report)

            # ---------------- agent 阶段 ----------------
            from repoproof.agents.backend import MiniSWEBackend
            from repoproof.agents.repoproof_env import RepoProofEnvironment

            env = RepoProofEnvironment(
                backend=backend,           # 同形接口:session 字符串当 container
                container=s.id,
                store=self.store,
                command_timeout_s=Budgets().max_command_minutes * 60,
                command_budget=b.max_commands,          # 全 run 共享(跨轮)
                budget_visibility=False,
                model_call_limit=b.max_model_calls,
                wall_limit_s=b.max_wall_time_minutes * 60,
                default_cwd="host",
                obs_char_cap=obs_cap(),                 # 修订④:观察限流
            )
            token_totals = {"in": 0, "out": 0, "seen": False}   # 累计(记账)
            make_budget_model = None
            if model_factory is None:
                assert provider is not None and preflight is not None
                _os.environ.setdefault("MSWEA_COST_TRACKING", "ignore_errors")
                _os.environ["OPENAI_API_KEY"] = provider.api_key
                _os.environ["OPENAI_API_BASE"] = provider.api_base
                _os.environ["OPENAI_BASE_URL"] = provider.api_base
                import litellm as _litellm
                from minisweagent.models.litellm_model import LitellmModel
                from minisweagent.models.litellm_textbased_model import LitellmTextbasedModel

                from repoproof.agents.token_budget import TokenBudgetedModel

                # 这个钩子是**异步**的(litellm 用 executor.submit 派发),
                # 只用于 run 级汇总。轮桶不再由它写:回调落地时下一轮可能
                # 已经开始,会把上一轮的 token 记到下一轮头上(LESSONS #39
                # H7-d)。执法与轮桶都走 TokenBudgetedModel 的同步记账。
                def _usage_cb(kwargs, completion_response, start_time, end_time):  # noqa: ANN001
                    usage = getattr(completion_response, "usage", None)
                    if usage:
                        token_totals["seen"] = True
                        token_totals["in"] += getattr(usage, "prompt_tokens", 0) or 0
                        token_totals["out"] += getattr(usage, "completion_tokens", 0) or 0

                _litellm.success_callback = [_usage_cb]
                model_cls = (LitellmTextbasedModel
                             if preflight.action_protocol == "textbased" else LitellmModel)
                mkwargs = {"temperature": 0} if preflight.temperature == "0" else {}
                _cto = call_timeout_s()          # 修订⑤:单调用超时
                if _cto is not None:
                    mkwargs["timeout"] = _cto
                inner_model = model_cls(model_name=f"openai/{provider.model_name}",
                                        model_kwargs=mkwargs)

                def make_budget_model(totals_dict: dict) -> TokenBudgetedModel:
                    return TokenBudgetedModel(
                        inner=inner_model,
                        totals=totals_dict,
                        max_input_tokens=enforcement_input_cap(b),
                        max_output_tokens=b.max_output_tokens_total,
                        on_exhausted=lambda payload: ev("budget.exhausted", actor="harness",
                                                        payload=payload),
                    )

                model = make_budget_model(token_totals)   # total 语义:全程一个额度
            else:
                model = model_factory(token_totals)

            base_prompt = build_host_prompt(
                contract, wheel_note=f"wheelhouse {self.wheelhouse.name}")
            prompt_sha = sha256_bytes(base_prompt.encode())
            ev("agent.prompt", actor="harness",
               payload={"sha256": prompt_sha, "chars": len(base_prompt)})

            repair_dir = self.store.run_dir / "repair"
            repair_dir.mkdir(exist_ok=True)
            metrics_acc = {"model_calls": 0, "commands": 0, "denied": 0}
            last_exit: dict = {"status": None, "exhausted": None}
            per_round_usage: list[tuple[int, int]] = []
            expected_reg = _expected_regression_passed(contract.host.regression_baseline)
            t_agent = time.monotonic()

            best_state = {"hard": None, "commit": None}
            prev_state = {"hard": None}

            def run_round(idx: int, packets: list[FailurePacket],
                          best_snapshot: str | None) -> RoundResult:
                t_round = time.monotonic()
                ev("repair.round.start", actor="harness",
                   payload={"round": idx, "packets": len(packets)})
                # 恢复策略(v2 修订,用户决策):默认**在上一轮现场继续**
                # (同分脚手架=平行探索,保留);仅当上一轮硬信号(收集/
                # 策略/回归/通过数)相对最佳**严格退步**才恢复最佳提交。
                # RepairLoop 传入的 best_snapshot 不再直接驱动恢复。
                # venv/chroma 属 gitignore 恒不回滚(L 模式单调,重放兜底)。
                if (best_state["commit"] and prev_state["hard"] is not None
                        and best_state["hard"] is not None
                        and prev_state["hard"] < best_state["hard"]):
                    cur = self._git(s, "rev-parse", "HEAD").stdout.decode().strip()
                    if cur != best_state["commit"]:
                        self._git(s, "reset", "--hard", best_state["commit"])
                        self._git(s, "clean", "-fd")
                        ev("repair.restored_best", actor="harness",
                           payload={"round": idx, "snapshot": best_state["commit"][:12],
                                    "reason": "hard_signal_regression"})
                base_hash = self._git(s, "rev-parse", "HEAD").stdout.decode().strip()

                if b.per_round:
                    # 每轮重置:calls/commands/tokens 各自满额起步(v2 语义)
                    round_totals = {"in": 0, "out": 0, "seen": False}
                    round_model = (make_budget_model(round_totals)
                                   if make_budget_model else model)
                    env.commands_used = 0
                    env.command_budget = b.max_commands
                    step_limit = b.max_model_calls
                else:
                    round_totals = token_totals
                    round_model = model
                    step_limit = b.max_model_calls - metrics_acc["model_calls"]
                    if step_limit <= 0:
                        return RoundResult(
                            adapter_snapshot=base_hash, passed=0,
                            failed_nodes=["budget::model_calls"],
                            failure_details={}, diff_lines=0,
                            tokens_used=token_totals["in"] + token_totals["out"],
                            commands_used=0, collected_ok=False, within_budget=False)

                round_prompt = (
                    base_prompt
                    + _ROUND_HEADER.format(idx=idx, max_rounds=b.max_rounds,
                                           marker=SCOPE_MARKER)
                    + render_packets(packets)
                )
                mback = MiniSWEBackend(
                    model=round_model, env=env,
                    step_limit=step_limit,
                    cost_limit=Budgets().monetary_soft_cap_usd,
                    output_path=self.store.run_dir / f"trajectory_round{idx}.json",
                )
                # H1(LESSONS #33):env.denied_count 是会话生命周期累计值;
                # 排序只许看**本轮增量**,否则一轮违规拖累后续所有轮。
                denied_before = env.denied_count
                result = mback.run_task(round_prompt)
                last_exit["status"] = result.exit_status
                last_exit["exhausted"] = getattr(round_model, "exhausted", None)
                metrics_acc["model_calls"] += result.n_model_calls
                if b.per_round:
                    metrics_acc["commands"] += env.commands_used
                    # 轮桶归同步记账所有(LESSONS #39 H7-d),落回桶里让
                    # record.json 与终局政策共用同一份数,不再各读各的。
                    r_in, r_out = round_usage(round_model, round_totals)
                    round_totals.update(
                        {"in": r_in, "out": r_out,
                         "seen": bool(round_totals["seen"]
                                      or getattr(round_model, "seen", False))})
                    per_round_usage.append((r_in, r_out))
                else:
                    metrics_acc["commands"] = env.commands_used
                metrics_acc["denied"] = env.denied_count

                self._git(s, "add", "-A")
                self._git(s, "commit", "-q", "--allow-empty", "-m", f"rp-host round {idx}")
                head = self._git(s, "rev-parse", "HEAD").stdout.decode().strip()
                diff = self._diff_stats(s, s.base_commit, head)  # type: ignore[attr-defined]
                tampered = tampered_public_surface(diff["files"])
                denied_round = env.denied_count - denied_before
                # H9-b(LESSONS #41):引用受保护基准物路径 —— 命令已被政策
                # 拦下(零执行),但**这一发不再是干净测量**,终局据此击杀。
                # 取全会话累计:一轮碰过,后续轮次也洗不白。
                answer_keys = answer_key_access(getattr(env, "policy_denials", []))
                if answer_keys:
                    out_of_workspace.update(answer_keys)

                # H2 依赖探针(LESSONS #33):适配动过 requirements.txt 就在
                # 会话内离线 dry-run 一次——会话 env 自带 PIP_NO_INDEX +
                # PIP_FIND_LINKS,练的就是干净重放最终要用的那台解析器。
                # 终局 PolicyVerifier 会比对 upstream 树哈希;轮内同样比一次,
                # 否则这条判据又是一个"只在盖棺时开口"的伏击(#33 的枚举收口)。
                upstream_touched: list[str] = []
                if upstream_before:
                    now = hash_tree(s.root / "upstream")
                    upstream_touched = sorted(
                        p for p in (now.keys() | upstream_before.keys())
                        if now.get(p) != upstream_before.get(p))

                unresolvable: list[str] = []
                probe_failed = False
                probe_detail = ""
                if "requirements.txt" in diff["files"]:
                    probe = s.backend.exec(
                        s.id, [s.venv_py, "-m", "pip", "install", "--dry-run",
                               "-q", "-r", "requirements.txt"],
                        timeout_s=240, workdir="host")
                    if probe.exit_code != 0:
                        probe_out = (probe.stdout.decode(errors="replace")
                                     + probe.stderr.decode(errors="replace"))
                        # 两种死法都认;认不出也照样报(#38:沉默最危险)
                        unresolvable = added_problem_dists(
                            probe_out, self._baseline_dists())
                        probe_failed = True
                        probe_detail = " ".join(probe_out.split())[-300:]
                    ev("repair.dependency_probe", actor="harness", payload={
                        "round": idx, "exit_code": probe.exit_code,
                        "unresolvable_dists": unresolvable,
                        "probe_failed": probe_failed})

                junit = self._run_public(s, meter_tag=f"public_round{idx}")
                nodes = junit.get("nodes", [])
                collected_ok = bool(junit.get("junit_present")) and not junit.get("junit_parse_error")
                failed_nodes = [n["node_id"] for n in nodes if n["outcome"] != "passed"]
                details = {n["node_id"]: n.get("message", "") for n in nodes
                           if n["outcome"] != "passed"}
                passed = sum(1 for n in nodes if n["outcome"] == "passed")

                regr = self._run_regression(s)
                reg_failed = regr["failed_checks"] + max(0, expected_reg - regr["passed_checks"])
                if reg_failed:
                    failed_nodes.append("host_regression::suite")
                    details["host_regression::suite"] = (
                        f"regression {regr['passed_checks']}/{expected_reg} passed, "
                        f"{regr['failed_checks']} failed")

                scope_req = extract_scope_change(result.submission)
                violation_packets, fatal, pol_count = round_violation_report(
                    denied_delta=denied_round,
                    tampered=tampered,
                    patch_files=len(diff["files"]),
                    patch_lines=diff["total_lines"],
                    max_patch_files=b.max_patch_files,
                    max_patch_lines=b.max_patch_lines,
                    unresolvable_dists=unresolvable,
                    dependency_probe_failed=probe_failed,
                    dependency_detail=probe_detail,
                    upstream_touched=upstream_touched,
                    answer_key_hits=answer_keys,
                )
                rr = RoundResult(
                    adapter_snapshot=head,
                    passed=passed,
                    failed_nodes=failed_nodes,
                    failure_details=details,
                    diff_lines=diff["total_lines"],
                    tokens_used=(round_totals["in"] + round_totals["out"] if b.per_round
                                 else token_totals["in"] + token_totals["out"]),
                    commands_used=result.commands_used,
                    scope_change_request=scope_req,
                    collected_ok=collected_ok,
                    policy_violations=pol_count,
                    regression_failed=reg_failed,
                    within_budget=result.exit_status not in
                    ("TokenBudgetExhausted", "LimitsExceeded"),
                    violation_packets=violation_packets,
                    fatal_violations=fatal,
                )
                hard = hard_signals(collected_ok=collected_ok,
                                    policy_violations=rr.policy_violations,
                                    regression_failed=reg_failed, passed=passed)
                prev_state["hard"] = hard
                if best_state["hard"] is None or hard > best_state["hard"]:
                    best_state["hard"] = hard
                    best_state["commit"] = head

                packets_next = build_failure_packets(failed_nodes, details)
                record = RepairRoundRecord(
                    round_index=idx,
                    base_snapshot_hash=base_hash,
                    adaptation_root=head,
                    changed_files=diff["files"],
                    diff_lines=diff["total_lines"],
                    public_passed=passed,
                    public_failed=len([n for n in failed_nodes
                                       if not n.startswith("host_regression")]),
                    regression_passed=regr["passed_checks"],
                    regression_failed=reg_failed,
                    policy_violations=pol_count,
                    model_calls=result.n_model_calls,
                    commands=result.commands_used,
                    tokens_in=(round_totals["in"] if round_totals["seen"] else "UNKNOWN"),
                    tokens_out=(round_totals["out"] if round_totals["seen"] else "UNKNOWN"),
                    wall_time_s=round(time.monotonic() - t_round, 1),
                    failure_packets=[p.to_dict()
                                     for p in (*packets_next, *violation_packets)],
                    scope_change_request=scope_req,
                    score=host_score(rr),
                )
                records.append(record)
                public_by_round.append(passed)
                regression_by_round.append(regr["passed_checks"])
                rd = repair_dir / f"round-{idx}"
                rd.mkdir(exist_ok=True)
                (rd / "record.json").write_text(
                    json.dumps(record.to_dict(), ensure_ascii=False, indent=2,
                               sort_keys=True), encoding="utf-8")
                ev("repair.round.end", actor="harness", payload={
                    "round": idx, "public_passed": passed,
                    "public_failed": len(failed_nodes),
                    "regression_passed": regr["passed_checks"],
                    "tampered_public_tests": tampered,
                    "denied_this_round": denied_round,
                    "fatal_violations": fatal,
                    "exit_status": result.exit_status,
                    "scope_change": bool(scope_req)})
                return rr

            # 真正的全局硬墙在 env(命令数)与 TokenBudgetedModel(token);
            # RoundResult 报的是累计值,RepairLoop 内部再求和会重复计数,
            # 故此处上限放大 max_rounds 倍只作兜底,不作首要执法者。
            loop = RepairLoop(
                run_round,
                budget=RepairBudget(
                    max_rounds=b.max_rounds,
                    max_tokens=(b.max_input_tokens_total + b.max_output_tokens_total)
                    * b.max_rounds,
                    max_commands=b.max_commands * b.max_rounds,
                    # H3 级联修复(LESSONS #33):diff 同样只作兜底——按旧写法
                    # (=max_patch_lines),超重的全绿轮刚被 fatal 拦下不许停,
                    # 就会在这里以 budget_exhausted 断轮,修剪机会照样丢。
                    # 首要执法者是 fatal 违规包 + 最终政策闸。
                    max_diff_lines=b.max_patch_lines * b.max_rounds),
                score_fn=host_score,
            )
            outcome = loop.run()
            cur = self._git(s, "rev-parse", "HEAD").stdout.decode().strip()
            if cur != outcome.final_adapter:
                self._git(s, "reset", "--hard", outcome.final_adapter)
                self._git(s, "clean", "-fd")
            for r in records:
                r.selected_as_best = (r.round_index == outcome.best_round)
                (repair_dir / f"round-{r.round_index}" / "record.json").write_text(
                    json.dumps(r.to_dict(), ensure_ascii=False, indent=2,
                               sort_keys=True), encoding="utf-8")
            repair_summary = {
                "rounds_run": outcome.rounds_run,
                "best_round": outcome.best_round,
                "best_public_passed": outcome.best_passed,
                "stop_reason": outcome.stop_reason,
                "rolled_back_rounds": outcome.rolled_back_rounds,
                "pending_scope_change": outcome.pending_scope_change,
            }
            (repair_dir / "summary.json").write_text(
                json.dumps(repair_summary, ensure_ascii=False, indent=2,
                           sort_keys=True), encoding="utf-8")
            ev("repair.summary", actor="harness", payload=repair_summary)
            agent_metrics = {
                **metrics_acc,
                "exit_status": last_exit["status"],
                "cost": "UNKNOWN",
                "input_tokens": token_totals["in"] if token_totals["seen"] else "UNKNOWN",
                "output_tokens": token_totals["out"] if token_totals["seen"] else "UNKNOWN",
                "agent_wall_s": round(time.monotonic() - t_agent, 1),
            }
            if model_factory is None:
                import litellm as _litellm
                _litellm.success_callback = []
                for traj in self.store.run_dir.glob("trajectory_round*.json"):
                    assert provider.api_key.encode() not in traj.read_bytes(), \
                        "API key leaked into trajectory"
            # per_round:早先轮次的耗尽会被下一轮满额"复活",只有**终轮**
            # 耗尽才把整个 run 标为额度收束;total:沿用全程单额度语义。
            final_ex = (last_exit.get("exhausted") if b.per_round
                        else getattr(model, "exhausted", None))
            if final_ex:
                scope = "final_round" if b.per_round else "total"
                budget_exhausted = (f"{final_ex['kind']} "
                                    f"({final_ex['used']} >= {final_ex['limit']}, {scope})")
            ev("agent.end", actor="harness", payload=agent_metrics)

            # ---------------- scope change 停点 ----------------
            if repair_summary.get("pending_scope_change"):
                verdict_record = {
                    "verdict": "BLOCKED", "state": "SCOPE_CHANGE_PENDING_USER",
                    "scope_change_request": repair_summary["pending_scope_change"]}
                return self._finish(
                    verdict_record, integrity_before, backend, s, keep_session,
                    agent_metrics=agent_metrics, repair_summary=repair_summary,
                    records=records, public_by_round=public_by_round,
                    regression_by_round=regression_by_round,
                    run_order=run_order, run_index=run_index, batch=batch, model_name=model_name,
                    preflight=preflight, budget_exhausted=budget_exhausted,
                    gate_reasons=["AI 请求范围变更,已暂停等待用户决定:"
                                  + str(repair_summary["pending_scope_change"])],
                    t0=t0)

            # ---------------- 冻结适配(git diff S0..best)----------------
            diff_final = self._diff_stats(s, s.base_commit)  # type: ignore[attr-defined]
            patch = self._git(s, "diff", "--binary",
                              f"{s.base_commit}..HEAD",  # type: ignore[attr-defined]
                              timeout_s=120)
            patch_bytes = patch.stdout
            (self.store.run_dir / "adaptation.patch").write_bytes(patch_bytes)
            adaptation_manifest = AdaptationManifest(
                files=[{"path": p} for p in diff_final["files"]],
                total_files=diff_final["total_files"],
                total_lines=diff_final["total_lines"],
                tree_root_sha256=sha256_bytes(patch_bytes),
                frozen=True)
            self.store.save_json("adaptation_manifest.json", adaptation_manifest.model_dump())
            ev("adaptation.frozen", actor="harness", payload={
                "files": adaptation_manifest.total_files,
                "lines": adaptation_manifest.total_lines,
                "root": adaptation_manifest.tree_root_sha256})

            # ---------------- 独立验证 ----------------
            t_verify = time.monotonic()
            cap_run = self._run_oracle(s, oracle_snap)
            cap = VerificationResult(
                verifier="CapabilityVerifier",
                passed=cap_run["exit_code"] == 0,
                detail=(f"passed_checks={cap_run['passed_checks']}, "
                        f"failed_checks={cap_run['failed_checks']}, "
                        f"total_checks={cap_run['total_checks']}"
                        + ("" if cap_run["exit_code"] == 0 else
                           " — failing: " + ", ".join(
                               t.split("::")[-1] for t in cap_run["failed_tests"][:12]))),
                extra={"exit_code": cap_run["exit_code"], **{
                    k: cap_run[k] for k in
                    ("passed_checks", "failed_checks", "total_checks", "failed_tests")}})
            reg_run = self._run_regression(s)
            reg_ok = reg_run["exit_code"] == 0 and reg_run["passed_checks"] >= expected_reg
            reg = VerificationResult(
                verifier="HostRegressionVerifier",
                passed=reg_ok,
                detail=(f"passed_checks={reg_run['passed_checks']}, "
                        f"failed_checks={reg_run['failed_checks']}, "
                        f"baseline={expected_reg}"
                        + ("" if reg_ok else " — host regression below baseline")),
                extra={"exit_code": reg_run["exit_code"],
                       "passed_checks": reg_run["passed_checks"],
                       "failed_tests": reg_run["failed_tests"]})

            # per_round 语义下,受约束的量是"单轮最大用量"而非累计
            # (累计对比每轮上限会假报违规)。usage 未上报时保持 UNKNOWN。
            if b.per_round and per_round_usage and token_totals["seen"]:
                tb_in: int | str = max(u[0] for u in per_round_usage)
                tb_out: int | str = max(u[1] for u in per_round_usage)
            else:
                tb_in = agent_metrics.get("input_tokens")
                tb_out = agent_metrics.get("output_tokens")
            pol = policy_result(
                token_budget={
                    "input_used": tb_in,
                    "output_used": tb_out,
                    "input_limit": b.max_input_tokens_total,
                    "output_limit": b.max_output_tokens_total,
                },
                trace_path=self.store.trace_path,
                oracle_before=oracle_before,
                oracle_after=hash_tree(oracle_snap),
                upstream_before=upstream_before,
                upstream_after=hash_tree(s.root / "upstream"),
                adaptation_manifest=adaptation_manifest,
                adaptation_recheck_ok=(
                    self._git(s, "rev-parse", "HEAD").stdout.decode().strip()
                    == outcome.final_adapter),
                adaptation_recheck_detail="session HEAD == frozen best commit",
                budgets=self.budgets,
                evidence=[])
            # 公开验收面 = public_tests + fixtures(LESSONS #40):隐藏 oracle
            # 的假模型量具就在 fixtures 里,被测者改得动它,结论就不独立。
            pub_ok, pub_diff = trees_equal(
                public_before, hash_public_surface(s.root / "host"))
            if not pub_ok:
                pol = VerificationResult(
                    verifier="PolicyVerifier", passed=False,
                    detail=pol.detail + f"; PUBLIC_SURFACE_TAMPERED: {pub_diff[:5]}",
                    evidence=pol.evidence,
                    extra={**pol.extra, "public_tests_tampered": pub_diff[:10]})
            # H9-b:引用受保护基准物路径 → 击杀。命令确实被拦下了(零执行),
            # 但检测器不是牢笼(#41 诚实边界):既然这一发伸过手,就不能再
            # 把它当作对模型能力的干净测量。反例是 order-21 —— 它伸手成功了。
            if out_of_workspace:
                hits = sorted(out_of_workspace)
                pol = VerificationResult(
                    verifier="PolicyVerifier", passed=False,
                    detail=pol.detail + f"; OUT_OF_WORKSPACE_ACCESS: {hits[:5]}",
                    evidence=pol.evidence,
                    extra={**pol.extra, "out_of_workspace_access": hits[:10]})
            self.timings["verification_s"] = round(time.monotonic() - t_verify, 1)

            first_outcome = {
                "capability_exit": cap_run["exit_code"],
                "capability_failed": sorted(cap_run["failed_tests"]),
                "regression_exit": reg_run["exit_code"],
                "probe_normalized_sha": sha256_bytes(json.dumps({
                    "cap_failed": sorted(cap_run["failed_tests"]),
                    "cap_passed": cap_run["passed_checks"],
                    "reg_passed": reg_run["passed_checks"],
                }, sort_keys=True).encode()),
            }

            # ---------------- clean replay(全过才有资格)----------------
            # replay 准入 = 静态三绿,**与额度标记无关**(v2 修订③,run
            # -232629 实证:每轮语义下"终轮撞执法线"与"任务成功"常态共存,
            # v1 的"耗尽即跳过"会让读入型模型的 PASS 结构性不可达;源方案
            # §3-14 规定最终 PASS 必须过 clean replay → 三绿必须尝试)。
            if replay_eligible(cap, reg, pol):
                if not keep_session:
                    backend.destroy(s.id)
                    s = None
                t_replay = time.monotonic()
                try:
                    replay_outcome = self._clean_replay(backend, patch_bytes, oracle_snap,
                                                        expected_reg)
                    rep = replay_result(first=first_outcome, replay=replay_outcome,
                                        mode=REPLAY_MODE_CLEAN,
                                        evidence=[first_outcome["probe_normalized_sha"]])
                    rep.extra["replay_model_calls"] = 0
                    rep.extra["replay_agent_commands"] = 0
                except DependencyNotReproducible as exc:
                    # 归因于 agent:适配自己声明了装不回来的钉版。**不是**
                    # 基础设施故障——这正是干净重放要抓的"在我机器上能跑"。
                    rep = VerificationResult(
                        verifier="ReplayVerifier", passed=False,
                        detail=f"{DEPENDENCY_NOT_REPRODUCIBLE}: {exc}",
                        extra={"mode": REPLAY_MODE_CLEAN,
                               "attribution": "agent",
                               "failure_type": DEPENDENCY_NOT_REPRODUCIBLE,
                               "unresolvable_dists": exc.dists})
                except Exception as exc:  # noqa: BLE001
                    rep = VerificationResult(
                        verifier="ReplayVerifier", passed=False,
                        detail=f"replay infrastructure failure: {exc}",
                        extra={"mode": REPLAY_MODE_CLEAN,
                               "attribution": "harness"})
                self.timings["replay_s"] = round(time.monotonic() - t_replay, 1)

        except _BenchContaminated as exc:
            verdict_record = {"verdict": "BLOCKED", "state": "BENCH_ROOT_CONTAMINATED",
                              "strays": exc.strays}
            return self._finish(
                verdict_record, integrity_before, backend, s, keep_session,
                agent_metrics=agent_metrics, repair_summary={}, records=[],
                public_by_round=[], regression_by_round=[],
                run_order=run_order, run_index=run_index, batch=batch, model_name=model_name,
                preflight=preflight, budget_exhausted=None,
                gate_reasons=[f"BENCH_ROOT_CONTAMINATED:{exc.strays[:5]}(零预算清场后重跑)"],
                t0=t0)
        except _BaselineUnhealthy as exc:
            verdict_record = {"verdict": "BLOCKED", "state": "HOST_BASELINE_UNHEALTHY",
                              "baseline_report": exc.report}
            return self._finish(
                verdict_record, integrity_before, backend, s, keep_session,
                agent_metrics=agent_metrics, repair_summary={}, records=[],
                public_by_round=[], regression_by_round=[],
                run_order=run_order, run_index=run_index, batch=batch, model_name=model_name,
                preflight=preflight, budget_exhausted=None,
                gate_reasons=["HOST_BASELINE_UNHEALTHY:宿主基线不达标,未消耗任何模型预算"],
                t0=t0)
        finally:
            if s is not None and not keep_session:
                backend.destroy(s.id)

        # ---------------- Completion Gate ----------------
        for r in (cap, reg, pol) + ((rep,) if rep else ()):
            self.store.save_verification(r)
            ev("verification.result", actor=r.verifier,
               payload={"passed": r.passed, "detail": r.detail})
        gate = completion_gate.decide(
            capability=cap, regression=reg, policy=pol, replay=rep,
            adaptation=adaptation_manifest,
            missing_external=missing_external, budget_exhausted=budget_exhausted)
        ev("gate.verdict", actor="completion-gate", payload=gate.model_dump(mode="json"))
        verdict_record = {
            "verdict": gate.verdict.value,
            "gate_reasons": gate.reasons,
            "capability": cap.detail if cap else "not_run",
            "regression": reg.detail if reg else "not_run",
            "policy": pol.detail if pol else "not_run",
            "replay": rep.detail if rep else None,
        }
        return self._finish(
            verdict_record, integrity_before, backend, None, keep_session,
            agent_metrics=agent_metrics, repair_summary=repair_summary,
            records=records, public_by_round=public_by_round,
            regression_by_round=regression_by_round,
            run_order=run_order, run_index=run_index, batch=batch, model_name=model_name,
            preflight=preflight, budget_exhausted=budget_exhausted,
            gate_reasons=gate.reasons, t0=t0,
            adaptation_manifest=adaptation_manifest,
            capability_vr=cap, regression_vr=reg, policy_vr=pol, replay_vr=rep,
            first_outcome=first_outcome)

    # ------------------------------------------------------------ clean replay
    def _clean_replay(self, backend: LocalWorktreeBackend, patch_bytes: bytes,
                      oracle_snap: Path, expected_reg: int) -> dict:
        """全新会话 + git apply + 从(补丁后的)requirements 重建 venv。

        依赖必须被声明进 requirements.txt——重放环境只从声明重建,
        未声明的运行期 pip install 在这里如实失败(源 §24 Dependency Delta)。"""
        ev = self.store.append_event
        s = self._assemble(backend, "replay")
        try:
            (s.root / "adaptation.patch").write_bytes(patch_bytes)
            if patch_bytes.strip():
                r = s.backend.exec(s.id, ["git", "apply", "../adaptation.patch"],
                                   timeout_s=120, workdir="host")
                if r.exit_code != 0:
                    raise HostRunError(
                        "重放 git apply 失败:" + r.stderr.decode(errors="replace")[-300:])
            self._git(s, "add", "-A")
            self._git(s, "commit", "-q", "--allow-empty", "-m", "rp-host replay apply")
            self._build_env_in_session(s)
            cap_run = self._run_oracle(s, oracle_snap, meter_tag="oracle_replay")
            reg_run = self._run_regression(s)
            outcome = {
                "capability_exit": cap_run["exit_code"],
                "capability_failed": sorted(cap_run["failed_tests"]),
                "regression_exit": reg_run["exit_code"],
                "probe_normalized_sha": sha256_bytes(json.dumps({
                    "cap_failed": sorted(cap_run["failed_tests"]),
                    "cap_passed": cap_run["passed_checks"],
                    "reg_passed": reg_run["passed_checks"],
                }, sort_keys=True).encode()),
            }
            ev("replay.done", actor="harness", payload={
                "capability_exit": cap_run["exit_code"],
                "regression_passed": reg_run["passed_checks"],
                "expected_regression": expected_reg})
            return outcome
        finally:
            backend.destroy(s.id)

    # ------------------------------------------------------------ 收尾与记账
    def _finish(
        self, verdict_record: dict, integrity_before: dict,
        backend: LocalWorktreeBackend, s: _Session | None, keep_session: bool,
        *, agent_metrics: dict, repair_summary: dict,
        records: list[RepairRoundRecord], public_by_round: list[int],
        regression_by_round: list[int], run_order, run_index, batch: str,
        model_name: str,
        preflight: PreflightResult | None, budget_exhausted: str | None,
        gate_reasons: list[str], t0: float,
        adaptation_manifest: AdaptationManifest | None = None,
        capability_vr: VerificationResult | None = None,
        regression_vr: VerificationResult | None = None,
        policy_vr: VerificationResult | None = None,
        replay_vr: VerificationResult | None = None,
        first_outcome: dict | None = None,
    ) -> dict:
        ev = self.store.append_event
        if s is not None and not keep_session:
            backend.destroy(s.id)
        if not keep_session:
            backend.destroy_all()
            shutil.rmtree(backend.sessions_root, ignore_errors=True)
        # 增强①(T3 批 1,4/4 发 Chrome 残留证据):postflight 进程清扫。
        # 时序钉死:在会话销毁之后、一切测量(oracle h6 PID 差集/replay)
        # 完成之后;keep_session 调试模式不清扫。判别与安全边界见
        # harness/postflight.py。清扫失败如实入账,不改判定。
        sweep_report: dict | None = None
        if (not keep_session and postflight.enabled()
                and self._browser_pids_before is not None):
            try:
                sweep_report = postflight.sweep(self._browser_pids_before)
                ev("postflight.process_sweep", actor="harness", payload={
                    "killed": len(sweep_report["killed"]),
                    "skipped_new": len(sweep_report["skipped_new"]),
                    "leftover_new_pids": sweep_report["leftover_new_pids"]})
            except Exception as exc:  # noqa: BLE001
                sweep_report = {"error": str(exc)}
                ev("postflight.process_sweep", actor="harness",
                   payload={"error": str(exc)})
        nested_meter = collect_nested_meter(self.store.run_dir)   # 增强③
        integrity = verify_protected_unchanged(integrity_before)
        if not integrity["ok"]:
            ev("integrity.MISMATCH", actor="harness", payload=integrity)
        self.timings["total_wall_s"] = round(time.monotonic() - t0, 1)
        ev("run.end", actor="runner", payload={
            "verdict": verdict_record.get("verdict"),
            "main_dir_integrity_ok": integrity["ok"],
            "timings": self.timings})

        chain_ok, n_events, chain_err = verify_chain(self.store.trace_path)
        trace_sha = sha256_file(self.store.trace_path)
        failure_types = sorted({
            p["type"] for r in records for p in (r.failure_packets or [])}
            # 修复轮的失败包之外,**验证器归因**也必须进 failure_types——
            # 否则重放期暴露的模型缺陷在台账里只留一个 UNKNOWN(2026-08-12
            # 实录:两发 T3 因声明装不回来的钉版挂在重放,台账 failure_types
            # 分别是 UNKNOWN 与 SCHEMA_ERROR/TEST_FAILURE,都没说中死因)。
            | {vr.extra["failure_type"]
               for vr in (capability_vr, regression_vr, policy_vr, replay_vr)
               if vr is not None and vr.extra.get("failure_type")})
        report = {
            "run_id": self.run_id,
            "task_id": self.contract.task_id,
            "mode": "host-guided-repair",
            "final_verdict": verdict_record.get("verdict"),
            **verdict_record,
            "gate_reasons": gate_reasons,
            "agent": agent_metrics,
            "repair": repair_summary,
            "public_passed_by_round": public_by_round,
            "regression_by_round": regression_by_round,
            "budget_exhausted": budget_exhausted,
            "adaptation_root": (adaptation_manifest.tree_root_sha256
                                if adaptation_manifest else None),
            "main_dir_integrity": integrity,
            "final_trace_sha256": trace_sha,
            "trace_events": n_events,
            "trace_chain_ok": chain_ok,
            "trace_chain_error": chain_err,
            "timings": self.timings,
            "first_outcome": first_outcome or {},
            "postflight_sweep": sweep_report or "UNKNOWN",
            "runtime_browser_agent": nested_meter or "UNKNOWN",
        }
        self.store.save_json("report.json", report)

        harness_commit = subprocess.run(  # noqa: S603
            ["git", "-C", str(self.project_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False).stdout.strip() or "UNKNOWN"
        rounds_used = repair_summary.get("rounds_run") or len(records) or "UNKNOWN"
        record = {
            "run_id": self.run_id,
            "task_id": self.contract.task_id,
            "task_version": self.contract.task_version,
            "harness_commit": harness_commit,
            "host_commit": self.contract.host.commit,
            "source_commit": self.contract.source_repo.resolved_commit,
            "model": model_name,
            "provider": "openai-compatible" if preflight else "fake",
            "provider_config_hash": (preflight.provider_config_sha256
                                     if preflight else "UNKNOWN"),
            "run_index": run_index,
            "run_order": run_order,
            # 批次归属:探索性加发打 EXPLORATORY_UNPREREGISTERED,闸门不计
            # (TESTPLAN §8/§9)。缺省 UNKNOWN,历史行无此字段=预注册批次。
            "batch": batch,
            "guided": True,
            "max_rounds": self.contract.budgets.max_rounds,
            "rounds_used": rounds_used,
            "model_calls": agent_metrics.get("model_calls"),
            "commands": agent_metrics.get("commands"),
            "input_tokens": agent_metrics.get("input_tokens"),
            "output_tokens": agent_metrics.get("output_tokens"),
            "wall_time": self.timings.get("total_wall_s"),
            "cost": agent_metrics.get("cost", "UNKNOWN"),
            "public_passed_by_round": public_by_round or "UNKNOWN",
            "regression_by_round": regression_by_round or "UNKNOWN",
            "rollback_count": len(repair_summary.get("rolled_back_rounds", []) or []),
            "scope_change_count": 1 if repair_summary.get("pending_scope_change") else 0,
            "stagnation": repair_summary.get("stop_reason") == "stagnation",
            "final_capability": capability_vr.detail if capability_vr else "UNKNOWN",
            "final_regression": regression_vr.detail if regression_vr else "UNKNOWN",
            "policy": (("PASS" if policy_vr.passed else "FAIL")
                       if policy_vr else "UNKNOWN"),
            "replay": (("PASS" if replay_vr.passed else "FAIL")
                       if replay_vr else "UNKNOWN"),
            "verdict": verdict_record.get("verdict"),
            "failure_types": failure_types or "UNKNOWN",
            "execution_backend": "local-worktree",
            "env_baseline_hash": self.env_baseline_hash,
            "main_dir_integrity": "ok" if integrity["ok"] else "MISMATCH",
            "trace_sha256": trace_sha,
            "bundle_path": str(self.store.run_dir),
            # 增强③:嵌套双计量(源 §19);无数据一律 UNKNOWN 不写 0
            "runtime_browser_agent": nested_meter or "UNKNOWN",
            # 增强①:postflight 清扫摘要(详情在 report.json/trace)
            "postflight_sweep": (
                "UNKNOWN" if sweep_report is None
                else {"killed": len(sweep_report.get("killed", [])),
                      "skipped_new": len(sweep_report.get("skipped_new", [])),
                      "leftover_new_pids": sweep_report.get("leftover_new_pids", []),
                      **({"error": sweep_report["error"]}
                         if "error" in sweep_report else {})}),
        }
        append_run(self.project_root, record)
        ev("bench.recorded", actor="harness", payload={"runs_jsonl": "benchmarks/v2/runs.jsonl"})
        return report


class _BaselineUnhealthy(Exception):
    def __init__(self, report: dict) -> None:
        super().__init__("HOST_BASELINE_UNHEALTHY")
        self.report = report


class _BenchContaminated(Exception):
    """bench 根白名单外条目(T2 批 1 实证:遗留正控工作区被 agent 挖到)。"""

    def __init__(self, strays: list[str]) -> None:
        super().__init__("BENCH_ROOT_CONTAMINATED")
        self.strays = strays


# ------------------------------------------------------------------ CLI 入口
def run_host_guided_cli(
    contract_path: Path,
    project_root: Path,
    *,
    fake: str | None = None,
    run_order: int | str = "UNKNOWN",
    run_index: int | str = "UNKNOWN",
    batch: str = "UNKNOWN",
    wheelhouse: Path | None = None,
    keep_session: bool = False,
) -> dict:
    """准入 → 预检 → 宿主级 guided 运行。

    fake:
      None        真实模型(REPOPROOF_API_BASE/KEY/MODEL 环境变量)
      "noop"      fake 模型什么都不做直接提交(FAIL 路径冒烟)
      "positive"  fake 模型脚本化注入正控(PASS 路径冒烟;绝不用于正式 run)
    """
    if fake is None:
        # 预检在 runner 构造(=建 run 目录)之前:preflight 拦截绝不留下
        # 无 report.json 的隐身 run 目录(LESSONS #12 教训)。
        from repoproof.agents.provider_gate import run_preflight
        from repoproof.runner.agent_run import provider_from_env

        # H9-a(LESSONS #41):答案残留在盘上就**拒开**,不是告警。
        # 反例 order-21:`~/RepoProofBench-quarantine/_scratch_t2_positive/
        # research_jobs.py` 被整文件 cp 进工作区,交付 344 行里 295 行与正控
        # 逐字相同。H9-b 的路径检测能被绕过,这一条不能 —— 答案不在盘上。
        residue = reachable_answer_keys(Path(contract_path).parent)
        if residue:
            return {"blocked": True, "agent_model_call_count": 0,
                    "preflight": {"ready": False, "reason": "ANSWER_KEY_REACHABLE"},
                    "answer_key_residue": residue[:20],
                    "remediation": "运行主机上仍可达到正控/负控/任务工程期残留;"
                                   "清掉或移出本机后再开跑(它们在 run 期间没有用途)"}

        provider = provider_from_env()
        pf = run_preflight(provider)
        if not pf.ready:
            return {"blocked": True, "preflight": pf.summary(),
                    "agent_model_call_count": 0}
        runner = HostGuidedRunner(contract_path, project_root, wheelhouse=wheelhouse)
        report = runner.run(provider, pf, run_order=run_order, run_index=run_index,
                            batch=batch, keep_session=keep_session)
        return {"blocked": False, "preflight": pf.summary(), "report": report}
    runner = HostGuidedRunner(contract_path, project_root, wheelhouse=wheelhouse)

    from repoproof.agents.fake_model import FakeModel

    def factory(_totals: dict):
        return FakeModel(script=_fake_script(fake, runner))

    report = runner.run(None, None, model_factory=factory,
                        run_order=run_order, run_index=run_index, batch=batch,
                        keep_session=keep_session)
    return {"blocked": False, "preflight": None, "report": report}


def _fake_script(kind: str, runner: HostGuidedRunner) -> list[dict]:
    """冒烟脚本。positive 脚本读取正控参考实现(harness 侧冒烟专用;
    正式 run 走真实模型,正控内容永不进入其提示或环境)。"""
    if kind == "noop":
        return [{"content": "noop submit",
                 "actions": [{"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"}]}]
    if kind != "positive":
        raise ValueError(f"未知 fake 模式:{kind}")
    positive = (runner.task_dir / "controls" / "positive" / "sdk_mcp.py").read_text(
        encoding="utf-8")
    mcp_pins = "fastapi-mcp\nmcp<2.0\n"
    steps = [
        {"actions": [{"command": ".venv/bin/pip install -q fastapi-mcp 'mcp<2.0'"}]},
        {"actions": [{"command":
                      "cat > sdk_mcp.py <<'RP_EOF'\n" + positive + "\nRP_EOF"}]},
        {"actions": [{"command":
                      "printf '\\nfrom sdk_mcp import mount_sdk_mcp\\n"
                      "mount_sdk_mcp(app)\\n' >> rag_api.py"}]},
        {"actions": [{"command":
                      "printf '" + mcp_pins.replace("\n", "\\n") + "' >> requirements.txt"}]},
        {"actions": [{"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"}]},
    ]
    return steps
