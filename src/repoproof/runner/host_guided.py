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
from pydantic import BaseModel, Field, field_validator

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


def make_usage_cb(token_totals: dict):
    """run 级 token 汇总回调(挂 litellm success_callback)。

    流式路(deepseek)对**同一请求**派发两枚带 usage 的 success 事件:
    末 chunk 自带全额 usage,组装出的 complete_streaming_response 又带
    同一份(HB-DSENTRY-1 批报 §4,单调用探针:66 枚逐 chunk usage=None
    + 2 枚终态满额;台账虚高 1.30×/1.50×,异步竞态使之非严格 2×)。
    按 litellm_call_id 去重:同一请求只记先到的一枚(两枚数值相同)。
    无 id 的事件按旧行为计数,不静默丢;非流式(gpt 路)单枚事件不受
    影响。执法与轮桶不走此路(同步记账,LESSONS #39 H7-a/H7-d)。
    """
    seen_call_ids: set = set()

    def _usage_cb(kwargs, completion_response, start_time, end_time):  # noqa: ANN001
        usage = getattr(completion_response, "usage", None)
        if not usage:
            return
        k = kwargs or {}
        call_id = k.get("litellm_call_id") or (k.get("litellm_params") or {}).get("litellm_call_id")
        if call_id is not None:
            if call_id in seen_call_ids:
                return
            seen_call_ids.add(call_id)
        token_totals["seen"] = True
        token_totals["in"] += getattr(usage, "prompt_tokens", 0) or 0
        token_totals["out"] += getattr(usage, "completion_tokens", 0) or 0

    return _usage_cb


def absorb_dsh_usage(token_totals: dict, usage: dict) -> None:
    """B-dsh 臂的 run 级用量落账 —— 第二个(也是最后一个)被钉允许的落点。

    与 make_usage_cb 同为 token_totals 累加的合法实现(test_token_enforcement
    的单实现钉逐行点名这两处)。来源是可信 events 汇经 normalize() 的
    usage 律(逐枚累加/终态权威/伪造双计点名,M86a-c 钉),**入口已去重**;
    这里只做落账,不做第二套去重逻辑。
    """
    token_totals["in"] += int(usage.get("input_tokens", 0))
    token_totals["out"] += int(usage.get("output_tokens", 0))
    if usage:
        token_totals["seen"] = True


def projection_mode() -> str:
    """投影模式:off(E0)/ prune(S2 确定性折叠)/ window(S2' 滑动窗口)。

    S2 实测判别力为 0(基线重复命令 0 条),故 `1` 现在解作 **window** ——
    那是唯一在真实数据上有效果的模式(基线六发降 12%,撞预算墙的 6 轮里
    4 轮折算后余量充足)。要单跑 S2 的确定性折叠用 `prune`。"""
    import os

    raw = os.environ.get("REPOPROOF_CONTEXT_PROJECTION", "").strip().lower()
    if raw in {"1", "true", "yes", "window"}:
        return "window"
    if raw == "prune":
        return "prune"
    return "off"


def projector_or_none():
    """投影函数或 None。None = E0 语义,messages 一字不动。"""
    mode = projection_mode()
    if mode == "off":
        return None
    from repoproof.agents.context_projector import project, project_window

    return project_window if mode == "window" else project


# ------------------------------------------------------------ WH 两臂(D4)
#
# 方案文档 §7.2 把 H2 写成十件套(投影 / 持久 shell / 编辑器 / capsule /
# 需求状态板 / FailurePacket v2 / 最佳态 / 靶向公开测试 / context reset)。
# 盘上实况:其中**六件不存在** —— S3/S4 判 NO_EXPOSURE 从未建,S5 判
# BLOCKED(状态板会主动给错误正信号),S2′ 两批消融后对 GPT 代际归档关闭
# (默认 off)。照那张清单实现 = 为一次消融临时造六个没有独立证据的机制,
# 与"先冻结判据、再测"正相反。
#
# 故两臂按**盘上真有的东西**定义,差集恰是 harness 今天所谓"引导"的全部:
#   guided (H2) = 当前默认:多轮编排 + 每轮结构化失败包 + 最佳态回滚 +
#                 轮抬头(含 scope-change 协议)
#   minimal(H0) = 冻结契约 + 单 Agent + 受控 bash + 公开测试(agent 自己
#                 跑,原始输出)+ 独立终局验证 + 同等总额度
# 安全面两臂**逐字相同**(策略执法、预算硬墙、越界拒绝、终局六层验证、
# 干净重放),差的只有引导 —— 否则测出来的是"安全网",不是"引导增益"。


def harness_mode() -> str:
    """WH 臂:`guided`(默认)/ `minimal`。

    缺省与拼错一律回落 guided —— 未知取值不许静默把发次降成最小臂
    (fail-closed 到当前行为,同 projection_mode)。
    """
    import os

    raw = os.environ.get("REPOPROOF_HARNESS_MODE", "").strip().lower()
    return "minimal" if raw == "minimal" else "guided"


def effective_budgets(b: "HostBudgets", mode: str | None = None) -> "HostBudgets":
    """最小臂的**等总额**换算:轮数收成 1,每轮额度乘回原轮数。

    §7 的题面是"相同任务和相同总预算"。per_round 语义下总额 = 每轮 ×
    轮数,所以最小臂单轮必须拿满原来的总和,否则测的是"少给了三分之二
    额度",不是"没给引导"。`semantics="total"`(v1)本就是全 run 额度,
    只收轮数不乘 —— 乘了就是白送两倍。

    patch/wall **不乘**(HostBudgets 原文:两者恒为全 run):它们约束的是
    交付物形态与墙钟,不是努力量;两臂的验收必须逐字同一条线。
    """
    if (mode or harness_mode()) != "minimal" or b.max_rounds <= 1:
        return b
    scale = b.max_rounds if b.per_round else 1
    return b.model_copy(update={
        "max_rounds": 1,
        "max_model_calls": b.max_model_calls * scale,
        "max_commands": b.max_commands * scale,
        "max_input_tokens_total": b.max_input_tokens_total * scale,
        "max_output_tokens_total": b.max_output_tokens_total * scale,
    })


# 最小臂的抬头:只留安全句,去掉"修复轮/失败包/最佳态回滚/scope-change"
# 四样 —— 那四样在最小臂都不存在,照发就是教一条不存在的路(#33 先教后
# 杀的反面:不许教做不到的事)。"不许编造测试结果"是安全面不是引导面,
# 两臂必须都有。
_MINIMAL_HEADER = (
    "\n\n==== SINGLE PASS ====\n"
    "You get one pass on this host working tree. Run the public acceptance\n"
    "tests and the host regression suite yourself whenever you want to know\n"
    "where you stand; the harness will not summarise them for you between\n"
    "attempts. Never invent test results.\n"
)


def round_guidance(mode: str, *, idx: int, max_rounds: int, marker: str) -> str:
    """轮抬头 —— 引导面的全部文本落点,故抽成函数以便单独钉死。"""
    if mode == "minimal":
        return _MINIMAL_HEADER
    return _ROUND_HEADER.format(idx=idx, max_rounds=max_rounds, marker=marker)


def _exec_profile_fields(contract, preflight, budgets=None, *,
                         backend: str = "mini-swe",
                         backend_composition: dict | None = None) -> dict:
    """执行侧三面指纹 + 代际 + 代码内容指纹(EXECUTOR-UPGRADE-PLAN S1)。

    取值全部来自**本次发次真正生效的配置**,不是文档里写的意图:
    工具面读 obs_cap() 与实际动作协议,上下文面读同一个 cap 与当前投影
    策略,预算面读契约 budgets 全量。E1 各步上线时只需在这里补字段,
    代际标签由 profiles.exec_generation 自动推导 —— 不靠人记得改。

    backend(DSH 阶段 8):B-dsh 臂的工具/上下文面记 DSH 组合的真身,
    缺省 mini-swe 分支逐字节不动(判据 F5:历史指纹不追溯漂移)。"""
    from repoproof.agents.profiles import profile_hashes

    # 预算面读**本次真正生效的**额度(最小臂已换算),不是契约里写的意图
    # —— 与本函数开头那条纪律同一条;记契约值就等于两臂指纹相同,消融
    # 分不了池。
    b = budgets if budgets is not None else contract.budgets
    if backend == "dsh":
        # B-dsh 臂:不读 mini-swe 的 obs_cap/投影/引导旋钮 —— 那些机制不在
        # 这条臂上,读了就是把别的臂的配置记成自己的(两臂必须分池,
        # M-DSH-14 的指纹面)。composition 指纹整份入 context 面哈希:
        # 组合任何一键变(版本/cordis/三缺省/model),context 指纹跟着变。
        tool = {
            "action_protocol": "dsh-minimal-v1",
            "tools": ["bash", "str_replace_editor"],
            "obs_char_cap": None,
        }
        context = {
            "policy": "dsh-runtime-native",
            "composition": dict(backend_composition or {}),
        }
    else:
        cap = obs_cap()
        tool = {
            "action_protocol": (preflight.action_protocol if preflight else "fake"),
            "tools": ["bash"],
            "obs_char_cap": cap,
        }
        context = {
            # E0:mini-swe DefaultAgent 每轮重发完整历史,单条观察头尾截断
            "policy": "full-history-resend",
            "obs_char_cap": cap,
        }
    hmode = harness_mode()
    if backend != "dsh":
        if hmode != "guided":
            # 只在非默认臂**加键**(同投影那条的写法):guided 臂的三面指纹
            # 与历史发次逐字节相同,不追溯改写(判据 F5);最小臂天然分池。
            context["guidance"] = "none"
            tool["harness_mode"] = hmode
        mode = projection_mode()
        if mode != "off":
            # 开了投影就**自动**离开 E0(profiles.exec_generation 据此推导);
            # 标签与开关同源,不存在"开了却仍标 E0"的漂移(S1 判据 P4 的现场版)。
            # 两种模式的 context 指纹必须不同 —— 它们是两个机制,不能混池。
            from repoproof.agents.context_projector import (
                SUPERSEDE_MIN_CHARS,
                WINDOW_READS,
            )

            if mode == "window":
                context["prune_policy"] = "window-v1"
                context["window_reads"] = WINDOW_READS
                context["lossy"] = True
            else:
                context["prune_policy"] = "deterministic-v1"
                context["supersede_min_chars"] = SUPERSEDE_MIN_CHARS
    budget = {
        "semantics": b.semantics, "max_rounds": b.max_rounds,
        "max_model_calls": b.max_model_calls, "max_commands": b.max_commands,
        "max_patch_files": b.max_patch_files, "max_patch_lines": b.max_patch_lines,
        "max_wall_time_minutes": b.max_wall_time_minutes,
        "max_input_tokens_total": b.max_input_tokens_total,
        "max_output_tokens_total": b.max_output_tokens_total,
    }
    repo = Path(__file__).resolve().parents[3]
    # 上游交付拓扑(A1):契约声明,缺省 in-process = 既有全部发次的行为。
    # 它进代际标签,于是 sidecar 发次与 in-process 发次在分析时天然分池 ——
    # 那是两道题,不是同一道题的两种跑法(execution/runtime_profiles.py)。
    from repoproof.execution.runtime_profiles import profile_of_contract

    rp = profile_of_contract(contract)
    out = profile_hashes(tool=tool, context=context, budget=budget, repo=repo,
                         runtime_profile=rp.id)
    # WH 臂单列可读字段(不入哈希):分析要能直接按臂分组,而不是去解析
    # 代际标签串 —— 与 runtime_profile_id 单列同一条理由。
    out["harness_mode"] = hmode
    # Agent backend 单列(DSH 阶段 8):bench_records 的第三锁按它裁能力池
    # 资格。历史行缺列 = mini-swe;新行两臂都显式落,不再靠 UNKNOWN 回填。
    out["backend_id"] = backend
    # 语义分面(2026-08-14):与粗粒度 exec_fingerprint **并存**。后者是 S1
    # 留下的值,历史发次绑着它,不追溯改写(判据 F5);新发次两个都记,
    # 严格 A/B 只看相关面(判据 F4)。
    from repoproof.agents.profiles import semantic_fingerprints

    out.update(semantic_fingerprints(repo))
    return out


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
from repoproof.verification.junit import parse_junit_xml, split_public_outcomes
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
def _resolve_wheelhouse(explicit, host) -> Path:
    """冻结轮仓的落点 —— 命令行 > 契约声明 > 第一宿主的历史命名。

    **抽成函数而不是写在 `__init__` 里**,是因为 `__init__` 要建 run 目录、
    校 HEAD、读 manifest,钉死没法直接考它,于是只能读源码串 —— 而读串抓不住
    "字段还在、没人用"(实测:M61d 就这么逃了一次)。
    """
    return Path(
        explicit
        or getattr(host, "wheelhouse_path", "")
        or Path("~/RepoProofBench").expanduser()
        / f"wheelhouse-offerclaw-{host.commit[:7]}"
    ).expanduser().resolve()


