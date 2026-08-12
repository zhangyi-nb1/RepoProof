"""LESSONS #33(约束只筛不教)— 轮内约束反馈的钉死测试。

实录反例(2026-08-12 取证:最新任务版 5 发真实模型失败,全部倒在
"提示里披露过、循环里却从不反馈"的约束上):
- 061522(T2 gpt-5.6):round-1 全绿 + patch 2630 行 > 1800,全绿即停,
  剩余 2 轮全弃,盖棺时政策闸击杀;当轮 failure_packets=[]。
- 181550(T3 gpt-5.5):同型,46 文件 > 25。
- 030156/054108(T3):requirements.txt 钉了离线轮仓解析不到的版本,
  三轮零警告,干净重放击杀。
- 060126(T2 gpt-5.5):round-2 公开 12/12 但 1 条被拒命令 → 静默回滚;
  denied 跨轮累计,round-3 自身零违规仍背着 1,结构性翻不了盘;回滚后
  失败包还是 best 的 failed_nodes 配劣化轮的空 details(9 个空壳包)。

冻结判据:H1 增量语义 / H2 违规成包带具体数字与名字 / H3 fatal 在场
不许全绿停轮 / H4 回滚必说明 + 细节取自恢复快照自己存的。
边界(§39):这些约束在任务提示里本就全文披露,反馈只是把"终局闸门
会说的话"提前到轮间——不是把任务改简单。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.adoption.repair.failure_packet import FailurePacket
from repoproof.adoption.repair.repair_budget import RepairBudget
from repoproof.adoption.repair.repair_loop import (
    STOP_ALL_PUBLIC_PASS,
    STOP_MAX_ROUNDS,
    RepairLoop,
    RoundResult,
    full_score,
)
from repoproof.runner.host_guided import _ROUND_HEADER

# 本修复新增的符号(round_violation_report / ROLLBACK)刻意**不在模块级
# 导入**:模块级导入会让修复前的树整文件收集失败,红绿证据退化成"文件级
# 红"——那只证明特性缺席,证不明每条钉死各自抓住了自己那个缺陷。下沉到
# 函数内,base 上就是逐节点红(LESSONS #34)。

REPO = Path(__file__).resolve().parent.parent
HOST_GUIDED_SRC = (REPO / "src" / "repoproof" / "runner" / "host_guided.py").read_text(
    encoding="utf-8")


# ---------- H2:round_violation_report 纯函数判据 ----------

def test_patch_overage_packet_carries_gate_numbers_and_is_fatal() -> None:
    """超限包必须带终局闸门将使用的同一对数字,且列为 fatal(H3 输入)。
    反例:061522 全绿 2630 行,包列表为空,盖棺时才见 2630 与 1800。"""
    from repoproof.runner.host_guided import round_violation_report

    packets, fatal, pol = round_violation_report(
        denied_delta=0, tampered=[], patch_files=10, patch_lines=2630,
        max_patch_files=20, max_patch_lines=1800, unresolvable_dists=[])
    assert [p.type for p in packets] == ["PATCH_BUDGET_EXCEEDED"]
    assert "2630" in packets[0].summary and "1800" in packets[0].summary
    assert fatal == ["patch_lines"]
    assert pol == 0  # 超重不是对抗性动作,不得毒化排序(冻结语义)


def test_dependency_pin_packet_names_the_dist_and_is_fatal() -> None:
    """反例:030156/054108 声明离线解析不到的钉版,三轮零警告,重放击杀。"""
    from repoproof.runner.host_guided import round_violation_report

    packets, fatal, pol = round_violation_report(
        denied_delta=0, tampered=[], patch_files=1, patch_lines=10,
        max_patch_files=20, max_patch_lines=1800,
        unresolvable_dists=["browser-use"])
    assert packets[0].type == "DEPENDENCY_NOT_REPRODUCIBLE"
    assert "browser-use" in packets[0].summary
    assert "dependency" in fatal
    assert pol == 0


def test_ranking_counts_only_what_the_final_gate_kills() -> None:
    """LESSONS #35:排序只对齐终局判据。tampered 计入(终局以
    PUBLIC_TESTS_TAMPERED 树哈希击杀),denied 不计入(终局
    policy_result 根本不数它)——但两者都要成包教学。
    反例:order-53 round-3 公开 21/23 仅因一条零执行的 `sh -c` 调试命令
    被拦而整轮回滚,最终交付 round-2 的 3/23;060126 同因弃掉 12/12。"""
    from repoproof.runner.host_guided import round_violation_report

    packets, fatal, pol = round_violation_report(
        denied_delta=2, tampered=["public_tests/test_x.py"], patch_files=1,
        patch_lines=10, max_patch_files=20, max_patch_lines=1800,
        unresolvable_dists=[])
    assert pol == 1, "只有 tampered 计入排序"
    assert fatal == []
    assert {p.type for p in packets} == {"POLICY_VIOLATION", "SCOPE_EXCEEDED"}

    # 纯 denied 轮:成包教学,但排序不受损(否则好轮被无害拦截毁掉)
    dpackets, dfatal, dpol = round_violation_report(
        denied_delta=3, tampered=[], patch_files=1, patch_lines=10,
        max_patch_files=20, max_patch_lines=1800, unresolvable_dists=[])
    assert dpol == 0 and dfatal == []
    assert [p.type for p in dpackets] == ["POLICY_VIOLATION"]
    assert "3" in dpackets[0].summary

    assert round_violation_report(
        denied_delta=0, tampered=[], patch_files=1, patch_lines=10,
        max_patch_files=20, max_patch_lines=1800,
        unresolvable_dists=[]) == ([], [], 0)


def test_denied_round_can_still_win_on_pass_count() -> None:
    """端到端语义:一条被拒命令不再让高分轮输给低分干净轮。
    **policy_violations 必须由真判据引擎算出**——手填 0 等于把结论写进
    前提,那样的钉死在未修复的树上也绿(红绿工具首咬,已实证)。
    反例(order-53 实录):[3, 3, 21] 的第 3 轮因 denied=1 被回滚,
    best 落回 3/23。"""
    from repoproof.runner.host_guided import round_violation_report

    def _round(snapshot: str, passed: int, denied: int) -> RoundResult:
        packets, fatal, pol = round_violation_report(
            denied_delta=denied, tampered=[], patch_files=1, patch_lines=10,
            max_patch_files=20, max_patch_lines=1800, unresolvable_dists=[])
        return RoundResult(adapter_snapshot=snapshot, passed=passed,
                           failed_nodes=["t::x"], policy_violations=pol,
                           violation_packets=packets, fatal_violations=fatal)

    rounds = [_round("r1", 3, 0), _round("r2", 21, 1)]

    def run_round(idx, packets, best_snapshot):
        return rounds[idx - 1]

    out = RepairLoop(run_round, budget=RepairBudget(max_rounds=2),
                     score_fn=full_score).run()
    assert out.best_round == 2 and out.best_passed == 21
    assert out.rolled_back_rounds == []
    # 教学面仍在:被拒命令照样成包
    assert any(p.type == "POLICY_VIOLATION" for p in rounds[1].violation_packets)


# ---------- H3:fatal 在场不许全绿停轮 ----------

def _green(snapshot: str, *, diff: int = 100,
           fatal: list[str] | None = None,
           vp: list[FailurePacket] | None = None) -> RoundResult:
    return RoundResult(adapter_snapshot=snapshot, passed=12, failed_nodes=[],
                       diff_lines=diff, violation_packets=vp or [],
                       fatal_violations=fatal or [])


def test_green_round_with_fatal_violation_keeps_looping() -> None:
    """全绿 + fatal 在场 → 不停轮,下一轮提示里能看到超限包;修剪后
    fatal 清零才停。反例:061522/181550/054108 全部 rounds_run=1/3。"""
    over = FailurePacket(type="PATCH_BUDGET_EXCEEDED",
                         summary="adaptation lines 2630 > max_patch_lines 1800",
                         suggestion="trim the diff")
    rounds = [
        _green("r1", diff=2630, fatal=["patch_lines"], vp=[over]),
        _green("r2", diff=1500),
    ]
    seen: list[list[FailurePacket]] = []

    def run_round(idx, packets, best_snapshot):
        seen.append(list(packets))
        return rounds[idx - 1]

    # max_diff_lines 给足空间:本测针对停轮逻辑;diff 兜底见下一条钉死
    out = RepairLoop(run_round,
                     budget=RepairBudget(max_rounds=3, max_diff_lines=5400),
                     score_fn=full_score).run()
    assert out.rounds_run == 2
    assert out.stop_reason == STOP_ALL_PUBLIC_PASS
    assert out.best_round == 2
    # H2(循环层):round-2 的进包含具体的超限说明
    assert any(p.type == "PATCH_BUDGET_EXCEEDED" for p in seen[1])


def test_loop_diff_backstop_leaves_room_for_trimming() -> None:
    """H3 级联钉死:宿主接线里循环的 max_diff_lines 只作兜底(×轮数),
    否则超重全绿轮刚被 fatal 拦下,就会在循环预算检查处以
    budget_exhausted 断轮——修剪机会照样丢,H3 形同虚设。
    首咬:本文件上一条测试初版用默认预算,实测停在 budget_exhausted。"""
    assert "max_diff_lines=b.max_patch_lines * b.max_rounds" in HOST_GUIDED_SRC


def test_green_with_fatal_on_last_round_stops_at_max_rounds() -> None:
    """fatal 挡住全绿停轮,但轮次上限仍是硬墙——不得死循环。"""

    def run_round(idx, packets, best_snapshot):
        return _green("r1", diff=2630, fatal=["patch_lines"])

    out = RepairLoop(run_round, budget=RepairBudget(max_rounds=1),
                     score_fn=full_score).run()
    assert out.rounds_run == 1
    assert out.stop_reason == STOP_MAX_ROUNDS


# ---------- H4:回滚必须被解释,细节取恢复快照自己的 ----------

def test_rollback_is_explained_and_details_come_from_restored_round() -> None:
    """回滚后下一轮必有 ROLLBACK 包(哪轮、为何、恢复到哪),失败包配
    恢复快照**自己**的断言细节。反例:060126 round-3 收到 round-1 的
    failed_nodes × round-2 的空 details,无一字提及回滚。"""
    from repoproof.adoption.repair.failure_packet import ROLLBACK

    denied = FailurePacket(
        type="POLICY_VIOLATION",
        summary="1 command(s) were DENIED by the policy guard this round",
        suggestion="stay inside the allowed paths")
    rounds = [
        RoundResult(adapter_snapshot="r1", passed=3, failed_nodes=["t::alpha"],
                    failure_details={"t::alpha": "expected alpha == beta"}),
        RoundResult(adapter_snapshot="r2", passed=12, failed_nodes=[],
                    policy_violations=1, violation_packets=[denied]),
        RoundResult(adapter_snapshot="r3", passed=12, failed_nodes=[]),
    ]
    seen: list[list[FailurePacket]] = []

    def run_round(idx, packets, best_snapshot):
        seen.append(list(packets))
        return rounds[idx - 1]

    out = RepairLoop(run_round, budget=RepairBudget(max_rounds=3),
                     score_fn=full_score).run()
    assert 2 in out.rolled_back_rounds
    assert out.stop_reason == STOP_ALL_PUBLIC_PASS  # round-3 干净全绿收尾
    r3_packets = seen[2]
    rb = [p for p in r3_packets if p.type == ROLLBACK]
    assert len(rb) == 1
    assert "round-2" in rb[0].summary and "round 1" in rb[0].summary
    assert "DENIED" in rb[0].actual          # 回滚原因携带违规明细
    others = [p for p in r3_packets if p.type != ROLLBACK]
    assert any("alpha == beta" in p.actual for p in others)  # best 自己的细节


# ---------- H1/H2 接线(源码钉死,基线树必红) ----------

def test_run_round_uses_per_round_denied_delta() -> None:
    """H1:排序只看本轮增量;旧累计写法绝迹。反例:060126 round-3
    自身零违规却 pol=1(继承 round-2),永远输给干净的 round-1。"""
    assert "denied_before = env.denied_count" in HOST_GUIDED_SRC
    assert "denied_round = env.denied_count - denied_before" in HOST_GUIDED_SRC
    assert "env.denied_count + len(tampered)" not in HOST_GUIDED_SRC
    assert HOST_GUIDED_SRC.count("policy_violations=pol_count") == 2  # rr + record


def test_run_round_probes_requirements_against_offline_resolver() -> None:
    """H2(依赖面):动过 requirements.txt 的轮在会话内离线 dry-run,
    失败按基线归因剥出 agent 新增钉版并留痕。

    2026-08-13 判据升级(#38):原判据是"added_unresolvable_dists 出现
    ≥3 次"——一个**代理量**。归因函数改名换代后它就假红,而真正要钉的是
    "探针在跑、结果进 trace、归因走基线比对"这三件事,故改为直接断言。"""
    assert '"--dry-run"' in HOST_GUIDED_SRC
    assert '"repair.dependency_probe"' in HOST_GUIDED_SRC
    assert "self._baseline_dists()" in HOST_GUIDED_SRC
    assert 'workdir="host")' in HOST_GUIDED_SRC


def test_round_record_ledger_carries_violation_packets() -> None:
    """违规包必须同时进**轮次账本**:agent 看得到(提示),我事后复核也
    看得到(record.json)。只进提示不进账本 = 无从取证。"""
    assert "for p in (*packets_next, *violation_packets)" in HOST_GUIDED_SRC


def test_round_header_discloses_violation_feedback() -> None:
    """公开面=目标函数(LESSONS #17):包内容扩到政策/预算/依赖违规与
    回滚说明,轮头承诺文本必须一致,不得再写 "only"。"""
    assert "policy/budget/dependency violations" in _ROUND_HEADER
    assert "ROLLBACK" in _ROUND_HEADER


# ---------- LESSONS #37:修剪轮必须能赢下超重轮 ----------

def test_trimmed_round_beats_oversized_round_on_equal_passes() -> None:
    """H3 的闭环:同样 12/12,一个 2682 行超限、一个 325 行合规 →
    best 必须是合规那轮。反例(order-57 实录):两轮 score 逐位相等
    判平局,"先到先得"选中超重轮,终局以
    `adaptation lines 2682 > max_patch_lines 1800` 击杀——循环做完了
    修剪又把成果扔了。"""
    from repoproof.runner.host_guided import host_score

    fat = RoundResult(adapter_snapshot="r2", passed=12, failed_nodes=[],
                      diff_lines=2682, fatal_violations=["patch_lines"])
    trim = RoundResult(adapter_snapshot="r3", passed=12, failed_nodes=[],
                       diff_lines=325, fatal_violations=[])
    assert host_score(trim) > host_score(fat)

    seq = [fat, trim]

    def run_round(idx, packets, best_snapshot):
        return seq[idx - 1]

    out = RepairLoop(run_round,
                     budget=RepairBudget(max_rounds=2, max_diff_lines=5400),
                     score_fn=host_score).run()
    assert out.best_round == 2 and out.final_adapter == "r3"


def test_compliance_never_outranks_test_progress() -> None:
    """合规位排在通过数**之后**:不许拿"少改点"去换测试进度。
    这正是 2026-08-09 run -211400 的老病(同分取小 diff 把脚手架
    中间态当退步),不得因 #37 复发。"""
    from repoproof.runner.host_guided import host_score

    clean_but_weak = RoundResult(adapter_snapshot="a", passed=3,
                                 diff_lines=50, fatal_violations=[])
    strong_but_fat = RoundResult(adapter_snapshot="b", passed=11,
                                 diff_lines=2600, fatal_violations=["patch_lines"])
    assert host_score(strong_but_fat) > host_score(clean_but_weak)


def test_equal_rounds_without_fatal_keep_first_come_first_served() -> None:
    """无 fatal 时行为不变:逐位相等 → 先到先得(F8 语义不回退)。"""
    from repoproof.runner.host_guided import host_score

    a = RoundResult(adapter_snapshot="a", passed=9, diff_lines=100)
    b = RoundResult(adapter_snapshot="b", passed=9, diff_lines=40)
    assert host_score(a) == host_score(b), "diff 不得重新进入连续排序"


# ---------- LESSONS #38:探针失败不得沉默;冲突也是一种死法 ----------

_CONFLICT_TAIL = (
    "ERROR: Cannot install requests==2.32.5 and requests>=2.31.0 because these "
    "package versions have conflicting dependencies.\n"
    "ERROR: ResolutionImpossible: for help visit https://pip.pypa.io/...\n")


def test_version_conflict_is_recognised_and_attributed_to_adder() -> None:
    """#38:`ResolutionImpossible` 与"找不到分发"是两种措辞,都要认;
    且只报**适配新增**的分发(基线里本就有的算轮仓/宿主的事)。
    反例 order-59:冲突里的 requests 是 agent 自己加的,旧正则认不出,
    harness 又一次替模型认领(attribution: harness)。"""
    from repoproof.runner.host_guided import added_problem_dists, conflicting_dists

    assert conflicting_dists(_CONFLICT_TAIL) == ["requests"]
    assert added_problem_dists(_CONFLICT_TAIL, frozenset()) == ["requests"]
    # 基线里本就有 requests → 不算适配的锅
    assert added_problem_dists(_CONFLICT_TAIL, frozenset({"requests"})) == []


def test_probe_failure_always_produces_a_fatal_packet() -> None:
    """#38 核心:探针非零退出**必须**成包并进 fatal,哪怕一个分发名都认不出。
    反例 order-59:exit_code=1 + 空清单 → 该轮被当成干净 → 全绿即停 →
    干净重放以同一条冲突击杀。沉默比误报危险得多。"""
    from repoproof.runner.host_guided import round_violation_report

    packets, fatal, pol = round_violation_report(
        denied_delta=0, tampered=[], patch_files=1, patch_lines=10,
        max_patch_files=20, max_patch_lines=1800,
        unresolvable_dists=[],                    # 认不出任何名字
        dependency_probe_failed=True,
        dependency_detail="ERROR: ResolutionImpossible")
    assert "dependency" in fatal, "认不出名字也必须致命,不得放行"
    assert len(packets) == 1 and packets[0].type == "DEPENDENCY_NOT_REPRODUCIBLE"
    assert "ResolutionImpossible" in packets[0].actual, "原文要带给 agent"
    assert pol == 0

    # 探针没失败 → 一切照旧,不得凭空造包
    assert round_violation_report(
        denied_delta=0, tampered=[], patch_files=1, patch_lines=10,
        max_patch_files=20, max_patch_lines=1800,
        unresolvable_dists=[]) == ([], [], 0)


def test_probe_wiring_reports_failure_not_just_names() -> None:
    """接线钉死:run_round 必须把"探针失败"这一事实传下去,而不是只传名字。"""
    assert "probe_failed = True" in HOST_GUIDED_SRC
    assert "dependency_probe_failed=probe_failed" in HOST_GUIDED_SRC
    assert "added_problem_dists(" in HOST_GUIDED_SRC