class HostHealthCheck(BaseModel):
    """基线健康检查的一条。

    `pass_if_stdout_contains` 是给"退出码非零但已知预期差异"留的口子 ——
    OfferClaw 的 `verify_docs.py` 就是这种(chunks 交叉核对因合成语料重建
    必然不一致,但"0 处未围栏裸露"不退化才是真判据,2026-08-09 由首次冒烟
    BLOCKED 校准)。**只在契约里显式写出来才生效**,代码里不再有硬编码中文串。
    """

    command: list[str]
    pass_if_stdout_contains: str = ""
    gating: bool = True          # False = 只记录不作门禁(OfferClaw 的 doctor.py)


# 第一宿主(OfferClaw)的形状。**缺省值就是它现在的行为,逐字节不变** ——
# 泛化的意义是让第二宿主能声明自己的形状,不是趁机改第一宿主的判据。
_OFFERCLAW_SETUP = [
    ["python3", "-m", "venv", ".venv"],
    [".venv/bin/pip", "install", "-q", "-r", "requirements.txt"],
    [".venv/bin/python", "rag_ingest.py"],
]
_OFFERCLAW_HEALTH = [
    {"command": ["python", "verify_pipeline.py"]},
    {"command": ["python", "verify_docs.py"], "pass_if_stdout_contains": "0 处未围栏"},
    {"command": ["python", "doctor.py"], "gating": False},
]


class HostInfo(BaseModel):
    repo: str
    commit: str
    copy_path: str
    baseline_manifest: str = "HOST_BASELINE_MANIFEST.json"
    regression_command: list[str]
    regression_baseline: str = ""
    # ---- C 轨(2026-08-15):宿主形状从代码常量搬进契约 ----
    #
    # 勘察查出五处把 OfferClaw 布局当常量的地方,第二宿主不是"跑起来不准",
    # 是**跑不起来**:没有 requirements.txt / rag_ingest.py 直接 HostRunError,
    # 三个健康检查脚本不存在 → exec 127 → 每发零预算 BLOCKED,而且无旁路。
    #
    # 缺省 = OfferClaw 现状,所以 T1–T3 的行为**一个字节都不变**(K13 现场验)。
    # 第二宿主在自己的契约里声明,不改一行 harness 代码。
    setup_commands: list[list[str]] = Field(default_factory=lambda: list(_OFFERCLAW_SETUP))
    health_checks: list[HostHealthCheck] = Field(
        default_factory=lambda: [HostHealthCheck(**h) for h in _OFFERCLAW_HEALTH])
    # oracle 拿宿主根用的环境变量名。OfferClaw 的 oracle 读 OFFERCLAW_HOST_ROOT;
    # 别的宿主自然读别的名字。两个都注入(见 `_run_oracle`)——多注一个没有害处,
    # 少注一个会让 oracle 在自己家里找不到路。
    host_root_env: str = "OFFERCLAW_HOST_ROOT"
    # 冻结轮仓。空 = 沿用第一宿主的历史命名 `wheelhouse-offerclaw-<commit7>`
    # (九个现存轮仓都叫这个,改名会让全部历史发次无法复现)。
    wheelhouse_path: str = ""
    # 轮仓 manifest。第二宿主的轮仓是 `pip download` 出来的,没有第一宿主那套
    # env_baseline_hash 记账 —— 缺省仍要求它在(那是第一宿主的既有纪律),
    # 契约可声明 false 表示"这个宿主的环境基线由别处保证"。
    require_wheelhouse_manifest: bool = True
    # 测量三跑的 PATH 语义(G7,B10 同款换宿主复发:sqlglot test_lazy_load
    # 起裸 `python` 子进程,本机 PATH 无裸 python → 基线 1149/1150 恒 BLOCKED;
    # 准入量具早已 venv/bin 前置——M66f 钉着,harness 的钦定套件跑法没有同款,
    # 两把尺子两个答案)。声明 true = 回归/公开面按"激活 venv"语义跑
    # (会话 venv/bin 前置进 PATH);缺省 false = 既有宿主行为一字不变。
    path_prepend_venv_bin: bool = False
    # PII 出口扫描的范畴(G5,2026-08-16 实测):该闸守的是**用户宿主的个人
    # 数据**不进 agent 工作区;对公开 OSS 上游树,上游测试夹具里的假邮箱/
    # 样例号码(click test_defaults 的 a@b.com、sqlglot 方言测试的 SQL 样例)
    # 是**按构造公开**的内容,命中即拒跑是范畴错配。声明 public-oss-tree =
    # 跳过扫描并在事件里如实记 SKIPPED;缺省 user-host 行为一字不变。
    pii_scan_profile: str = "user-host"
    # oracle 进程的 env 净化(2026-08-16 可搬运性审查 blocking [1a]):历史行为
    # 给 oracle 注 PYTHONPATH=<宿主根>(OfferClaw 的 oracle 靠它 import 宿主
    # 模块)。但 PYTHONPATH 在 site 处理时刻就上 sys.path —— 宿主根下一个
    # sitecustomize.py 会在**判卷解释器的起点**被自动 import,agent 可借此
    # 改写判卷读数(含 h1 守卫自身)。delta 任务的 oracle 不需要宿主上
    # sys.path(驱动器自带 sys.path.insert,宿主包经 .venv 装),声明 true =
    # 不注 PYTHONPATH 且禁 user-site;缺省 false = 既有宿主行为一字不变。
    oracle_env_sanitized: bool = False

    @field_validator("pii_scan_profile")
    @classmethod
    def _known_pii_profile(cls, v: str) -> str:
        if v not in {"user-host", "public-oss-tree"}:
            raise ValueError(f"未知 pii_scan_profile:{v!r}"
                             "(可选:public-oss-tree | user-host)")
        return v


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


def _reject_duplicate_keys(raw: bytes, path: Path) -> None:
    """冻结契约里出现重复顶层键 → 报错。

    2026-08-14 实测到的坑:往契约里加了一行 `task_shape: DEPENDENCY_INTEGRATION`,
    而 165 行早就有一个 `task_shape:` 字典。`yaml.safe_load` **后者覆盖前者
    且不报错**,于是新加的那行静默消失,而所有下游看到的仍是旧值 —— 契约是
    冻结对象,这种静默覆盖等于契约说的和实际生效的不是一回事。
    """
    import yaml as _y

    class _Dup(_y.SafeLoader):
        pass

    def _mapping(loader, node, deep=False):
        seen, dups = set(), []
        for k, _ in node.value:
            key = loader.construct_object(k, deep=deep)
            if key in seen:
                dups.append(key)
            seen.add(key)
        if dups:
            raise HostRunError(f"契约里有重复键(YAML 会静默覆盖):{sorted(set(dups))} @ {path}")
        return _y.SafeLoader.construct_mapping(loader, node, deep=deep)

    _Dup.add_constructor(_y.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)
    _y.load(raw, Loader=_Dup)


# S2:哪些回执核验失败**不许记到被测方头上**(走 missing_external → BLOCKED)。
# 其余(U2/U3/U4 判红)是**被测方**的失败,必须并进 capability 侧,否则
# "没真用上游"会被记成"不算模型失败、可重跑"。
_HARNESS_SIDE_RECEIPT_REASONS = frozenset({
    "NO_DELIVERY_EXTRACTOR",       # 任务包没给取件器
    "NO_DELIVERY_EXTRACTED",       # 取不到交付(目录不在)
    "RECEIPT_VERIFIER_ERROR",      # 核验器自己炸了
    "UPSTREAM_EXECUTION_ERROR",    # 封存浏览器崩了/超时(S1)
    # 工件在、但**全都读不出来**(S4)。严格说这不是 harness 的错(契约 R8
    # 写明了 schema),但契约的 failure_taxonomy 里没有对应类型,硬塞一个
    # 等于用未言明的要求判人 —— 而预注册 Q3 写死了"说不清的,该发作废"。
    # 所以归到"不判被测方失败"这一侧,同时**保留独立的 reason 串**:
    # 它与 NO_DELIVERY_EXTRACTED 在记录里可区分,真出现了看得见、能议。
    "DELIVERY_SHAPE_INVALID",
})


def _adoption_detail(rv: dict) -> str:
    red = [f'{f["check"]}: {f["detail"]}' for f in (rv.get("findings") or [])
           if not f["ok"]]
    return "; ".join(red)[:600] or str(rv.get("reason"))


class HostContract(BaseModel):
    """宿主级任务契约(benchmarks/v2/tasks/*/contract.yaml,冻结对象)。"""

    task_id: str
    task_version: str
    kind: str
    host: HostInfo
    # ---- G1(HB-PCDELTA-1,2026-08-16):source_repo 可选 ----
    # delta 形态宿主即上游。复用 upstream-cache 会把**含答案 commit 的 git
    # 历史**复制进会话(一条 `git log -p` 即满分),所以这类任务不声明
    # source_repo,harness 相应跳过上游快照的核验与注入。缺省行为不变:
    # 既有契约全都声明了 source_repo,None 只在新契约里出现。
    source_repo: HostSourceRepo | None = None
    capability: HostCapability
    constraints: HostConstraints = HostConstraints()
    budgets: HostBudgets
    acceptance: HostAcceptance
    task_shape: dict = Field(default_factory=dict)     # 难度画像(既有含义)
    failure_taxonomy_expected: list[str] = Field(default_factory=list)
    # ---- 上游交付拓扑与任务谱系(A1,2026-08-14)----
    # 缺省全部等于既有行为:in-process + 依赖集成 + 未归族。
    runtime_profile: str = "rt-inprocess-v1"
    task_family: str = ""
    adoption_shape: str = "DEPENDENCY_INTEGRATION"
    # ---- G2:提示档口 ----
    # 提示文字住在代码里(可钉死、可变异),契约只选档。缺省 offerclaw-v1
    # 逐字节等于既有提示(金标哈希在 tests/test_hb_task_glue.py)。
    prompt_profile: str = "offerclaw-v1"

    @field_validator("prompt_profile")
    @classmethod
    def _known_prompt_profile(cls, v: str) -> str:
        known = {"offerclaw-v1", "hb-delta-v1"}
        if v not in known:
            # 打错字必须炸在加载期 —— 否则一个 typo 会静默落回缺省档,
            # 而缺省档的提示对 delta 宿主句句是假话。
            raise ValueError(f"未知 prompt_profile:{v!r}(可选:{sorted(known)})")
        return v

    @classmethod
    def load(cls, path: Path) -> tuple["HostContract", str]:
        raw = Path(path).read_bytes()
        _reject_duplicate_keys(raw, path)
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
`/private/tmp/t2v4_direct/fixtures`(任务工程期)。

**`~/.Trash` 刻意不在这里**(2026-08-13 实测定的,详见 LESSONS #42)。
当天先加过、又撤了 —— 撤的依据是三条实测,不是嫌麻烦:

  ls ~/.Trash            -> Operation not permitted   (macOS TCC,非沙箱)
  find ~/.Trash          -> Operation not permitted
  head ~/.Trash/<确切名>/research_jobs.py  -> 正常打印出正控正文

即:废纸篓**不可枚举、却可按确切路径读**。做扫描根等于零覆盖(枚举不了
就什么也发现不了),同时因为"列不动"而永久判 `ANSWER_KEY_SCAN_BLIND` ——
一道在本平台上**不可满足**的闸门,最后一定是被人整条关掉,比明写限制更糟。

于是划成与 H9-b 同型的诚实边界:**残留不得停放在废纸篓,这条靠规程,
H9-a 执法不到**。真要清零就删到不存在,别删到"看不见"。"""

PROTECTED_TASK_DIRS = ("controls", "oracle", "fixtures", "public_tests")
_SESSION_DIR = "_sessions"


def reachable_answer_keys(
    task_dir: Path, roots: tuple[str, ...] = ANSWER_KEY_SCAN_ROOTS, max_depth: int = 3,
    blind: list[str] | None = None,
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

    `blind` 传入一个 list 时,**列不动的目录**记进去 —— 看不见不等于干净。
    反例(2026-08-13 实测):7 棵残留树 `mv` 进 `~/.Trash` 后,macOS TCC 让
    `iterdir()` 抛 `Operation not permitted`,老代码 `except OSError: continue`
    于是返回**0 处命中**,而 `test -d` 同时证明答案就在那儿 —— 检测器看不见
    时朝**放行**的方向失败了。本函数只报告盲区,拒不拒开由 preflight 判;
    单个文件读不到不计入(那是小得多的洞,且真机上噪声大)。
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
            except OSError:          # 列不动:不是残留证据,但也**不是**清白证据
                if blind is not None:
                    blind.append(str(cur))
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


def _pii_scan_required(contract: HostContract) -> bool:
    """PII 出口扫描要不要跑 —— 唯一判定点(G5)。

    只有显式声明 public-oss-tree 才跳;任何其他值(含缺省)都扫。抽成纯
    函数是为了让"全宿主静默跳扫"这个失效方向有人守(变异 M70b)。
    """
    return contract.host.pii_scan_profile != "public-oss-tree"


def source_commit_of(contract: HostContract) -> str:
    """台账 source_commit 的唯一来源(G1)。

    没有 source_repo 时如实落宿主 commit —— 源即宿主。不落 UNKNOWN:
    这个 commit 是真实存在且已核验过的,装不知道反而是假话。
    """
    if contract.source_repo is not None:
        return contract.source_repo.resolved_commit
    return contract.host.commit


def build_host_prompt(contract: HostContract, *, wheel_note: str,
                      budgets=None) -> str:
    """契约 → agent 提示的唯一投影(不含任何 oracle/隐藏信息)。

    双档(G2):offerclaw-v1 = 既有文本逐字节不变(金标哈希钉死);
    hb-delta-v1 = post-cutoff delta 形态,一句 OfferClaw 的话都不许说。
    """
    if contract.prompt_profile == "hb-delta-v1":
        return _build_delta_prompt(contract, wheel_note=wheel_note, budgets=budgets)
    if contract.source_repo is None:
        raise HostRunError(
            "offerclaw-v1 档口的提示要陈述 ../upstream,而契约没有 source_repo "
            "—— 无上游的任务请声明 prompt_profile: hb-delta-v1")
    cap = contract.capability
    req_lines = [f"[{r.id}] {' '.join(r.text.split())}" for r in cap.requirements]
    forbidden = [f"- {' '.join(f.split())}" for f in contract.constraints.forbidden]
    # 提示里的额度必须是**生效额度**:最小臂说"3 轮 30 调用"而实际单轮
    # 90 调用,等于拿假数字规划,那是量具在骗被测方。
    b = budgets if budgets is not None else contract.budgets
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


def _build_delta_prompt(contract: HostContract, *, wheel_note: str,
                        budgets=None) -> str:
    """hb-delta-v1 档口(HB-PCDELTA-1,预注册 §4 裁决 A:盲攻同视野)。

    对提示的三条纪律:
    1. **不说第一宿主的话**:无 OfferClaw、无 ../upstream、无 requirements.txt
       (重放从契约 setup_commands 重建,提示说 requirements.txt 就是教一条
       不存在的路);
    2. **先教后杀**(附录一第 4 条):验收语义类别公开 —— 上游同 PR 自带的
       隐藏验收测试 FAIL→PASS、回归全绿;验收实例(文件/节点名/内容)隐藏;
    3. H9-c 工作区边界照教,截断与靶向读取的忠告照教(与执行器行为一致,
       不是宿主专属)。
    """
    cap = contract.capability
    req_lines = [f"[{r.id}] {' '.join(r.text.split())}" for r in cap.requirements]
    forbidden = [f"- {' '.join(f.split())}" for f in contract.constraints.forbidden]
    b = budgets if budgets is not None else contract.budgets   # 同上:生效额度
    public_cmd = " ".join(contract.acceptance.public_test_command)
    parts = [
        "You are implementing an accepted feature request in a REAL open-source\n"
        f"project ({contract.host.repo}). You work directly inside the project\n"
        "tree as it stood just before this feature landed upstream.",
        f"GOAL\n{cap.statement.strip()}",
        "REQUIREMENTS (each is verified)\n" + "\n".join(req_lines),
        "YOUR ENVIRONMENT\n"
        "- You start in the project root (a disposable snapshot; git is\n"
        "  available and the baseline is already committed).\n"
        "- ./.venv              project virtualenv: the package is installed\n"
        "  editable with its test dependencies and pytest preinstalled.\n"
        "- Regression suite (MUST stay green) — run it yourself:\n"
        f"    {public_cmd}\n"
        f"- pip is OFFLINE: it resolves ONLY from a local wheel index ({wheel_note}).\n"
        "  The task needs nothing beyond what is preinstalled.\n"
        "- Command outputs beyond ~8000 chars are TRUNCATED (head+tail) with a notice.\n"
        "  Read files in targeted ranges (sed -n '120,180p' FILE, grep -n PATTERN FILE)\n"
        "  instead of dumping whole files — every char you read is re-sent on every\n"
        "  later call and burns your per-round token allowance quadratically.",
        "HARD RULES\n" + "\n".join(forbidden)
        + "\n- Do not modify anything under ./tests or ./public_tests. The regression\n"
          "  suite is a measuring instrument; changing it is treated exactly like\n"
          "  forging results."
        + "\n- STAY INSIDE THE WORKSPACE. Everything you need is here in ./ .\n"
          "  Do NOT read anything else on this machine — no filesystem-wide\n"
          "  sweeps (find / ...), and never touch the benchmark tree, reference\n"
          "  solutions or hidden acceptance material. Such commands are DENIED,\n"
          "  and referencing that material ends the run.",
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
        "Acceptance is judged AFTER you finish by the upstream project's own\n"
        "hidden acceptance tests for this exact feature: they must go from FAIL\n"
        "to PASS, and the regression suite must stay green. You cannot see them;\n"
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


def dsh_receipt_block(fidelity_missing: list, round_infos: list[dict]) -> dict:
    """B-dsh 台账回执块(记录装配的唯一来源)。

    独立成签名传参的函数不是整洁癖:装配发生在 _finish,而逐轮回执产自
    run() —— 跨方法引用局部名在 DQ-SDK-1 发 1 当场 NameError(链条全走完
    只差落账,2026-08-18)。签名把数据流钉死;送达判读走 dsh_bridge 的
    fidelity_verdict(M88d 钉的那份判读律),不另写第二套。
    """
    from repoproof.agents.dsh_bridge import fidelity_verdict

    v = fidelity_verdict(list(fidelity_missing))
    return {
        "fidelity_missing": list(fidelity_missing),
        "fidelity_verdict": v or "DELIVERED",
        "rounds": [{
            "attribution": i["attribution"],
            "session_id": i["session_id"],
            "logical_requests": i["counters"].get("logical_requests"),
            "usage": i["usage"],
            "fidelity_missing": i.get("fidelity_missing", []),
        } for i in round_infos],
    }


def run_dsh_round(*, workspace: Path, side_dir: Path, prompt: str,
                  budgets: "HostBudgets", model_name: str, api_base: str,
                  api_key: str, runtime_root: Path | None = None,
                  request_timeout_s: float | None = None,
                  session_id: str | None = None) -> tuple["AgentRunResult", dict]:
    """B-dsh 臂的一轮(模块级,可脱离 runner 独测):job 装配 → 封存
    worker → 回执适配成 AgentRunResult(DSH 阶段 8)。

    - workspace = 会话工作树(与 H0 同一棵);events/session 落 side_dir
      (工作树**外**)—— 落进工作树会被轮末 `git add -A` 收进适配 diff;
    - key 只在内存经 extra_env 传给 worker 进程环境(allowlist 之外全拦),
      不进本进程 os.environ、不落 argv/日志/回执;
    - 适配纪律:n_model_calls = logical_requests(周期计数,E5),
      commands_used = bash tool/call 计数,cost 恒 "UNKNOWN"(DSH 无
      费率读数,绝不写 0 冒充);submission 仅诊断,不产生 PASS。
    """
    from repoproof.agents.backend import AgentRunResult
    from repoproof.agents.dsh_backend import run_dsh_worker
    from repoproof.agents.dsh_bridge import (
        DEFAULT_RUNTIME_ROOT,
        DSH_MAX_TOKENS,
        DSH_SYSTEM_PROMPT,
        bridge_budget,
        composition_fingerprint,
        runtime_paths,
    )

    rt_root = Path(runtime_root or DEFAULT_RUNTIME_ROOT)
    worker_py, cordis = runtime_paths(rt_root)
    side_dir.mkdir(parents=True, exist_ok=True)
    job: dict = {
        "prompt": prompt,
        "workspace": str(workspace),
        "events_path": str(side_dir / "events.jsonl"),
        "session_root": str(side_dir / "sessions"),
        "cordis": str(cordis),
        "model": model_name,
        "system_prompt": DSH_SYSTEM_PROMPT,
        "max_tokens": DSH_MAX_TOKENS,
        "env": {"DEEPSEEK_BASE_URL": api_base},
    }
    if request_timeout_s is not None:
        job["request_timeout_seconds"] = request_timeout_s
    if session_id:
        job["session_id"] = session_id
    budget = bridge_budget(budgets)
    report = run_dsh_worker(job, worker_python=worker_py, budget=budget,
                            extra_env={"DEEPSEEK_API_KEY": api_key})

    c = report.trace.counters
    u = report.trace.usage_totals
    bash_calls = sum(1 for r in report.trace.records
                     if r.get("type") == "tool/call" and r.get("tool") == "bash")
    ok = report.attribution == "ok" and bool((report.result or {}).get("ok"))
    result = AgentRunResult(
        exit_status="submitted" if ok else f"dsh:{report.attribution}",
        # DSH 的终答仅诊断(落 run_dir 回执),不进 submission ——
        # N10:裁决树对它零消费,PASS 只走隐藏 oracle+验证器+干净重放。
        submission="",
        n_model_calls=int(c.get("logical_requests", 0)),
        cost="UNKNOWN",
        trajectory_path=None,
        commands_used=bash_calls,
        denied_count=0,
    )
    sid = report.trace.session_id or (report.result or {}).get("session_id")
    info = {
        "job": job,
        "budget": budget,
        "report": report,
        "fingerprint": composition_fingerprint(rt_root, model=model_name),
        "usage": dict(u),
        "counters": dict(c),
        "attribution": report.attribution,
        "session_id": sid,
        "events_path": job["events_path"],
        "selfcheck_problems": list(report.selfcheck_problems),
        "trace_problems": list(report.trace.problems),
    }
    return result, info


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
        # G1:无 source_repo 的任务(delta 形态,宿主即上游)没有上游快照 ——
        # 复用 upstream-cache 会把含答案 commit 的历史带进会话。
        self.upstream_src: Path | None = (
            self.project_root / "upstream-cache"
            / f"upstream-{self.contract.source_repo.resolved_commit[:12]}"
        ) if self.contract.source_repo is not None else None
        # 轮仓路径。缺省仍是 `wheelhouse-offerclaw-<commit7>`(第一宿主的历史
        # 命名,九个现存轮仓都叫这个,改名等于让全部历史发次无法复现);
        # 第二宿主在契约里声明自己的 `host.wheelhouse_path`。
        #
        # 名字里带 "offerclaw" 不是小事:它是**第六处**把第一宿主当常量的地方,
        # 而这一处的失败最隐蔽 —— 目录不存在时报的是"冻结 wheelhouse 缺失",
        # 看起来像是没建轮仓,而不是"harness 在按别人的名字找"。
        self.wheelhouse = _resolve_wheelhouse(wheelhouse, self.contract.host)
        self.run_id = f"{self.contract.task_id}-{time.strftime('%Y%m%d-%H%M%S')}"
        self.budgets = self.contract.budgets.as_budgets()
        self.timings: dict[str, float] = {}
        self._fake_mode: str | None = None     # 冒烟脚本名(真实发次恒为 None)
        self._browser_pids_before: set[int] | None = None   # 增强①:run 起点快照
        # 先核验后建店(LESSONS #35 · F3,批 6 期间实证):建店在护栏之前
        # 会给**被拒绝的**调用也留下 runs/<task>-<ts>/ 空壳,混在真实证据里
        # 像一发夭折的官方 run;跑测试套件时更会直接污染证据树。
        self._verify_static_resources()
        self.store = FileRunStore((runs_root or self.project_root / "runs") / self.run_id)

    # ------------------------------------------------------------ 静态核验
    def _verify_static_resources(self) -> None:
        # G1:无 source_repo → 无上游快照可核,跳过上游两查;轮仓照查。
        if self.upstream_src is not None:
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
            if self.contract.host.require_wheelhouse_manifest:
                raise HostRunError(f"wheelhouse manifest 缺失:{manifest}")
            # 声明了不要求 —— 但**环境基线哈希不许凭空造一个**。写明它没有,
            # 让台账里那一格如实是 UNKNOWN,而不是一个看起来煞有介事的值。
            self.env_baseline_hash = "UNKNOWN"
            return
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

    def _sidecar_env_for_oracle(self) -> dict[str, str]:
        """oracle 需要的 sidecar 环境。非 sidecar 任务返回空字典(行为不变)。

        给的是**与 agent 同一份**:端点、令牌、符号、fixture 基址、那批项的
        nonce。oracle 拿它去提交作业;它拿不到台账与密钥,与 agent 一样。
        """
        sess = getattr(self, "_sidecar_sess", None)
        if sess is None:
            return {}
        # **oracle 拿的比 agent 多两项**(fixture 基址 + 那批 nonce)。
        # B4:agent 拿到它们就能预取 oracle 将来会下发的全部项,把事实写死进
        # 源码,交付代码一次 RPC 都不发而四道谓词全绿。
        return dict(sess.oracle_env())

    def _receipt_failure_side(self, rv: dict) -> str:
        """回执核验没过 —— **这笔算谁的**。返回 `"harness"` 或 `"agent"`。

        单独一个方法而不是写在 `finally` 里的 if,是为了让变异闸门能**考行为**:
        埋在两千行的 finally 里,任何钉死都只能读源码字符串,而读字符串抓不住
        "结构还在、判定反了"(M46a 那一类逃逸)。
        """
        if rv.get("attribution") == "harness":
            return "harness"
        if str(rv.get("reason")) in _HARNESS_SIDE_RECEIPT_REASONS:
            return "harness"
        return "agent"

    def _adoption_failure_type(self, rv: dict) -> str:
        """把红掉的谓词映射成契约已声明的失败类型 —— 归因要能对回 taxonomy。"""
        red = {f["check"] for f in (rv.get("findings") or []) if not f["ok"]}
        if "U2.symbol" in red:
            return "WRONG_UPSTREAM_SYMBOL"
        if "U3.coverage" in red and "U4.adoption" in red:
            return "UPSTREAM_CAPABILITY_REIMPLEMENTED"
        if "U3.coverage" in red:
            return "SYMBOLIC_INVOCATION_ONLY"
        if "U4.adoption" in red:
            return "UPSTREAM_CALLED_BUT_RESULT_UNUSED"
        return "UPSTREAM_CAPABILITY_REIMPLEMENTED"

    def _delivery_dirs(self) -> list[str]:
        """任务声明的交付目录 —— oracle 起跑前由 harness 清场(B5)。

        **由契约/取件器声明,不扫目录**:清场是删除动作,删什么必须写死在
        任务包里,不能从 agent 落盘的东西推断(那是 #43 坑五的翻版)。
        """
        f = self.task_dir / "delivery_extractor.py"
        if not f.is_file():
            return []
        import importlib.util

        spec = importlib.util.spec_from_file_location("rp_delivery_dirs", f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        d = getattr(mod, "JOBS_DIRNAME", None)
        return [d] if isinstance(d, str) and d and "/" not in d and d != "." else []

    def _extract_sidecar_delivery(self, s) -> list | None:
        """紧贴产出取交付 —— 在会话被销毁之前调用。"""
        import importlib.util

        f = self.task_dir / "delivery_extractor.py"
        if not f.is_file() or s is None:
            return None
        spec = importlib.util.spec_from_file_location("rp_delivery_extractor", f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        try:
            return mod.extract(s.root / "host")
        except Exception as e:                                # noqa: BLE001
            # S4 的下半截。取件器现在会把"工件在、但全都读不出来"单独抛出来
            # (`DeliveryExtractionError`);裸 except 吞成 None 的话,它就又变
            # 回含糊的"取不到交付",S4 白修。按类名认 —— 取件器是按路径加载
            # 的,isinstance 对不上(同一个类被加载了两次是两个类)。
            if type(e).__name__ == "DeliveryExtractionError":
                self._delivery_shape_error = str(e)
            return None

    def _verify_sidecar_receipts(self, sess, s, *, delivery=None) -> dict:
        """取交付 + 核验回执。**会话销毁前调用。**

        取件器由任务包提供(`delivery_extractor.py`)。没有取件器就判不过 ——
        不猜:一个 sidecar 任务若没说清"交付在哪",那它的采纳根本无从判定,
        而默认放行等于把这道判据整个删掉。
        """
        import importlib.util

        from repoproof.runner import sidecar_session as _ss

        f = self.task_dir / "delivery_extractor.py"
        if not f.is_file():
            return {"ok": False, "reason": "NO_DELIVERY_EXTRACTOR",
                    "detail": f"任务包没有 {f.name} —— 交付在哪没人说得清,"
                              "采纳无从判定。不猜。"}
        spec = importlib.util.spec_from_file_location("rp_delivery_extractor", f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if delivery is None:
            host = (s.root / "host") if s is not None else None
            try:
                delivery = mod.extract(host) if host is not None else None
            except mod.DeliveryExtractionError as e:
                self._delivery_shape_error = str(e)
        shape_err = getattr(self, "_delivery_shape_error", "")
        if delivery is None and shape_err:
            # 工件在、但全都读不出来 —— 与"目录不在"分开报(S4)。
            return {"ok": False, "reason": "DELIVERY_SHAPE_INVALID",
                    "detail": f"交付工件读不出:{shape_err[:400]}"}
        if delivery is None:
            # 取不到就**把现场说清楚**:是会话没了、目录不在、还是目录空。
            # 含糊的 NO_DELIVERY_EXTRACTED 会让人无从下手,而取件失败与
            # 采纳不成立的修法完全不同。
            host = (s.root / "host") if s is not None else None
            seen = (sorted(x.name for x in host.iterdir())[:20]
                    if host is not None and host.is_dir()
                    else "(会话已销毁或 host 目录不在 —— 多半是取件时机晚了)")
            return {"ok": False, "reason": "NO_DELIVERY_EXTRACTED",
                    "detail": f"取不到交付。host={host};其中有:{seen}"}
        return _ss.verify(sess, task_id=self.contract.task_id, delivery=delivery)

    def _assemble(self, backend: LocalWorktreeBackend, label: str,
                  extra_env: dict[str, str] | None = None) -> _Session:
        """装配一个会话:快照+替身+PII 扫描+上游+公开测试+S0 提交。

        `extra_env` 供 sidecar 拓扑注入端点与令牌(A1)。**缺省 None = 既有
        行为一字不变** —— 新增能力不得改变任何既有任务的会话环境。
        """
        ev = self.store.append_event
        session = backend.start(name_prefix=f"rp-host-{label}", env={
            "PIP_NO_INDEX": "1",
            "PIP_FIND_LINKS": str(self.wheelhouse),
            **(extra_env or {}),
            # A 类只读缓存共享(TESTPLAN §4-3):共享 + 离线开关;假 HOME 不变
            "MODELSCOPE_CACHE": str(Path("~/.cache/modelscope").expanduser()),
            "PYTHONHASHSEED": "0",
        })
        root = backend.session_root(session)
        snap = prepare_host_snapshot(
            self.host_copy, root / "host",
            substitutes=_read_substitutes(self.host_copy))
        pii_scan_note = "user-host"
        if not _pii_scan_required(self.contract):
            # G5:公开 OSS 树按构造不含用户数据(来源 = 封存池,D5 窗口审计
            # 在案);上游夹具的假邮箱会让该闸恒红。跳过要**如实入事件**,
            # 不许静默 —— 跳过和通过在证据里必须长得不一样。
            pii_scan_note = "SKIPPED_PUBLIC_OSS_TREE"
        else:
            pii = scan_for_pii(root / "host")
            if pii:
                backend.destroy(session)
                raise HostRunError(f"PII 出口扫描命中 {len(pii)} 条,拒绝开跑:{pii[:3]}")
        if self.upstream_src is not None:      # G1:delta 形态无上游区
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
        # G6(F0 彩排第 1 抓,2026-08-16):delta 宿主的交付树是纯净 V(无
        # .git —— 字节码条款同源:攻击者视野里也没有);S0 提交机制需要仓,
        # 就地补一个空仓。既有宿主(bench 副本自带 .git)不走此分支。
        if not (root / "host" / ".git").is_dir():
            r = self._git(s, "init", "-q")
            if r.exit_code != 0:
                backend.destroy(session)
                raise HostRunError(f"git init 失败:{r.stderr.decode(errors='replace')[-300:]}")
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
            "pii_scan": pii_scan_note,
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
        """per-run venv 重建(预注册教训:绝不复制)+ 宿主自己的建环境步骤。

        步骤由契约 `host.setup_commands` 声明,缺省 = OfferClaw 现状(逐字节
        不变)。**依赖归因那段仍然只对装依赖的那一步生效** —— 它区分的是
        "轮仓不全(harness)"还是"适配自己加的钉版(agent)",换个宿主这条
        区分照样成立,但只有 pip 那步的输出里才有可解析的分发名。
        """
        cmds = list(self.contract.host.setup_commands)
        if not cmds:
            raise HostRunError(
                "契约没声明 host.setup_commands —— 建环境无从做起。不猜:"
                "怎么装环境是每个宿主的偶然事实,写在 harness 代码里就是"
                "把第一宿主的布局当常量(C 轨勘察实录)")
        t0 = time.monotonic()
        pip_idx = next((i for i, c in enumerate(cmds)
                        if any("pip" in part for part in c)), None)
        # **只跑装依赖之前的那几步。** 第一版写成 `for i, cmd in enumerate(cmds):
        # if i == pip_idx: continue`,于是 pip 之后的步骤被提前跑了 ——
        # OfferClaw 的 `rag_ingest.py` 在装 chromadb 之前执行,当场
        # ModuleNotFoundError。零模型端到端冒烟一把抓住,单测没有(它们不建环境)。
        head = cmds[:pip_idx] if pip_idx is not None else cmds
        for i, cmd in enumerate(head):
            r = s.backend.exec(s.id, cmd, timeout_s=min(timeout_s, 600), workdir="host")
            if r.exit_code != 0:
                raise HostRunError(
                    f"建环境第 {i + 1} 步失败({' '.join(cmd)}):"
                    + (r.stdout + r.stderr).decode(errors="replace")[-300:])
        if pip_idx is None:
            venv_s = round(time.monotonic() - t0, 1)
            return {"venv_s": venv_s, "ingest_s": 0.0}
        r2 = s.backend.exec(s.id, cmds[pip_idx], timeout_s=timeout_s, workdir="host")
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
        for i, cmd in enumerate(cmds[pip_idx + 1:], start=pip_idx + 2):
            r = s.backend.exec(s.id, cmd, timeout_s=600, workdir="host")
            if r.exit_code != 0:
                raise HostRunError(
                    f"建环境第 {i} 步失败({' '.join(cmd)}):"
                    + (r.stdout + r.stderr).decode(errors="replace")[-500:])
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
        if not cmd:
            raise HostRunError("契约没声明 host.regression_command —— 回归跑什么不猜")
        # 原来是 `if cmd[0] == "python" else 退回 pytest tests/`:**静默**退回,
        # 于是契约写了别的命令也照跑 OfferClaw 那条,而报告里看不出差别。
        # 现在只在开头是 "python" 时替换成会话 venv 的解释器,其余原样执行。
        argv = [s.venv_py, *cmd[1:]] if cmd[0] == "python" else list(cmd)
        xml_name = "rp_reg.xml"
        (s.root / xml_name).unlink(missing_ok=True)
        argv = [*argv, "--junitxml", f"../{xml_name}"]
        res = s.backend.exec(s.id, argv, timeout_s=timeout_s, workdir="host",
                             env=self._measure_env(s))
        stdout = res.stdout.decode(errors="replace")
        return {"exit_code": res.exit_code, "stdout": stdout,
                **self._pytest_counts(s, xml_name, stdout)}

    def _meter_env(self, tag: str) -> dict[str, str]:
        """嵌套计量注入(增强③):只对 harness 自己发起的套件生效。"""
        return {"RP_METER_DIR": str(self.store.run_dir / "nested_meter"),
                "RP_METER_TAG": tag}

    def _measure_env(self, s: _Session) -> dict[str, str]:
        """测量跑(回归/公开面)的 PATH 语义(G7)。

        契约声明 path_prepend_venv_bin 时把会话 venv/bin 前置 —— 与准入
        量具 venv_env() 同款(B10),否则钦定套件里裸 `python` 子进程按
        机器巧合红绿。缺省空 dict = 既有行为逐字节不变。oracle 子跑不走
        这里:delta_oracle_lib 自带同款前置。
        """
        if not self.contract.host.path_prepend_venv_bin:
            return {}
        import os as _os

        return {"PATH": f"{s.root / 'host' / '.venv' / 'bin'}:"
                        f"{_os.environ.get('PATH', '')}"}

    def _public_argv(self) -> list[str]:
        """公开面命令 —— **读契约**。

        2026-08-15 之前这里写死 `pytest public_tests/`,而契约的
        `acceptance.public_test_command` 一直躺在那儿没人读:**契约说的和实际
        跑的不是一回事**。现有五个契约声明的与写死的逐字相同(K14 现场比对),
        所以这次改动对 T1–T3 是零行为变化 —— 但第二宿主的公开面在别处。
        """
        cmd = list(self.contract.acceptance.public_test_command)
        if not cmd:
            raise HostRunError("契约没声明 acceptance.public_test_command —— 公开面在哪不猜")
        return cmd[1:] if cmd[:1] == ["python"] else cmd

    def _run_public(self, s: _Session, *, timeout_s: int = 600,
                    meter_tag: str = "public") -> dict:
        xml_path = s.root / "rp_public.xml"
        if xml_path.exists():
            xml_path.unlink()
        res = s.backend.exec(
            s.id,
            [s.venv_py, *self._public_argv(),
             "--junitxml", "../rp_public.xml"],
            timeout_s=timeout_s, workdir="host",
            env={**self._measure_env(s), **self._meter_env(meter_tag)})
        junit = parse_junit_xml(xml_path.read_bytes() if xml_path.exists() else None)
        junit["pytest_exit"] = res.exit_code
        junit["stdout_tail"] = res.stdout.decode(errors="replace")[-600:]
        return junit

    def _oracle_import_env(self, s: _Session) -> dict[str, str]:
        """判卷进程的 **import 面** env(契约 oracle_env_sanitized,blocking [1a])。

        PYTHONPATH 指宿主根时,根下一个 sitecustomize.py 会在**判卷解释器的
        起点**被自动 import(site 处理期,早于 pytest 的一切配置)—— 判卷进程
        一旦被它污染,连 H1 量具面守卫都在被改写的解释器里跑,等于没守。
        声明净化 = 不注 PYTHONPATH 且禁 user-site(usercustomize 同型通道)。
        宿主根**路径**照注(那是数据,不是 import 面),故不在此函数里。
        """
        if self.contract.host.oracle_env_sanitized:
            return {"PYTHONNOUSERSITE": "1"}
        return {"PYTHONPATH": str(s.root / "host")}

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
            env={**self._oracle_import_env(s),
                 # 宿主根。OfferClaw 的 oracle 读 OFFERCLAW_HOST_ROOT,别的宿主
                 # 读别的名字 —— 两个都注,多注一个无害,少注一个会让 oracle
                 # 在自己家里找不到路。
                 "OFFERCLAW_HOST_ROOT": str(s.root / "host"),
                 self.contract.host.host_root_env: str(s.root / "host"),
                 "REPOPROOF_HOST_ROOT": str(s.root / "host"),
                 # A1:oracle 是用**显式 env** 跑的,会话级环境到不了它 ——
                 # 实测踩过:oracle 里 os.environ["REPOPROOF_FIXTURE_URL"]
                 # 直接 KeyError,三条隐藏用例全红,而真因与被测方无关。
                 # sidecar 拓扑的任务,oracle 必须拿得到端点与那批项。
                 **self._sidecar_env_for_oracle(),
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
        # 健康检查由契约 `host.health_checks` 声明。缺省 = OfferClaw 的三条
        # (verify_pipeline 严判 / verify_docs 认 "0 处未围栏" / doctor 不作门禁),
        # 行为逐字节不变。写死在代码里的问题不是"不通用",是**第二宿主每发
        # 都会零预算 BLOCKED 且无旁路** —— 脚本不存在 → exec 127。
        for hc in self.contract.host.health_checks:
            argv = [s.venv_py, *hc.command[1:]] if hc.command[:1] == ["python"] else hc.command
            r = s.backend.exec(s.id, argv, timeout_s=300, workdir="host")
            out = r.stdout.decode(errors="replace")
            # `pass_if_stdout_contains` 是给"退出码非零但已知预期差异"留的口子,
            # **只在契约里显式写出来才生效**(OfferClaw 的 verify_docs 是这种:
            # chunks 交叉核对因合成语料重建必然不一致,而真判据是"0 处未围栏
            # 裸露"不退化 —— 2026-08-09 由首次冒烟 BLOCKED 校准)。
            passed = r.exit_code == 0 or (
                bool(hc.pass_if_stdout_contains) and hc.pass_if_stdout_contains in out)
            name = " ".join(hc.command[-1:]) or " ".join(hc.command)
            report[name] = {"exit_code": r.exit_code, "passed": passed,
                            "gating": hc.gating, "tail": out[-300:]}
            if hc.gating:
                ok = ok and passed
        return ok, report

    # ------------------------------------------------------------ diff 计量
    def _diff_stats(self, s: _Session, base: str, head: str = "HEAD") -> dict:
        num = self._git(s, "diff", "--numstat", f"{base}..{head}")
        # S6:**交付工件不计入补丁预算**。
        #
        # 它们是任务要求落盘的产物(契约 R8),不是"改动"。每自测一次多一个
        # 文件,十来次就撞 `max_patch_files` —— 而公开面本来就是让它自测的。
        #
        # 排除集**只能来自任务包声明**(`delivery_extractor.JOBS_DIRNAME`),
        # 不做通配、不从 agent 落盘的任何东西推断 —— 后者是 #43 坑五的翻版:
        # 判据锚在 SUT 能自己供的名字上,它随便建个目录就能把改动藏进去。
        skip = tuple(f"{d}/" for d in self._delivery_dirs())
        files: list[str] = []
        lines = 0
        for row in num.stdout.decode(errors="replace").splitlines():
            parts = row.split("\t")
            if len(parts) != 3:
                continue
            a, d, path = parts
            if skip and path.startswith(skip):
                continue
            files.append(path)
            lines += (int(a) if a.isdigit() else 0) + (int(d) if d.isdigit() else 0)
        return {"files": files, "total_files": len(files), "total_lines": lines}

    # ------------------------------------------------------------------ 主流程
    def _run_dsh_round(self, s, idx: int, prompt: str, b: "HostBudgets",
                       provider) -> tuple["AgentRunResult", dict]:
        """B-dsh 臂一轮的 runner 壳:调模块级 run_dsh_round,当场把回执两件
        (events 汇、worker result)拷进 run_dir(会话树随 run 清理,证据
        不能跟着走),并对本轮做 treatment fidelity 判读(阶段 8,§17.3)。
        """
        from repoproof.agents.dsh_bridge import (
            fidelity_verdict,
            treatment_fidelity,
        )

        result, info = run_dsh_round(
            workspace=s.root, side_dir=s.root.parent / f"_dsh_round{idx}",
            prompt=prompt, budgets=b, model_name=provider.model_name,
            api_base=provider.api_base, api_key=provider.api_key,
            runtime_root=getattr(self, "_dsh_runtime_root", None),
            request_timeout_s=call_timeout_s(),
        )
        ev_src = Path(info["events_path"])
        if ev_src.exists():
            shutil.copy2(ev_src, self.store.run_dir / f"dsh_events_round{idx}.jsonl")
        (self.store.run_dir / f"dsh_result_round{idx}.json").write_text(
            json.dumps({"attribution": info["attribution"],
                        "result": info["report"].result,
                        "counters": info["counters"], "usage": info["usage"],
                        "selfcheck_problems": info["selfcheck_problems"],
                        "trace_problems": info["trace_problems"],
                        "killed": info["report"].killed,
                        "orphan_count": info["report"].orphan_count},
                       ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8")
        # 送达判读:①②③对照准入时算的组合指纹(预注册冻结值的批层复核在
        # 批分析做);⑦的"本批已见"目前是"本发已见"(跨轮不许复用会话)。
        missing = treatment_fidelity(
            report=info["report"], fingerprint=info["fingerprint"],
            expected_fingerprint=getattr(self, "_dsh_composition",
                                         info["fingerprint"]),
            budget=info["budget"], host_budgets=b,
            seen_session_ids=set(getattr(self, "_dsh_session_ids", [])),
            job=info["job"], expected_workspace=s.root)
        if info["session_id"]:
            self._dsh_session_ids.append(info["session_id"])
        self._dsh_fidelity_missing.extend(m for m in missing
                                          if m not in self._dsh_fidelity_missing)
        info["fidelity_missing"] = missing
        info["fidelity_verdict"] = fidelity_verdict(missing)
        self.store.append_event("dsh.round", actor="harness", payload={
            "round": idx, "attribution": info["attribution"],
            "session_id": info["session_id"], "usage": info["usage"],
            "logical_requests": info["counters"].get("logical_requests"),
            "fidelity_missing": missing})
        return result, info

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
        # WH 两臂:guided 臂 `effective_budgets` 恒等返回契约原对象,故本行
        # 对既有全部发次是恒等变换(任务包一字不动,§39)。最小臂在此换算
        # 成"单轮 × 等总额",此后全流程(提示、step_limit、RepairLoop、
        # 指纹、台账)共用这一份 —— 生效值只有一个来源。
        self._harness_mode = harness_mode()
        b = effective_budgets(contract.budgets, self._harness_mode)
        # 冒烟发次的名字带上**跑的是哪一个脚本**。原来全叫 `fake-scripted`,
        # 于是台账里 `--fake noop`、`--fake positive`、七个负控长得一模一样 ——
        # "冒烟 10 发通过 4 发"这句话说不出任何东西。前缀仍是 `fake`,
        # `SMOKE_MODEL_PREFIX` 的扣除照旧生效(它用的是 startswith)。
        model_name = (provider.model_name if provider
                      else f"fake-scripted:{self._fake_mode}" if self._fake_mode
                      else "fake-scripted")
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
        self._delivery_shape_error = ""  # S4:每发次清空,免得上一发的错串过来
        sidecar_sess = None            # A1:仅 sidecar 拓扑的任务会起
        delivery_snapshot: list | None = None
        adoption_vr: VerificationResult | None = None
        receipt_verification: dict | None = None
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

            # ---- A1:sidecar 拓扑的任务,发次期由 harness 起上游 ----
            #
            # 只对声明了 sidecar 的任务生效;in-process 任务走原路,
            # 一个字节都不变(§2 规则 5 的延伸:加一条新路,不动老路)。
            from repoproof.execution.runtime_profiles import profile_of_contract

            _rt = profile_of_contract(self.contract)
            if _rt.topology == "sidecar":
                from repoproof.runner import sidecar_session as _ss

                sidecar_sess = _ss.start(profile=_rt, run_id=self.run_id,
                                         run_dir=self.store.run_dir)
                self._sidecar_sess = sidecar_sess
                ev("sidecar.started", actor="harness",
                   payload={"profile_id": _rt.id, "items": len(sidecar_sess.items),
                            "fixture": sidecar_sess.fixture_url})

            s = self._assemble(backend, "agent",
                               extra_env=(sidecar_sess.agent_env()
                                          if sidecar_sess else None))
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
            if model_factory is None and getattr(self, "_backend", "mini-swe") == "dsh":
                # B-dsh 臂(阶段 8):宿主侧不建模型对象 —— agent 环归封存
                # worker,预算由父侧 watchdog 执法(dsh_backend),token 记账
                # 从可信 events 汇回填。provider 准入照走(模型身份与费率面
                # 和 H0 同源);key 只在内存传给 worker 环境(allowlist 之外
                # 全拦),不进 os.environ、不落 argv/日志。
                assert provider is not None and preflight is not None
                # 写成 ptype 中转不是风格偏好:M75l 变异钉的旧串是
                # `if provider.PROVIDER_TYPE != "deepseek-native":`,同文重现
                # 会破坏登记簿"旧串恰一次"的可变异性。
                ptype = provider.PROVIDER_TYPE
                if ptype != "deepseek-native":
                    raise ValueError(
                        f"B-dsh 桥接臂只接 deepseek-native provider,实得 "
                        f"{ptype!r} —— DSH runtime 只说 DeepSeek "
                        "协议,换通道 = 换了被测组合")
                from repoproof.agents.dsh_bridge import (
                    DEFAULT_RUNTIME_ROOT,
                    bridge_budget,
                    composition_fingerprint,
                )

                # 两道 fail-fast 都要在建会话之前:per_round 语义拒绝
                # (等总额无从定义)与 cordis 现物校验(封存被动过就不开跑)。
                bridge_budget(b)
                self._dsh_runtime_root = Path(
                    _os.environ.get("REPOPROOF_DSH_RUNTIME_ROOT",
                                    str(DEFAULT_RUNTIME_ROOT))).expanduser()
                self._dsh_composition = composition_fingerprint(
                    self._dsh_runtime_root, model=provider.model_name)
                self._dsh_session_ids: list = []
                self._dsh_fidelity_missing: list = []
                model = None
            elif model_factory is None:
                assert provider is not None and preflight is not None
                _os.environ.setdefault("MSWEA_COST_TRACKING", "ignore_errors")
                # litellm DEV 模式 import 时会把 CWD .env 全量 load_dotenv
                # 进程 env(秘密静默入环境,配置来源失守)。Gate 4A:官方
                # 运行只读宿主显式 env —— 生产侧钉死 PRODUCTION。
                _os.environ.setdefault("LITELLM_MODE", "PRODUCTION")
                if provider.PROVIDER_TYPE != "deepseek-native":
                    # openai-compatible 通道才喂 OPENAI_* env;deepseek 的
                    # key 绝不进错通道的变量(下方分支自设 DEEPSEEK_*)。
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
                # 流式双终态事件按请求去重见 make_usage_cb 文档串。
                _litellm.success_callback = [make_usage_cb(token_totals)]
                _cto = call_timeout_s()          # 修订⑤:单调用超时
                if provider.PROVIDER_TYPE == "deepseek-native":
                    # P-D 直连通道:key/base 走 env(serialize 永不落盘),
                    # 旋钮由 provider 哈希层背书(build_model_kwargs 同源)。
                    from repoproof.agents.deepseek_native import (
                        DeepSeekNativeModel,
                        build_model_kwargs,
                    )

                    _os.environ["DEEPSEEK_API_KEY"] = provider.api_key
                    _os.environ["DEEPSEEK_API_BASE"] = provider.api_base
                    inner_model = DeepSeekNativeModel(
                        model_name=f"deepseek/{provider.model_name}",
                        model_kwargs=build_model_kwargs(provider, _cto),
                        reasoning_passback=provider.reasoning_passback,
                    )
                else:
                    model_cls = (LitellmTextbasedModel
                                 if preflight.action_protocol == "textbased" else LitellmModel)
                    mkwargs = {"temperature": 0} if preflight.temperature == "0" else {}
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
                        projector=projector_or_none(),
                        on_projection=lambda mf: ev("projection.applied", actor="harness",
                                                    payload=mf),
                    )

                model = make_budget_model(token_totals)   # total 语义:全程一个额度
            else:
                model = model_factory(token_totals)

            base_prompt = build_host_prompt(
                contract, wheel_note=f"wheelhouse {self.wheelhouse.name}",
                budgets=b)
            prompt_sha = sha256_bytes(base_prompt.encode())
            ev("agent.prompt", actor="harness",
               payload={"sha256": prompt_sha, "chars": len(base_prompt)})

            repair_dir = self.store.run_dir / "repair"
            repair_dir.mkdir(exist_ok=True)
            metrics_acc = {"model_calls": 0, "commands": 0, "denied": 0}
            # B-dsh 臂逐轮回执。挂 self 而非局部:记录装配在 _finish(另一个
            # 方法),局部名过不去 —— DQ-SDK-1 发 1 实测在收尾 NameError,
            # 链条全走完只差落账(2026-08-18,预注册附录二)。
            dsh_round_infos: list[dict] = []
            self._dsh_round_infos = dsh_round_infos
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
                    + round_guidance(self._harness_mode, idx=idx,
                                     max_rounds=b.max_rounds, marker=SCOPE_MARKER)
                    + render_packets(packets)
                )
                # H1(LESSONS #33):env.denied_count 是会话生命周期累计值;
                # 排序只许看**本轮增量**,否则一轮违规拖累后续所有轮。
                denied_before = env.denied_count
                if getattr(self, "_backend", "mini-swe") == "dsh":
                    # B-dsh 臂:agent 环归封存 worker;token 记账回填自可信
                    # events 汇(worker 自述不算数)。dsh 臂只走 total 语义
                    # (准入时 bridge_budget 已把 per_round 拒了),故写
                    # token_totals 即写本轮桶。
                    result, dsh_round = self._run_dsh_round(
                        s, idx, round_prompt, b, provider)
                    dsh_round_infos.append(dsh_round)
                    absorb_dsh_usage(token_totals, dsh_round.get("usage") or {})
                else:
                    mback = MiniSWEBackend(
                        model=round_model, env=env,
                        step_limit=step_limit,
                        cost_limit=Budgets().monetary_soft_cap_usd,
                        output_path=self.store.run_dir / f"trajectory_round{idx}.json",
                    )
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
                    # dsh 臂的命令数来自 trace 的 bash tool/call 计数 —— env
                    # 不在那条臂上跑命令,读它就是拿 0 冒充测量值。
                    metrics_acc["commands"] = (
                        metrics_acc["commands"] + result.commands_used
                        if getattr(self, "_backend", "mini-swe") == "dsh"
                        else env.commands_used)
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
                # skipped ≠ failed(2026-08-16,HB pilot 首发当场抓出)。
                # 原式 `outcome != "passed"` 把 **skipped 也算成失败**:click
                # 上游套件有 26 个 Windows-only 用例在 macOS 恒 skip,于是每轮
                # 凭空生成 26 个 FailurePacket 喂给模型("修好 getchar windows"
                # ——在 macOS 上无从修起),模型拿真预算去追不存在的失败。
                # 为什么第一宿主没炸:OfferClaw 的公开面是手写的
                # `public_tests/`(0 skip),HB 的公开面是**上游自带回归套件**
                # (25-26 skip)—— 又一次"首宿主上成立的假设换棵树就失效",
                # 与本日两条 blocking 同科。
                # 不开新洞:skip 只能由改 tests/ 或根 conftest 制造,二者都在
                # 契约 forbidden 里先教、且被 H1 逐字节守卫与 tampered_public
                # _tests 双杀 —— 排除 skipped 不给"跳过即隐身"留路。
                split = split_public_outcomes(nodes)
                failed_nodes = list(split.failed_nodes)
                details = dict(split.details)
                passed, skipped = split.passed, split.skipped

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
                    public_skipped=skipped,
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
                    "public_skipped": skipped,
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
                    provider_type=provider_label(provider),
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
            # ---- A1:oracle 起跑前的两件事(2026-08-15 可搬运性审查)----
            if sidecar_sess is not None:
                # B4:**现摇一批 agent 从没见过的项**。砍掉环境变量只挡住
                # "直接读";还得挡住"猜" —— oracle 构造 URL 的写法与 harness
                # 生成项的写法逐字相同,agent 在 round-1 就能算出将来要抽哪些
                # 页面、提前各调一次、把事实写死进源码,交付代码一次 RPC 不发
                # 而四道谓词全绿。项一换,预取的字典必然在 U3 上红。
                sidecar_sess.rotate_items()
                # B5:**清掉早轮残留的交付工件**(误杀侧)。取件器把
                # `page_facts_jobs/` 下全部 json 一网打尽,而每轮 `git add -A`
                # 会把它们变成 tracked 文件长久留在工作区。修复循环的全部意义
                # 就是允许 round-1 是错的:round-1 落 2 条坏事实、round-3 改对
                # 再落 2 条好的,终局取件把 4 条一起交上去 → U4 红,措辞与
                # "调了但没用"一字不差,而最终交付物其实是完美的。
                # 契约里没有一个字说"清理旧作业",oracle 全绿也不给反馈,
                # 判死发生在 agent 看不见的 harness 侧 —— 那正是循环与闸门
                # 不对齐(常设纪律)。清场是纯 harness 动作,不改 patch。
                for _d in self._delivery_dirs():
                    s.backend.exec(s.id, ["rm", "-rf", _d],
                                   timeout_s=60, workdir="host")

            cap_run = self._run_oracle(s, oracle_snap)

            # S3:**交付要在 oracle 之后、宿主回归之前取。**
            #
            # `_run_regression` 跑的是 agent 可写的 `tests/`,而每一次 exec 都
            # 带着 sidecar 令牌 —— 于是存在一个窗口:API 只返回占位串骗过
            # oracle,再由 `tests/` 下一个必过的测试在这个窗口里调 sidecar 把
            # 工件补写出来,U1–U4 全绿。取件绑到 oracle 的观察窗口上,那条路
            # 就断了:oracle 看见什么,采纳就判什么。
            if sidecar_sess is not None and s is not None:
                delivery_snapshot = self._extract_sidecar_delivery(s)
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
            # A1:**在销毁 agent 会话之前**把交付取出来。
            # 实测踩过:原本放在最外层 finally 里,而 clean replay 会先
            # `backend.destroy(s.id); s = None`,等到 finally 时 host 目录
            # 早没了 —— 报出来是 "host=None",看起来像交付不存在,实则是
            # 取件时机错了。**取件必须紧贴产出,不能等到清场之后。**
            # 兜底:上面那次没取到(例如 oracle 早退)时再试一次。
            # **正常路径不走这里** —— 走到这里说明 oracle 那次是空的。
            if sidecar_sess is not None and s is not None and delivery_snapshot is None:
                delivery_snapshot = self._extract_sidecar_delivery(s)

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
                provider_type=provider_label(provider),
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
                provider_type=provider_label(provider),
                preflight=preflight, budget_exhausted=None,
                gate_reasons=["HOST_BASELINE_UNHEALTHY:宿主基线不达标,未消耗任何模型预算"],
                t0=t0)
        finally:
            # A1:**会话销毁之前**取交付并核验回执 —— 销毁之后就取不到了。
            # 放在 finally 里是为了任何路径都会跑到;主成功路径的 return 在
            # 本 finally 之后,所以 `receipt_verification` 赶得上进报告。
            if sidecar_sess is not None:
                try:
                    receipt_verification = self._verify_sidecar_receipts(
                        sidecar_sess, s, delivery=delivery_snapshot)
                    ev("sidecar.receipts_verified", actor="harness",
                       payload={"ok": receipt_verification.get("ok"),
                                "reason": receipt_verification.get("reason", "")})
                    if not receipt_verification.get("ok"):
                        # S2:**按归因分流**,不再一律走 missing_external。
                        #
                        # 那条通道会短路成 BLOCKED,与"profile 没登记""宿主
                        # 基线不健康"同桶 —— 而这道题存在的全部理由就是把
                        # "没真用上游"判成**被测方失败**。一判出来就被塞进
                        # "不算模型失败、可重跑"的那格,等于白判。
                        #
                        # harness 侧的问题(取件器缺失、核验器出错、上游自己
                        # 崩了)仍走 missing_external —— 那些**确实**不是被测方
                        # 的错,BLOCKED 是对的。
                        _reason = str(receipt_verification.get("reason"))
                        if self._receipt_failure_side(receipt_verification) == "harness":
                            missing_external.append(
                                "RECEIPT_VERIFICATION_FAILED:" + _reason)
                        else:
                            adoption_vr = VerificationResult(
                                verifier="AdoptionVerifier", passed=False,
                                detail=str(receipt_verification.get("findings")
                                           and _adoption_detail(receipt_verification)
                                           or _reason),
                                extra={"attribution": "agent",
                                       "failure_type": self._adoption_failure_type(
                                           receipt_verification),
                                       "reason": _reason})
                except Exception as exc:                          # noqa: BLE001
                    # 核验本身出错 ≠ 核验不通过。混同会把 harness 的毛病
                    # 记成被测方的失败,而两者修法完全不同。
                    receipt_verification = {
                        "ok": False, "reason": "RECEIPT_VERIFIER_ERROR",
                        "detail": f"{type(exc).__name__}: {exc}"}
                    missing_external.append("RECEIPT_VERIFIER_ERROR")
                finally:
                    sidecar_sess.shutdown()
                    self._sidecar_sess = None
            if s is not None and not keep_session:
                backend.destroy(s.id)

        # ---------------- Completion Gate ----------------
        for r in (cap, reg, pol) + ((rep,) if rep else ()):
            self.store.save_verification(r)
            ev("verification.result", actor=r.verifier,
               payload={"passed": r.passed, "detail": r.detail})
        # S2:采纳不成立 = **被测方失败**,并进 capability 侧。
        #
        # 不并进去的话,gate 只看得见 oracle 的绿 —— 而 oracle 只验行为,
        # 它给绿不代表用了上游。合成一条新的 capability 结果,detail 里
        # 两边都写清楚,`extra` 带上归因与 taxonomy 类型。
        if adoption_vr is not None:
            cap = VerificationResult(
                verifier="capability+adoption", passed=False,
                detail=(f"{cap.detail if cap else 'not_run'} | "
                        f"采纳不成立:{adoption_vr.detail}"),
                extra={**(dict(cap.extra) if cap and cap.extra else {}),
                       **dict(adoption_vr.extra)})
            self.store.save_verification(adoption_vr)

        gate = completion_gate.decide(
            capability=cap, regression=reg, policy=pol, replay=rep,
            adaptation=adaptation_manifest,
            missing_external=missing_external, budget_exhausted=budget_exhausted)
        ev("gate.verdict", actor="completion-gate", payload=gate.model_dump(mode="json"))
        verdict_record = {
            "verdict": gate.verdict.value,
            "gate_reasons": gate.reasons,
            "receipt_verification": receipt_verification,
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
            provider_type=provider_label(provider),
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
        model_name: str, provider_type: str,
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
            "source_commit": source_commit_of(self.contract),
            "model": model_name,
            # 通道归属来自 ProviderConfig.PROVIDER_TYPE,不许写死 ——
            # deepseek 发次记成 openai-compatible 就是"跑的通道和台账
            # 写的通道不是一个"(M75i 的台账端;M76a 在钉)。
            "provider": provider_type,
            "provider_config_hash": (preflight.provider_config_sha256
                                     if preflight else "UNKNOWN"),
            # 执行侧四面指纹(S1):provider 面见上一行,其余三面 + 代际 +
            # 代码内容指纹在这里。拆开记是为了 E1 消融能单变量归因 ——
            # 一个大 hash 只说"配置变了",拆开才说"变的是哪一面"。
            **_exec_profile_fields(self.contract, preflight,
                                   effective_budgets(self.contract.budgets,
                                                     getattr(self, "_harness_mode", None)),
                                   backend=getattr(self, "_backend", "mini-swe"),
                                   backend_composition=getattr(
                                       self, "_dsh_composition", None)),
            "run_index": run_index,
            "run_order": run_order,
            # 批次归属:探索性加发打 EXPLORATORY_UNPREREGISTERED,闸门不计
            # (TESTPLAN §8/§9)。缺省 UNKNOWN,历史行无此字段=预注册批次。
            "batch": batch,
            # 宿主身份(C 轨)。阶段闸门是**第一宿主**上的存在性证明,而阶段
            # 归属靠 task_id 前缀 —— 不落这一笔,第二宿主的 `t3-<新宿主>-…`
            # 会自动进 stages.T3。`append_run` 缺它直接拒收。
            "host_id": self.contract.host.repo,
            "guided": True,
            # 生效轮数,不是契约意图值(最小臂恒 1)。guided 臂两者相等,
            # 历史行读数不变。
            "max_rounds": effective_budgets(
                self.contract.budgets, getattr(self, "_harness_mode", None)).max_rounds,
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
            # B-dsh 臂回执(阶段 8):送达判读与逐轮归因入台账 —— 批分析
            # 据此算送达率(<80% 停批),TREATMENT_NOT_DELIVERED 的发次
            # 不得读作 H0/H1 无差异。mini-swe 发次无此键(不写空壳)。
            **({"dsh": dsh_receipt_block(
                getattr(self, "_dsh_fidelity_missing", []),
                getattr(self, "_dsh_round_infos", []))}
               if getattr(self, "_backend", "mini-swe") == "dsh" else {}),
        }
        append_run(self.project_root, record)
        ev("bench.recorded", actor="harness", payload={"runs_jsonl": "benchmarks/v2/runs.jsonl"})
        return report


def provider_label(provider) -> str:
    """台账 provider 归属:通道类型取 ProviderConfig.PROVIDER_TYPE,
    不许写死字面量 —— deepseek 发次记成 openai-compatible 就是"跑的
    通道和台账写的通道不是一个"(静默换模的台账端)。fake 冒烟无
    provider,如实记 fake。"""
    return provider.PROVIDER_TYPE if provider is not None else "fake"


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
    backend: str = "mini-swe",
) -> dict:
    """准入 → 预检 → 宿主级 guided 运行。

    fake:
      None        真实模型(REPOPROOF_API_BASE/KEY/MODEL 环境变量)
      "noop"      fake 模型什么都不做直接提交(FAIL 路径冒烟)
      "positive"  fake 模型脚本化注入正控(PASS 路径冒烟;绝不用于正式 run)
      "control:X" 注入任务包里的控制组 X。负控走完整条链路,用来验判据在
                  **失败侧**的行为 —— 控制矩阵只跑到"红在哪",红之后那段
                  (归因分流 → capability 合并 → gate → verdict → 台账)
                  它一步没走过。
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
        blind: list[str] = []
        residue = reachable_answer_keys(Path(contract_path).parent, blind=blind)
        if residue:
            return {"blocked": True, "agent_model_call_count": 0,
                    "preflight": {"ready": False, "reason": "ANSWER_KEY_REACHABLE"},
                    "answer_key_residue": residue[:20],
                    "remediation": "运行主机上仍可达到正控/负控/任务工程期残留;"
                                   "清掉或移出本机后再开跑(它们在 run 期间没有用途)"}
        if blind:
            return {"blocked": True, "agent_model_call_count": 0,
                    "preflight": {"ready": False, "reason": "ANSWER_KEY_SCAN_BLIND"},
                    "answer_key_scan_blind": blind[:20],
                    "remediation": "扫描根里有列不动的目录,H9-a 无法确立'答案不在盘上';"
                                   "看不见不等于干净。常见是 ~/.Trash(macOS TCC):"
                                   "倒空废纸篓,或给运行终端授予完全磁盘访问权限后重试"}

        provider = provider_from_env()
        pf = run_preflight(provider)
        if not pf.ready:
            return {"blocked": True, "preflight": pf.summary(),
                    "agent_model_call_count": 0}
        runner = HostGuidedRunner(contract_path, project_root, wheelhouse=wheelhouse)
        runner._backend = backend         # B-dsh 臂开关(阶段 8);缺省 mini-swe
        report = runner.run(provider, pf, run_order=run_order, run_index=run_index,
                            batch=batch, keep_session=keep_session)
        return {"blocked": False, "preflight": pf.summary(), "report": report}
    if backend != "mini-swe":
        # fake 通路是 mini-swe 环里的脚本化模型;dsh 臂的四形电池走脚本化
        # 假端点 + 真 worker 环(dsh_fake_provider),是另一条通路 —— 混着
        # 跑会把"判据面自检"记成"dsh 臂发次"。声明式拒绝,不静默换道。
        raise ValueError(
            f"--fake 只走 mini-swe 通路(实得 backend={backend!r});"
            "dsh 臂的 F0 四形走脚本化假端点彩排,不共用 fake 开关")
    runner = HostGuidedRunner(contract_path, project_root, wheelhouse=wheelhouse)
    runner._fake_mode = fake          # 台账里要看得出跑的是哪一个冒烟脚本

    from repoproof.agents.fake_model import FakeModel

    def factory(_totals: dict):
        return FakeModel(script=_fake_script(fake, runner))

    report = runner.run(None, None, model_factory=factory,
                        run_order=run_order, run_index=run_index, batch=batch,
                        keep_session=keep_session)
    return {"blocked": False, "preflight": None, "report": report}


def _fake_setup_steps(src_control: Path) -> list[dict]:
    """冒烟的环境准备步骤:**每任务清单**,不猜(G3 重构时原样搬出,逻辑未动)。

    为什么不能有通用装法(逐条实测,2026-08-14):
      - `pip install -e ../upstream` 对三任务全灭 —— 钉版 wheelhouse 里
        没有 `hatchling`,PEP 517 editable 构建离线起不来;
      - `pip install <distribution>` 只有 T1 碰巧能成 —— wheelhouse 里
        `fastapi_mcp` 有轮子,`open_deep_research` / `browser_use` 各 0 个;
      - T2 即便把上游装进去,`langchain` 伞包仍不在 wheelhouse(只有
        `langchain_core`/`langgraph`),真实通关发次是自己写兼容垫片的;
      - T3 历史 PASS 发次的 pip **每一条都失败**,它是自写 `browser_use/`
        包过的关 —— 那正是 T3v6 要堵的洗白路径,不能当正控范本。

    结论:上游可得性是**每任务的偶然事实**,写在任务包里才对;写在
    harness 代码里,就是原实现"把 T1 的 fastapi-mcp / mcp<2.0 钉死"那个
    病的翻版 —— 只是换了个更体面的形状。

    缺清单 → 显式失败(与缺控制组目录同一条纪律:不猜、不静默降级)。
    """
    steps: list[dict] = []
    setup = src_control / "smoke_setup.txt"
    if not setup.is_file():
        # 负控回落到**正控的**清单。这不是图省事:负控与正控必须在**同一个
        # 环境**里跑,环境不同就不成对照 —— 那样红的可能是环境而不是判据。
        # 所以回落目标只有一个、且是那个唯一的参照系。
        shared = src_control.parent / "positive" / "smoke_setup.txt"
        if shared.is_file():
            setup = shared
    if not setup.is_file():
        raise ValueError(
            f"控制组没有环境清单,冒烟无从做起:{setup}\n"
            "冒烟脚本不替任务猜上游怎么装 —— 钉版可得性是每任务的偶然事实"
            "(实测:editable 装法三任务全灭;pip install <名> 只有 T1 能成)。"
            "请在任务包里写清单,一行一条命令。")
    # `#!BLOCKED: <理由>` —— 该任务的正控在钉版环境下**不可能绿**,冒烟带
    # 诊断拒跑。为什么不是"跑出一发 FAIL 就完了":那会在台账里留下一条
    # 看起来和模型失败同型的记录,而它其实是**环境不可满足**,两者的含义
    # 完全相反(前者说模型不行,后者说这道题在这个环境里没有正确答案)。
    # 格式:命令块之间用单独一行 `---` 分隔(块内保留换行,故 heredoc 可用);
    # 块外的 `#` 开头行是注释。用显式分隔符而不是空行,是因为 heredoc 正文
    # 里本来就可能有空行。
    raw = setup.read_text(encoding="utf-8")
    for line in raw.splitlines():
        if line.strip().startswith("#!BLOCKED:"):
            raise ValueError(
                f"正控在钉版环境下不可满足,冒烟拒跑:{src_control}\n"
                + line.strip()[len("#!BLOCKED:"):].strip())
    for block in raw.split("\n---\n"):
        cmd = "\n".join(ln for ln in block.splitlines()
                        if not ln.lstrip().startswith("#")).strip()
        if cmd:
            steps.append({"actions": [{"command": cmd}]})
    return steps


def _fake_script(kind: str, runner: HostGuidedRunner) -> list[dict]:
    """冒烟脚本。positive 脚本读取**该任务自己的**正控参考实现(harness 侧
    冒烟专用;正式 run 走真实模型,正控内容永不进入其提示或环境)。

    2026-08-14 修:原实现把 T1 的 `sdk_mcp.py` / `mount_sdk_mcp` /
    fastapi-mcp 钉版**写死**,对 T2/T3 直接 FileNotFoundError —— 于是那两
    个任务的 F0 失去真正的正控意义(S1 只能降级用 `--fake noop`)。
    现改为**从任务包发现**:控制组文件名与挂载符号都由 `build_control_tree`
    的同一套发现逻辑给出,依赖钉版则读控制组自带的 `requirements.txt`
    (没有就不装 —— 不猜)。

    **控制组缺失必须显式失败,不得静默退回 noop**:那会让冒烟"通过"而
    其实什么都没验(与 batch_criteria 的"空跑不算通过"同源)。
    """
    if kind == "noop":
        return [{"content": "noop submit",
                 "actions": [{"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"}]}]

    # `control:<名>` —— 把任务包里的**任一**控制组当脚本跑完整条链路。
    #
    # 为什么要有它(2026-08-15,PQ 首批之后):控制矩阵只跑到"判据红在哪",
    # 而红了之后那一段 —— 归因分流 → capability 合并 → completion gate →
    # verdict → 台账 —— **矩阵一步都没走过**。首批四发全过,于是判据在
    # **失败侧**的行为至今零现场实例:S1/S2 那套分流只有合成证据。
    # 负控走完整条链路,是唯一能在不等真实失败的前提下把那段补上的办法。
    #
    # 它**不是**新的判据,也不产生任何模型成绩:model 仍是 `fake-scripted`,
    # 照旧按冒烟从闸门里扣除。
    name = "positive"
    if kind.startswith("control:"):
        name = kind.split(":", 1)[1].strip()
        if not name or "/" in name or name.startswith("."):
            raise ValueError(f"控制组名不合法:{name!r}")
    elif kind != "positive":
        raise ValueError(f"未知 fake 模式:{kind}(noop | positive | control:<名>)")

    src_control = runner.task_dir / "controls" / name
    if not src_control.is_dir():
        avail = sorted(p.name for p in (runner.task_dir / "controls").glob("*")
                       if p.is_dir()) if (runner.task_dir / "controls").is_dir() else []
        raise ValueError(
            f"任务包没有这个控制组,冒烟无从做起:{src_control}\n"
            f"已有:{avail}\n"
            "冒烟必须有真实控制组 —— 拒绝静默退回 noop(那会让冒烟"
            "'通过'而其实什么都没验)")

    def _setup_steps() -> list[dict]:
        return _fake_setup_steps(src_control)

    # G3(HB-PCDELTA-1,2026-08-16):patch 形态。控制组给的是一个现成补丁
    # (controls/<名>/apply.patch),不是"复制 .py + 挂载"。delta 任务的正控
    # = 上游 answer 实现原样施加(测试 hunk 已剥),负控 = 惰性/破坏补丁;
    # 它们没有 mount 符号,也绝不该往 rag_api.py 里追加任何东西 —— 那两步
    # 是第一宿主的形状,硬走会 SystemExit / 污染交付。环境清单纪律照旧
    # (缺清单显式失败;负控回落正控清单)。
    patch_file = src_control / "apply.patch"
    if patch_file.is_file():
        steps = _setup_steps()
        body = patch_file.read_text(encoding="utf-8").rstrip("\n")
        steps.append({"actions": [{"command":
                      "cat > _rp_control.patch <<'RP_PATCH_EOF'\n"
                      + body + "\nRP_PATCH_EOF"}]})
        steps.append({"actions": [{"command":
                      "git apply _rp_control.patch && rm _rp_control.patch"}]})
        steps.append({"actions": [{"command":
                      "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"}]})
        return steps

    # 与 build_control_tree 用同一套挂载发现 —— 两处各写一份必然漂移
    import importlib.util as _iu

    _path = Path(__file__).resolve().parents[3] / "scripts" / "build_control_tree.py"
    _spec = _iu.spec_from_file_location("build_control_tree", _path)
    _bct = _iu.module_from_spec(_spec)
    _spec.loader.exec_module(_bct)
    module, mount_fn, _block = _bct.mount_of(src_control)

    steps = _setup_steps()

    # 落**全部** .py,不只是挂载模块 —— `build_control_tree.build()` 就是
    # `for f in sorted(src_control.glob("*.py"))`。只落一个的话,带辅助模块的
    # 控制组在冒烟里会缺件,而在控制树验证里是齐的:同一个正控,两条路径看到
    # 的东西不一样,冒烟就不再是控制树的现场复现。
    for f in sorted(src_control.glob("*.py")):
        steps.append({"actions": [{"command":
                      f"cat > {f.name} <<'RP_EOF'\n"
                      + f.read_text(encoding="utf-8") + "\nRP_EOF"}]})
    steps += [
        {"actions": [{"command":
                      f"printf '\\nfrom {module} import {mount_fn}\\n"
                      f"{mount_fn}(app)\\n' >> rag_api.py"}]},
        {"actions": [{"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"}]},
    ]
    return steps
