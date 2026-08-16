"""变异闸门:把**已付过学费的缺陷**逐个注回源码,钉死套件必须 100% 抓住。

这是"评测者的评测者"(PROCESS-INDEPENDENCE-PLAN §5-P1-5)。回答的问题:
我的钉死到底护住了什么?——不是"测试全绿"(照着实现写的测试永远全绿),
而是"把 LESSONS 里每一条历史缺陷(及其近似变体)重新犯一遍,套件会不会红"。
变体的意义:抓得住原案却抓不住变体 = 钉死过拟合到了事发实例,护不住缺陷类。

四种结局:
    CAUGHT         注入后指定测试子集变红,且**声明要考的那条判断在红名单里**
    ESCAPED        注入后子集仍绿 —— 套件没在护这条教训,当场补钉死
    STALE          旧串在源里找不到/不唯一 —— 源码重构后登记簿未更新,必须维护
    MISATTRIBUTED  红了,但抓住它的不是声明的判断 —— 登记簿错误,非通过

归因执法(2026-08-16,M59c/M62d,e/M64c 一天三次同型逃逸之后):
`expected_catcher` 声明这条变异必须由哪条钉死抓住(裸函数名;参数化按
基名匹配)。只看"红没红"的旧口径下,合成缺陷被更早的另一条判断先杀
(比例关先于散文关),被考的判断掏掉也看不出差别 —— 语料在替一条不存在
的防线背书。声明为空的存量条目照旧算 CAUGHT,但进 `unattributed`
诚实清单;整文件收集期崩溃单列 COLLAPSE(判断不是被抢先,是全场阵亡)。
**边界(如实声明)**:归因粒度到 junitxml 节点;同一个测试函数里多条断言
的先后遮蔽量不到,那一半仍靠"合成缺陷必须只触发被考的那条判断"的设计纪律。

自证机制(先于一切变异运行):C0 金丝雀变异(掏空 PASS_VERDICTS)若未被
抓住,说明 worktree 隔离失效(测的是主树不是变异体);C1 归因金丝雀
(同一变异体、声明一个不存在的判断)若没有判出 MISATTRIBUTED,说明归因
执法在装样子。任一不过,整个闸门自宣无效退出 —— 检查器必须先证明自己
在检查,才有资格给别人发绿。

隔离:临时 git worktree(HEAD)+ `PYTHONPATH=<树>/src` 压过 editable 安装;
每个变异注入→跑子集→`git checkout --` 还原。主工作树全程零触碰。

用法:
    .venv/bin/python scripts/mutation_gate.py          # 全量,证据落盘
    .venv/bin/python scripts/mutation_gate.py --list   # 只列登记簿
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYTEST = REPO / ".venv" / "bin" / "pytest"
EVIDENCE_DIR = REPO / "docs" / "evidence" / "mutation_gate"

# ---------------------------------------------------------------- 登记簿
# 每条 = 一次真实事故(lesson)或其近似变体(variant of)。old 必须与 HEAD
# 源码逐字节一致且唯一(STALE 判据);catchers 是必须变红的测试子集。

_BR = "src/repoproof/persistence/bench_records.py"
_HG = "src/repoproof/harness/host_guard.py"
_HD = "src/repoproof/runner/host_guided.py"
_RL = "src/repoproof/adoption/repair/repair_loop.py"
_RG = "scripts/redgreen.py"
_FP = "src/repoproof/adoption/repair/failure_packet.py"
_TB = "src/repoproof/agents/token_budget.py"
_T_BR = ["tests/test_bench_records.py"]
_T_RCL = ["tests/test_run_classification.py"]
_T_HG = ["tests/test_host_guard.py"]
_T_HD = ["tests/test_host_guided.py"]
_RC_M = "src/repoproof/receipts/model.py"
_RC_V = "src/repoproof/receipts/verify.py"
_RC_L = "src/repoproof/receipts/ledger.py"
_T_UR = ["tests/test_upstream_receipt.py"]
_RCS = "scripts/verify_receipt_controls.py"
_T_RCS = ["tests/test_receipt_controls.py"]
_RTP = "src/repoproof/execution/runtime_profiles.py"
_USC = "src/repoproof/execution/upstream_sidecar.py"
_T_RTP = ["tests/test_runtime_profiles.py"]
_SCF = "scripts/sidecar_conformance.py"
_T_SCF = ["tests/test_sidecar_conformance.py"]
_BCF = "scripts/browser_conformance.py"
_BWK = "benchmarks/v2/sidecar_browser/worker.py"
_T_BCF = ["tests/test_browser_conformance.py"]
# HB-PCDELTA-1 出题工程(2026-08-16)
_DOL = "scripts/delta_oracle_lib.py"
_T_DOL = ["tests/test_delta_oracle_lib.py"]
_HBC = "scripts/hb_batch_criteria.py"
_T_HBC = ["tests/test_hb_batch_criteria.py"]
_BTP = "scripts/build_hb1_task_packages.py"
_T_HTP = ["tests/test_hb_task_packages.py"]
_T_HTG = ["tests/test_hb_task_glue.py"]
_VTR = "scripts/verify_task_receipts.py"
_T_T3S = ["tests/test_t3_sidecar_task.py"]
_FSM = "scripts/failure_side_matrix.py"
_DIF = "src/repoproof/execution/differential.py"
_PH2 = "scripts/prepare_host2.py"
_HA = "src/repoproof/execution/heldout_admission.py"
_T_HA = ["tests/test_heldout_admission.py"]
_T_PH2 = ["tests/test_host2_prepare.py"]
_DIM = "scripts/differential_injection_matrix.py"
_T_DIF = ["tests/test_differential_injection.py"]
_T_FS = ["tests/test_failure_side.py"]
_SSN = "src/repoproof/runner/sidecar_session.py"
_T_SW = ["tests/test_sidecar_wiring.py"]
_PP = "src/repoproof/execution/profile_promotion.py"
_T_PP = ["tests/test_profile_promotion.py"]
_T_CF = ["tests/test_constraint_feedback.py"]
_T_PI = ["tests/test_process_independence.py"]
_T_RC = ["tests/test_root_cause_packets.py"]
_T_TE = ["tests/test_token_enforcement.py"]
_T_PS = ["tests/test_public_surface_integrity.py"]
_PO = "src/repoproof/harness/policy.py"
_EV = "src/repoproof/agents/repoproof_env.py"
_T_WC = ["tests/test_workspace_containment.py"]
_BC = "scripts/build_control_tree.py"
_T_CT = ["tests/test_control_tree_recipe.py"]
_CP = "src/repoproof/agents/context_projector.py"
_T_WP = ["tests/test_window_projection.py"]
_PR = "src/repoproof/agents/profiles.py"
_T_EP = ["tests/test_exec_profiles.py"]
_VC = "scripts/validate_controls.py"
_T_VM = ["tests/test_control_validation_matrix.py"]
_MG = "scripts/mutation_gate.py"
_T_MA = ["tests/test_mutation_attribution.py"]
_BAM = "scripts/blind_attack_admission.py"
_T_BAM = ["tests/test_blind_attack_admission.py"]

CANARY = {
    "id": "C0-plumbing-canary",
    "lesson": "自证:worktree 隔离必须真的生效",
    "file": _BR,
    "old": 'PASS_VERDICTS = frozenset({"PASS", "PASS_ADAPTED"})',
    "new": "PASS_VERDICTS = frozenset()",
    "catchers": _T_BR,
}

# C1:归因金丝雀。复用 C0 的变异体(已被 C0 证明必红),但声明一个 catcher
# 文件里**不存在**的判断 —— 红∩声明恒为空,唯一健康结局就是 MISATTRIBUTED。
# 判出别的(尤其 CAUGHT)= 归因执法在装样子,整个闸门的归因结论无效。
ATTRIBUTION_CANARY = {
    "id": "C1-attribution-canary",
    "lesson": "自证:摆好的归因错位必须报得出来(声明 A 抓、实际 B 抓 ≠ 通过)",
    "file": CANARY["file"],
    "old": CANARY["old"],
    "new": CANARY["new"],
    "catchers": CANARY["catchers"],
    "expected_catcher": ["test_attribution_canary_names_a_judge_that_never_fires"],
}

MUTATIONS: list[dict] = [
    # ---- LESSONS #30:冒烟发混进闸门通过数 ----
    {
        "id": "M30a-smoke-not-excluded",
        "lesson": "#30 fake 冒烟发被当成模型 PASS(在闸门里躺了 3 天)",
        "file": _BR,
        "old": ('    smoke = [r for r in rows\n'
                '             if str(r.get("model", "")).startswith(SMOKE_MODEL_PREFIX)]\n'
                '    real = [r for r in rows\n'
                '            if not str(r.get("model", "")).startswith(SMOKE_MODEL_PREFIX)]'),
        "new": "    smoke = []\n    real = list(rows)",
        "catchers": _T_BR,
        "expected_catcher": ["test_fake_smoke_pass_never_counts_toward_gate"],
    },
    {
        "id": "M30b-smoke-prefix-case-variant",
        "lesson": "#30 变体:前缀大小写错配,fake-scripted 漏网",
        "file": _BR,
        "old": 'SMOKE_MODEL_PREFIX = "fake"',
        "new": 'SMOKE_MODEL_PREFIX = "FAKE"',
        "catchers": _T_BR,
        "expected_catcher": ["test_fake_smoke_pass_never_counts_toward_gate"],
    },
    # ---- LESSONS #27:探索性加发未与预注册批次隔离 ----
    {
        "id": "M27-exploratory-counts",
        "lesson": "#27 探索性加发充闸门(真话写在机器读不到的地方)",
        "file": _BR,
        "old": '    prereg = [r for r in real if r.get("batch") != EXPLORATORY_BATCH]',
        "new": "    prereg = list(real)",
        "catchers": _T_BR,
        "expected_catcher": ["test_exploratory_batch_never_counts_toward_gate"],
    },
    # ---- LESSONS #26:裁定不进统计,台账自失真 ----
    {
        "id": "M26-verdict-not-effective",
        "lesson": "#26 闸门数原始 verdict 而非 effective_verdict(order-38 假 PASS 复活)",
        "file": _BR,
        "old": '    passes = [r for r in gateable if r["effective_verdict"] in PASS_VERDICTS]',
        "new": '    passes = [r for r in gateable if r.get("verdict") in PASS_VERDICTS]',
        "catchers": _T_BR,
        "expected_catcher": ["test_effective_verdict_join_and_pass_count"],
    },
    {
        "id": "M26b-substring-pass-variant",
        "lesson": '#26 变体:"PASS" in verdict 子串判定(FALSE_PASS 含 PASS)',
        "file": _BR,
        "old": '    passes = [r for r in gateable if r["effective_verdict"] in PASS_VERDICTS]',
        "new": '    passes = [r for r in gateable if "PASS" in str(r["effective_verdict"])]',
        "catchers": _T_BR,
        "expected_catcher": ["test_effective_verdict_join_and_pass_count"],
    },
    # ---- LESSONS #29:bench 根白名单方向反了 ----
    {
        "id": "M29a-prefix-free-pass",
        "lesson": "#29 前缀白名单放行了装着 PASS 解的 T4 栈",
        "file": _HG,
        "old": '        if name == ".DS_Store" or name in _BENCH_ALLOWED_NAMES:',
        "new": ('        if name == ".DS_Store" or name.startswith("offerclaw-") '
                'or name in _BENCH_ALLOWED_NAMES:'),
        "catchers": _T_HG,
        "expected_catcher": ["test_bench_hygiene_offerclaw_prefix_is_not_a_free_pass"],
    },
    {
        "id": "M29b-upstream-whitelisted",
        "lesson": "#29 变体:给无害兄弟目录 upstream 开口子(该迁走的是整套栈)",
        "file": _HG,
        # 锚在**判定行**而不是名单末行(2026-08-15 重锚):名单会随宿主增长,
        # 锚在末行的话每加一个宿主就 STALE 两条,而 STALE 让 G5.mutation 判不过、
        # 整条晋级链连坐全红。判定行不随名单动。
        "old": '        if name == ".DS_Store" or name in _BENCH_ALLOWED_NAMES:',
        "new": ('        if name == ".DS_Store" or name in ('
                '_BENCH_ALLOWED_NAMES | {"upstream"}):'),
        "catchers": _T_HG,
        "expected_catcher": ["test_bench_hygiene_flags_vendored_upstream"],
    },
    {
        "id": "M29c-answer-key-registered",
        "lesson": "#29 变体:把答案卷目录本身登记进白名单",
        "file": _HG,
        "old": '        if name.startswith(_BENCH_ALLOWED_PREFIXES) or (extra and name.startswith(extra)):',
        "new": ('        if name.startswith(_BENCH_ALLOWED_PREFIXES) or '
                'name == "offerclaw-transaction-stack" or '
                '(extra and name.startswith(extra)):'),
        "catchers": _T_HG,
        "expected_catcher": ["test_bench_hygiene_offerclaw_prefix_is_not_a_free_pass"],
    },
    # ---- 主目录硬护栏(红线,无单独 lesson 号) ----
    {
        "id": "MGuard-case-sensitive",
        "lesson": "护栏红线变体:路径比较丢大小写归一(APFS 大小写不敏感可绕)",
        "file": _HG,
        "old": '    return os.path.realpath(os.path.expanduser(str(p))).lower().rstrip("/")',
        "new": '    return os.path.realpath(os.path.expanduser(str(p))).rstrip("/")',
        "catchers": _T_HG,
        "expected_catcher": ["test_path_variants_all_blocked"],
    },
    # ---- LESSONS #31:harness 替模型认领错 ----
    {
        "id": "M31a-attribution-neutered",
        "lesson": "#31 归因分支被掏空(一切依赖失败重新都算 harness)",
        "file": _HD,
        "old": "            added = added_problem_dists(full, self._baseline_dists())",
        "new": "            added = []",
        "catchers": _T_HD,
        "expected_catcher": ["test_dependency_failure_attributed_to_agent_not_harness"],
    },
    {
        "id": "M31b-attribution-flipped",
        "lesson": "#31 变体:归因标签写反(agent 缺陷标成 harness)",
        "file": _HD,
        "old": '                               "attribution": "agent",',
        "new": '                               "attribution": "harness",',
        "catchers": _T_HD,
        "expected_catcher": ["test_dependency_failure_attributed_to_agent_not_harness"],
    },
    {
        "id": "M31c-failure-types-union-dropped",
        "lesson": "#31 验证器归因进不了台账 failure_types(只活在 report.json)",
        "file": _HD,
        "old": ('            | {vr.extra["failure_type"]\n'
                '               for vr in (capability_vr, regression_vr, policy_vr, replay_vr)\n'
                '               if vr is not None and vr.extra.get("failure_type")})'),
        "new": "            )",
        "catchers": _T_HD,
        "expected_catcher": ["test_verifier_attribution_reaches_failure_types"],
    },
    {
        "id": "M31d-pep503-dropped",
        "lesson": "#31 变体:丢 PEP 503 归一(Browser_Use ≠ browser-use,基线比对失效)",
        "file": _HD,
        "old": '    return re.sub(r"[-_.]+", "-", name).lower()',
        "new": "    return name.lower()",
        "catchers": _T_HD,
        "expected_catcher": ["test_dist_names_are_pep503_normalised"],
    },
    # ---- LESSONS #33:轮内约束不反馈,终局才伏击 ----
    {
        "id": "M33a-denied-cumulative-restored",
        "lesson": "#33 denied 退回会话累计(一轮违规永久拖累后续所有轮)",
        "file": _HD,
        "old": "                denied_round = env.denied_count - denied_before",
        "new": "                denied_round = env.denied_count",
        "catchers": _T_CF,
        "expected_catcher": ["test_run_round_uses_per_round_denied_delta"],
    },
    {
        "id": "M33b-green-stop-ignores-fatal",
        "lesson": "#33 全绿即停无视 fatal 违规(剩余轮次全弃,盖棺被击杀)",
        "file": _RL,
        "old": "                    and not result.fatal_violations):",
        "new": "                    ):",
        "catchers": _T_CF,
        "expected_catcher": ["test_green_round_with_fatal_violation_keeps_looping"],
    },
    {
        "id": "M33c-rollback-detail-mismatch",
        "lesson": "#33 回滚后失败包配错细节(best 的节点 × 劣化轮的 details)",
        "file": _RL,
        "old": "            packets = build_failure_packets(src_cp.failed_nodes, src_cp.failure_details)",
        "new": "            packets = build_failure_packets(src_cp.failed_nodes, result.failure_details)",
        "catchers": _T_CF,
        "expected_catcher": ["test_rollback_is_explained_and_details_come_from_restored_round"],
    },
    {
        "id": "M33d-violation-packets-dropped",
        "lesson": "#33 变体:违规判据引擎在,但包不进下一轮提示(agent 仍瞎)",
        "file": _HD,
        "old": ("                    failure_packets=[p.to_dict()\n"
                "                                     for p in (*packets_next, *violation_packets)],"),
        "new": "                    failure_packets=[p.to_dict() for p in packets_next],",
        "catchers": _T_CF,
        "expected_catcher": ["test_round_record_ledger_carries_violation_packets"],
    },
    {
        "id": "M33e-patch-overage-poisons-ranking",
        "lesson": "#33 变体:patch 超限计进 policy_violations(超重全绿轮被回滚,逼重做)",
        "file": _HD,
        "old": "    return packets, fatal, len(tampered)",
        "new": "    return packets, fatal, len(tampered) + len(fatal)",
        "catchers": _T_CF,
        "expected_catcher": ["test_patch_overage_packet_carries_gate_numbers_and_is_fatal"],
    },
    # ---- LESSONS #34:红绿守卫两义性 ----
    {
        "id": "M34a-exit4-blanket-reject",
        "lesson": "#34 exit 4 一律否掉(ImportError 型最强的红被判假阴性)",
        "file": _RG,
        "old": "        if not genuine:",
        "new": "        if True:",
        "catchers": _T_PI,
        "expected_catcher": ["test_import_error_collection_counts_as_red"],
    },
    {
        "id": "M34b-exit4-blanket-accept",
        "lesson": "#34 反向:exit 4 一律算红(守卫被拆,名字打错也能冒充红)",
        "file": _RG,
        "old": "    if red_exit == 4:",
        "new": "    if False:",
        "catchers": _T_PI,
        "expected_catcher": ["test_typo_node_name_still_cannot_fake_red", "test_unrelated_collection_crash_is_not_red"],
    },
    # ---- LESSONS #35:排序只对齐终局判据 ----
    {
        "id": "M35a-denied-poisons-ranking-again",
        "lesson": "#35 denied 退回排序(21/23 的轮因一条零执行的调试命令被弃)",
        "file": _HD,
        "old": "    return packets, fatal, len(tampered)",
        "new": "    return packets, fatal, len(tampered) + denied_delta",
        "catchers": _T_CF,
        "expected_catcher": ["test_denied_round_can_still_win_on_pass_count"],
    },
    {
        "id": "M35b-store-before-guard",
        "lesson": "#35 F3:先建证据目录后过护栏(被拒的构造也留空壳污染证据树)",
        "file": _HD,
        "old": ('        self._verify_static_resources()\n'
                '        self.store = FileRunStore('
                '(runs_root or self.project_root / "runs") / self.run_id)'),
        "new": ('        self.store = FileRunStore('
                '(runs_root or self.project_root / "runs") / self.run_id)\n'
                '        self._verify_static_resources()'),
        "catchers": _T_HD,
        "expected_catcher": ["test_failed_construction_leaves_no_run_dir"],
    },
    # ---- LESSONS #36:反馈量足够、形状错误 ----
    {
        "id": "M36a-collapse-disabled",
        "lesson": "#36 同根因不再折叠(15 项同话包重回,信息 1 句噪声 60 行)",
        "file": _FP,
        "old": "COLLAPSE_MIN = 3   # 同签名达此数量才合并;2 条不值得抽象",
        "new": "COLLAPSE_MIN = 9999",
        "catchers": _T_RC,
        "expected_catcher": ["test_shared_root_cause_collapses_into_one_packet"],
    },
    {
        "id": "M36b-timeout-rule-dropped",
        "lesson": "#36 超时规则被摘(超时按测试名误判成 SCHEMA_ERROR)",
        "file": _FP,
        "old": '    (TIMEOUT, ("未在", "内终结", "timed out", "timeout", "timeouterror")),',
        "new": "",
        "catchers": _T_RC,
        "expected_catcher": ["test_timeout_is_typed_and_advised_as_timeout"],
    },
    {
        "id": "M36c-victim-list-truncated",
        "lesson": "#36 折叠包截断受害者名单(静默丢信息,开发中真犯过)",
        "file": _FP,
        "old": '                         f"(判定类型 {cause}):" + "、".join(names)),',
        "new": '                         f"(判定类型 {cause}):" + "、".join(names[:6])),',
        "catchers": _T_RC,
        "expected_catcher": ["test_no_information_is_silently_dropped"],
    },
    {
        "id": "M36d-collapse-too-eager",
        "lesson": "#36 变体:阈值降到 1,单条失败也被抽象成'根因',旧形态回退",
        "file": _FP,
        "old": "    collapsed = {n for sig, ns in groups.items() if len(ns) >= COLLAPSE_MIN for n in ns}",
        "new": "    collapsed = {n for sig, ns in groups.items() if len(ns) >= 1 for n in ns}",
        "catchers": _T_RC,
        "expected_catcher": ["test_distinct_root_causes_are_not_merged"],
    },
    # ---- LESSONS #37:修剪轮不能白干 ----
    {
        "id": "M37a-compliance-term-removed",
        "lesson": "#37 排序丢掉二元合规位(修剪轮与超重轮同分,先到先得选中超重的)",
        "file": _HD,
        "old": "        1.0 if not r.fatal_violations else 0.0,\n        1.0 if r.within_budget else 0.0,",
        "new": "        1.0 if r.within_budget else 0.0,",
        "catchers": _T_CF,
        "expected_catcher": ["test_trimmed_round_beats_oversized_round_on_equal_passes"],
    },
    {
        "id": "M37b-compliance-outranks-progress",
        "lesson": "#37 变体:合规位前移到通过数之前(拿少改点换测试进度,-211400 老病)",
        "file": _HD,
        "old": ("        float(r.passed),\n        float(r.passed),\n"
                "        1.0 if not r.fatal_violations else 0.0,"),
        "new": ("        1.0 if not r.fatal_violations else 0.0,\n"
                "        float(r.passed),\n        float(r.passed),"),
        "catchers": _T_CF,
        "expected_catcher": ["test_compliance_never_outranks_test_progress"],
    },
    # ---- LESSONS #38:探针失败不得沉默;冲突也是一种死法 ----
    {
        "id": "M38a-probe-failure-swallowed",
        "lesson": "#38 探针非零退出但认不出名字就放行(order-59:全绿即停→重放击杀)",
        "file": _HD,
        "old": "    if unresolvable_dists or dependency_probe_failed:",
        "new": "    if unresolvable_dists:",
        "catchers": _T_CF,
        "expected_catcher": ["test_probe_failure_always_produces_a_fatal_packet"],
    },
    {
        "id": "M38b-conflict-pattern-dropped",
        "lesson": "#38 只认「找不到分发」不认 ResolutionImpossible(harness 替模型认领)",
        "file": _HD,
        "old": "    return [d for d in conflicting_dists(pip_output) if d not in baseline]",
        "new": "    return []",
        "catchers": _T_CF,
        "expected_catcher": ["test_version_conflict_is_recognised_and_attributed_to_adder"],
    },
    # ---- LESSONS #39:执法读到陈旧总量 + 固定内移是猜的 ----
    {
        "id": "M39a-enforcement-back-to-async-hook",
        "lesson": "#39 执法只信异步钩子(order-63:读到落后一次调用的 703,172 就放行)",
        "file": _TB,
        "old": '        return max(self.sync_in, int(self.totals.get("in", 0) or 0))',
        "new": '        return int(self.totals.get("in", 0) or 0)',
        "catchers": _T_TE,
        "expected_catcher": ["test_enforcement_does_not_rely_on_the_async_usage_hook"],
    },
    {
        "id": "M39b-pre-call-projection-disabled",
        "lesson": "#39 调用前不投影,只在越线后才拦(803,310 > 800,000 的直接成因)",
        "file": _TB,
        "old": "            if used_in + projected > self.max_input_tokens:",
        "new": "            if used_in + projected > self.max_input_tokens * 100:",
        "catchers": _T_TE,
        "expected_catcher": ["test_no_single_call_can_cross_the_hard_cap"],
    },
    {
        "id": "M39c-observed-max-floor-dropped",
        "lesson": "#39 投影只剩估算一条腿(估算失准时又变成拍脑袋)",
        "file": _TB,
        "old": "        return max(math.ceil(est * self.ratio * SAFETY_FACTOR), self.max_call_in)",
        "new": "        return math.ceil(est * self.ratio * SAFETY_FACTOR)",
        "catchers": _T_TE,
        "expected_catcher": ["test_projection_floor_is_the_largest_observed_call"],
    },
    {
        "id": "M39d-round-bucket-back-to-hook",
        "lesson": "#39 轮桶回到异步钩子(上一轮末次调用被记进下一轮,拿别人的 token 杀这一轮)",
        "file": _HD,
        "old": '    if getattr(model, "seen", False):',
        "new": '    if not getattr(model, "seen", False):',
        "catchers": _T_TE,
        "expected_catcher": ["test_round_bucket_prefers_synchronous_accounting"],
    },
    {
        "id": "M39e-estimator-ignores-cjk",
        "lesson": "#39 估算照搬 chars/4(order-63 实测低估 33%,投影跟着塌)",
        "file": _TB,
        "old": "    cjk = len(_CJK.findall(text))",
        "new": "    cjk = 0",
        "catchers": _T_TE,
        "expected_catcher": ["test_estimator_never_undercounts_cjk"],
    },
    {
        "id": "M39f-enforcement-line-inset-again",
        "lesson": "#39 有人又把执法线往里挪(拍常数替代投影,单次调用比常数大就翻车)",
        "file": _HD,
        "old": "    return budgets.max_input_tokens_total",
        "new": "    return max(1, budgets.max_input_tokens_total - 50_000)",
        "catchers": _T_HD,
        "expected_catcher": ["test_enforcement_input_cap_is_the_contract_value_not_an_inset"],
    },
    # ---- LESSONS #40:fixtures 是量具,不是实现面 ----
    {
        "id": "M40a-fixtures-out-of-public-surface",
        "lesson": "#40 公开面只认 public_tests(order-20/21:oracle 拿被测者写的假模型当量具)",
        "file": _HD,
        "old": 'PROTECTED_PUBLIC_DIRS = ("public_tests", "fixtures")',
        "new": 'PROTECTED_PUBLIC_DIRS = ("public_tests",)',
        "catchers": _T_PS,
        "expected_catcher": ["test_fixtures_count_as_public_surface_tampering"],
    },
    {
        "id": "M40b-final-check-back-to-public-tests-only",
        "lesson": "#40 终局对账退回只哈希 public_tests(改 fixtures 盖棺时查不出)",
        "file": _HD,
        "old": "                public_before, hash_public_surface(s.root / \"host\"))",
        "new": "                public_before, hash_tree(s.root / \"host\" / \"public_tests\"))",
        "catchers": _T_PS,
        "expected_catcher": ["test_both_call_sites_use_the_merged_surface"],
    },
    {
        "id": "M40c-prompt-drops-the-fixtures-rule",
        "lesson": "#40 终局会杀却不在提示里教(#33 的老病:agent 改了 19 轮没人告诉过它)",
        "file": _HD,
        "old": '        + "\\n- Do not modify ./public_tests, ./fixtures or ../upstream. The fixtures\\n"',
        "new": '        + "\\n- Do not modify ./public_tests or ../upstream.\\n"',
        "catchers": _T_PS,
        "expected_catcher": ["test_prompt_forbids_touching_fixtures"],
    },
    {
        "id": "M41a-answer-key-markers-gone",
        "lesson": "#41 政策不认答案树路径(order-21:cp 正控 research_jobs.py 进工作区)",
        "file": _PO,
        "old": '    "_scratch_t",                 # 正控/负控安装树(order-21 抄的就是它)',
        "new": '    "__never_matches_anything__",',
        "catchers": _T_WC,
        "expected_catcher": ["test_heredoc_body_is_file_content_not_a_command"],
    },
    {
        "id": "M41b-root-sweep-not-detected",
        "lesson": "#41 根扫描放行(发现答案的第一步:find / -name fake_llm_server.py)",
        "file": _PO,
        "old": "    if root_sweeping(lowered):",
        "new": "    if False:",
        "catchers": _T_WC,
        "expected_catcher": ["test_root_sweep_is_denied_but_does_not_kill"],
    },
    {
        "id": "M41c-sweep-detector-ignores-separators",
        "lesson": "#41 变体:根检测不在分隔符处复位 → `find . -name x ; cp a /` 被误伤",
        "file": _PO,
        "old": "        if tok in _SEPARATORS:\n            active = False\n            continue",
        "new": "        if tok in _SEPARATORS:\n            continue",
        "catchers": _T_WC,
        "expected_catcher": ["test_root_sweep_detection_does_not_fire_on_plain_paths"],
    },
    {
        "id": "M41d-root-sweep-promoted-to-a-kill",
        "lesson": "#41 变体:把根扫描也判死 —— 27 发越界里 24 发只是在找 wheelhouse(#35 反面)",
        "file": _PO,
        "old": "        reasons.append(ROOT_SWEEP)",
        "new": "        reasons.append(f\"{OUT_OF_WORKSPACE}:{ROOT_SWEEP}\")",
        "catchers": _T_WC,
        "expected_catcher": ["test_root_sweep_is_denied_but_does_not_kill"],
    },
    {
        "id": "M41d2-heredoc-body-scanned-as-a-command",
        "lesson": "#41 变体:heredoc 正文当命令扫 → 写文件被误判成全盘扫描(误伤毁一轮)",
        "file": _PO,
        "old": "    for tok in strip_heredocs(command).split():",
        "new": "    for tok in command.split():",
        "catchers": _T_WC,
        "expected_catcher": ["test_heredoc_body_is_file_content_not_a_command"],
    },
    {
        "id": "M41e-denial-reasons-only-counted",
        "lesson": "#41 只记 denied_count 不记原因 → 越界与预算耗尽分不出来",
        "file": _EV,
        "old": "            self.policy_denials.extend(decision.reasons)",
        "new": "            pass",
        "catchers": _T_WC,
        "expected_catcher": ["test_denial_reasons_are_recorded_not_just_counted"],
    },
    {
        "id": "M41f-residue-scan-skips-scratch-trees",
        "lesson": "#41 H9-a 不认 _scratch_t* 安装树(order-21 抄的那棵就在其中)",
        "file": _HD,
        "old": '                    if e.name.startswith("_scratch_t"):',
        "new": '                    if False:',
        "catchers": _T_WC,
        "expected_catcher": ["test_scratch_tree_is_residue"],
    },
    {
        "id": "M41g-residue-scan-flags-the-live-session",
        "lesson": "#41 变体:H9-a 不跳过 _sessions → 每一发都拒开自己(过度封锁)",
        "file": _HD,
        "old": '                if e.name == _SESSION_DIR:\n                    continue',
        "new": '                if False:\n                    continue',
        "catchers": _T_WC,
        "expected_catcher": ["test_session_workspace_is_not_residue"],
    },
    {
        "id": "M41h-residue-is-a-warning-not-a-block",
        "lesson": "#41 H9-a 查到残留只告警不拒开(判据原文:拒开,不是告警)",
        "file": _HD,
        "old": "        residue = reachable_answer_keys(Path(contract_path).parent, blind=blind)\n        if residue:",
        "new": "        residue = reachable_answer_keys(Path(contract_path).parent, blind=blind)\n        if False:",
        "catchers": _T_WC,
        "expected_catcher": ["test_both_call_sites_are_wired"],
    },
    {
        "id": "M41i-out-of-workspace-not-fatal",
        "lesson": "#41 越界不进 fatal/排序 → 终局要杀,循环既不防也不报(#33/#35 老病)",
        "file": _HD,
        "old": '        fatal.append("out_of_workspace")',
        "new": '        pass',
        "catchers": _T_WC,
        "expected_catcher": ["test_answer_key_hits_are_fatal_and_counted"],
    },
    {
        "id": "M41j-prompt-drops-the-workspace-boundary",
        "lesson": "#41 H9-c:终局以 OUT_OF_WORKSPACE_ACCESS 击杀却不在提示里教(27 发无一被告知)",
        "file": _HD,
        "old": '        + "\\n- STAY INSIDE THE WORKSPACE. Everything you need is here: ./ and the\\n"',
        "new": '        + "\\n- Prefer to work inside the workspace.\\n"',
        "catchers": _T_WC,
        "expected_catcher": ["test_prompt_states_the_workspace_boundary"],
    },
    {
        "id": "M42g-scan-blindness-fails-open",
        "lesson": "#41 H9-a:列不动的目录当干净 → mv 进 ~/.Trash 后实测报 0 命中(检测器失明即放行)",
        "file": _HD,
        "old": "            except OSError:          # 列不动:不是残留证据,但也**不是**清白证据\n"
               "                if blind is not None:\n"
               "                    blind.append(str(cur))",
        "new": "            except OSError:          # 列不动:不是残留证据,但也**不是**清白证据\n"
               "                if False:\n"
               "                    blind.append(str(cur))",
        "catchers": _T_WC,
        "expected_catcher": ["test_unlistable_dir_is_reported_as_blind_not_as_clean"],
    },
    {
        "id": "M42h-blind-scan-does-not-block",
        "lesson": "#41 H9-a:查到盲区只记不拒开 —— 与 M41h 同型,只是这次拦的是'无法确立'",
        "file": _HD,
        "old": '        if blind:\n'
               '            return {"blocked": True, "agent_model_call_count": 0,\n'
               '                    "preflight": {"ready": False, "reason": "ANSWER_KEY_SCAN_BLIND"},',
        "new": '        if False:\n'
               '            return {"blocked": True, "agent_model_call_count": 0,\n'
               '                    "preflight": {"ready": False, "reason": "ANSWER_KEY_SCAN_BLIND"},',
        "catchers": _T_WC,
        "expected_catcher": ["test_blind_scan_blocks_the_run_with_its_own_reason"],
    },
    {
        "id": "M42f-trash-added-back-as-a-scan-root",
        "lesson": "#42 H9-a:废纸篓加回扫描根 → 它列不动,每一发都判 SCAN_BLIND(不可满足的闸门必被关掉)",
        "file": _HD,
        "old": 'ANSWER_KEY_SCAN_ROOTS = ("~/RepoProofBench", "~/RepoProofBench-quarantine", "/tmp")',
        "new": 'ANSWER_KEY_SCAN_ROOTS = ("~/RepoProofBench", "~/RepoProofBench-quarantine", "/tmp", "~/.Trash")',
        "catchers": _T_WC,
        "expected_catcher": ["test_trash_is_deliberately_not_a_scan_root"],
    },
    {
        "id": "M42a-control-tree-missing-the-mount",
        "lesson": "#41 C1:装配漏掉挂载 → 控制组装不起来,五物验证得到的是假阴性",
        "file": _BC,
        "old": "    if marker not in text:\n        rag.write_text(text + block)",
        "new": "    if False:\n        rag.write_text(text + block)",
        "catchers": _T_CT,
        "expected_catcher": ["test_mount_is_appended_exactly_once"],
    },
    {
        "id": "M42b-control-tree-drags-venv-and-git",
        "lesson": "#41 C2:不排除 .venv/.git → 7 棵手搓树各 78MB 的 .git(上游完整历史)被复制进可达树,"
                  ".venv 那条软链更直接指向隔离区",
        "file": _BC,
        "old": "    return {n for n in names if n in SKIP_DIRS}",
        "new": "    return set()",
        "catchers": _T_CT,
        "expected_catcher": ["test_venv_and_git_and_pycache_are_excluded"],
    },
    {
        "id": "M42c-control-tree-mounts-twice",
        "lesson": "#41 C3 反面:无条件追加 → 上游自带挂载时重复挂载(另一种装错)",
        "file": _BC,
        "old": "    if marker not in text:\n        rag.write_text(text + block)",
        "new": "    if True:\n        rag.write_text(text + block)",
        "catchers": _T_CT,
        "expected_catcher": ["test_mount_not_duplicated_when_upstream_already_mounts"],
    },
    {
        "id": "M42d-control-tree-defaults-to-residue",
        "lesson": "#41 C4:默认留树 → 每验证一次五物就多 7 棵残留(这正是 7 棵手搓树的来历)",
        "file": _BC,
        "old": "        if args.keep:",
        "new": "        if True:",
        "catchers": _T_CT,
        "expected_catcher": ["test_default_is_teardown_and_keep_is_opt_in"],
    },
    {
        "id": "M42e-control-tree-selfcheck-is-decorative",
        "lesson": "#41 C1:自检不逐字节比对 → 装错了要等五物验证出结论才发现(只写文字不执法)",
        "file": _BC,
        "old": "        if got.read_bytes() != f.read_bytes():",
        "new": "        if False:",
        "catchers": _T_CT,
        "expected_catcher": ["test_selfcheck_catches_a_botched_assembly"],
    },
    {
        "id": "M44a-mount-symbol-hardcoded-to-t2",
        "lesson": "#41 C5:挂载符号写死 → 装配器只服务 T2,T3 的控制组装出来的树根本起不来",
        "file": _BC,
        "old": "            return f.stem, fn, f\"\\nfrom {f.stem} import {fn}  # noqa: E402\\n{fn}(app)\\n\"",
        "new": "            return \"research_jobs\", \"mount_research_api\", \"\\nmount_research_api(app)\\n\"",
        "catchers": _T_CT,
        "expected_catcher": ["test_mount_symbol_is_discovered_from_the_control_body"],
    },
    {
        "id": "M44b-missing-mount-is-guessed-not-refused",
        "lesson": "#41 C5:找不到挂载函数就猜一个 → 装出一棵哑树,而自检比对的是自己写进去的那行,照样发绿",
        "file": _BC,
        "old": "    raise SystemExit(f\"控制组里找不到 `def mount_*(app)`,装不出能跑的树:{src_control}\")",
        "new": "    return \"research_jobs\", \"mount_research_api\", \"\\nmount_research_api(app)\\n\"",
        "catchers": _T_CT,
        "expected_catcher": ["test_control_without_a_mount_function_is_refused"],
    },
    {
        "id": "M43a-must-fail-all-green-still-passes",
        "lesson": "#43 V1:该红的全绿也判通过 → 需求只有文字没有执法,而验证发绿",
        "file": _VC,
        "old": "        elif name not in red:",
        "new": "        elif False:",
        "catchers": _T_VM,
        "expected_catcher": ["test_must_fail_all_green_means_the_requirement_is_only_text"],
    },
    {
        "id": "M43b-nothing-collected-counts-as-pass",
        "lesson": "#43 V3:一条都没跑起来时正控 must_fail 为空 → 把'什么都没跑'判成'全绿'",
        "file": _VC,
        "old": "    if not outcomes:\n        return False,",
        "new": "    if False:\n        return False,",
        "catchers": _T_VM,
        "expected_catcher": ["test_nothing_collected_is_never_a_pass"],
    },
    {
        "id": "M43c-collateral-damage-ignored",
        "lesson": "#43 V2:不查波及 → nc6 把半套用例打红也算数,证明不了是哪条判据抓住的它",
        "file": _VC,
        "old": "        for name in sorted(red & should_be_green):",
        "new": "        for name in sorted(set()):",
        "catchers": _T_VM,
        "expected_catcher": ["test_collateral_red_destroys_discrimination"],
    },
    {
        "id": "M43d-green-overwrites-red-in-parametrized",
        "lesson": "#43 V4:参数化用例被后续绿覆盖 → 3 个参数红 1 个也算整体绿",
        "file": _VC,
        "old": "        if out.get(name) == \"FAILED\":       # 已经红了就不被后续绿覆盖",
        "new": "        if False:       # 已经红了就不被后续绿覆盖",
        "catchers": _T_VM,
        "expected_catcher": ["test_parametrized_outcomes_merge_and_a_single_red_wins"],
    },
    {
        "id": "M43f-empty-suite-is-not-noticed",
        "lesson": "#43 V5:套件整跑丢失不报 → 实测中 oracle 那 10 条一条没跑,正控仍判'符合预期'",
        "file": _VC,
        "old": "        elif n == 0:",
        "new": "        elif False:",
        "catchers": _T_VM,
        "expected_catcher": ["test_a_suite_that_ran_nothing_voids_the_verdict"],
    },
    {
        "id": "M43g-void-exit-codes-accepted",
        "lesson": "#43 V5:pytest 内部错误/用法错误的那一跑也拿来下结论",
        "file": _VC,
        "old": "        if rc in VOID_EXITS:",
        "new": "        if False:",
        "catchers": _T_VM,
        "expected_catcher": ["test_pytest_internal_exit_codes_void_the_run"],
    },
    {
        "id": "M45a-profile-hash-not-per-face",
        "lesson": "#S1 P2:三面共用一个 hash → 只知道'配置变了',消融时无法判断变的是哪一面",
        "file": _PR,
        "old": ('        "tool_profile_hash": _hash(tool),\n'
                '        "context_profile_hash": _hash(context),\n'
                '        "budget_profile_hash": _hash(budget),'),
        "new": ('        "tool_profile_hash": _hash({**tool, **context, **budget}),\n'
                '        "context_profile_hash": _hash({**tool, **context, **budget}),\n'
                '        "budget_profile_hash": _hash({**tool, **context, **budget}),'),
        "catchers": _T_EP,
        "expected_catcher": ["test_changing_one_face_moves_only_that_hash"],
    },
    {
        "id": "M45b-fingerprint-not-content-stable",
        "lesson": "#S1 P1:哈希输入不排序 → 同一配置每次算出不同指纹,历史发次无法配对",
        "file": _PR,
        "old": '    return sha256_bytes(json.dumps(obj, sort_keys=True, separators=(",", ":"),',
        "new": '    return sha256_bytes(json.dumps(obj, sort_keys=False, separators=(",", ":"),',
        "catchers": _T_EP,
        "expected_catcher": ["test_hashes_are_deterministic_across_calls"],
    },
    {
        "id": "M45c-fingerprint-covers-whole-repo",
        "lesson": "#S1 P3:指纹扩到全仓 → 改一个 docs 错别字就让全部历史发次'不可比'",
        "file": _PR,
        "old": '_EXEC_ROOT = ("src", "repoproof")',
        "new": '_EXEC_ROOT = ()',
        "catchers": _T_EP,
        "expected_catcher": ["test_exec_fingerprint_tracks_src_only"],
    },
    {
        "id": "M45d-generation-ignores-spill",
        "lesson": "#S1 P4:上了 spill 仍标 E0 → E0/E1 数据混进同一个池子(§2 规则 1 被架空)",
        "file": _PR,
        "old": '    if context.get("spill_threshold_chars") or context.get("prune_policy"):',
        "new": "    if False:",
        "catchers": _T_EP,
        "expected_catcher": ["test_turning_on_spill_leaves_e0_automatically"],
    },
    {
        "id": "M45e-generation-ignores-new-tools",
        "lesson": "#S1 P4:多了 editor 仍标 E0 → S4 上线后代际标签失真",
        "file": _PR,
        "old": '    tools = tuple(tool.get("tools") or _E0_TOOLS)',
        "new": "    tools = _E0_TOOLS",
        "catchers": _T_EP,
        "expected_catcher": ["test_adding_editor_leaves_e0_automatically"],
    },
    {
        "id": "M46a-window-folds-exec-results",
        "lesson": "#S2' W1:把 pytest/pip 的结果也折了 → 模型失去修复依据,且重跑要 95 秒",
        "file": _CP,
        "old": "    if not cmd or _EXEC_CMD.search(cmd):\n        return False",
        "new": "    if not cmd:\n        return False",
        "catchers": _T_WP,
        "expected_catcher": ["test_read_then_exec_chain_is_never_folded"],
    },
    {
        "id": "M46b-window-folds-everything",
        "lesson": "#S2' W2:窗口失效 → 连最近读过的代码都折掉,模型只能重读,省下的被吃回去",
        "file": _CP,
        "old": "    keep = set(reads[-window:]) if window > 0 else set()",
        "new": "    keep = set()",
        "catchers": _T_WP,
        "expected_catcher": ["test_window_keeps_the_most_recent_reads_verbatim"],
    },
    {
        "id": "M46c-window-stub-drops-the-command",
        "lesson": "#S2' W4:存根不给原命令 → 丢了还不告诉你怎么找回",
        "file": _CP,
        "old": '                f"(窗口外的旧读取结果)。需要时重跑该命令即可取回:`{cmd}`]")[:_STUB_MAX]',
        "new": '                f"(窗口外的旧读取结果)。]")[:_STUB_MAX]',
        "catchers": _T_WP,
        "expected_catcher": ["test_stub_carries_the_command_for_rerun"],
    },
    {
        "id": "M46d-window-hides-its-lossiness",
        "lesson": "#S2' W6:有损投影不标 lossy → 后来者当成零风险,批报少一条诚实边界",
        "file": _CP,
        "old": '                 "lossy": True,',
        "new": '                 "lossy": False,',
        "catchers": _T_WP,
        "expected_catcher": ["test_manifest_declares_lossiness"],
    },
    # ---- M48:正控冒烟的环境清单(2026-08-14)。冒烟是**假阳侧正控**,它
    # 回答"这套 oracle 在钉版环境里到底能不能被满足"。下面四条各对应一种
    # "冒烟看起来跑了、其实什么都没证"的失效。
    {
        "id": "M48a-missing-manifest-silently-skipped",
        "lesson": "#N1:缺环境清单却静默跳过装依赖 → 冒烟跑完全红,读的人以为实现不对,其实是环境没备好",
        "file": _HD,
        "old": "    if not setup.is_file():\n        raise ValueError(",
        "new": "    if not setup.is_file():\n        setup.write_text('', encoding='utf-8')\n"
               "    if False:\n        raise ValueError(",
        "catchers": _T_HD,
        "expected_catcher": ["test_missing_setup_manifest_fails_loudly"],
    },
    {
        "id": "M48b-blocked-directive-ignored",
        "lesson": "#N2:忽略 #!BLOCKED 照常跑 → 台账里多一条与'模型失败'同型的记录,而它其实是环境不可满足,含义相反",
        "file": _HD,
        "old": '        if line.strip().startswith("#!BLOCKED:"):',
        "new": "        if False:",
        "catchers": _T_HD,
        "expected_catcher": ["test_blocked_directive_refuses_with_the_reason"],
    },
    {
        "id": "M48c-manifest-split-per-line",
        "lesson": "#N3:按行拆命令 → heredoc 被腰斩,垫片只写出半截而每条 rc=0,失败要到 oracle 才现形",
        "file": _HD,
        "old": '    for block in raw.split("\\n---\\n"):',
        "new": "    for block in raw.splitlines():",
        "catchers": _T_HD,
        "expected_catcher": ["test_multiline_block_is_delivered_whole"],
    },
    {
        "id": "M48d-smoke-lands-only-mount-module",
        "lesson": "#N5:只落挂载模块 → 冒烟看到的正控与控制树看到的不是同一个,冒烟不再是控制树的现场复现",
        "file": _HD,
        "old": '    for f in sorted(src_control.glob("*.py")):',
        "new": '    for f in sorted(src_control.glob(f"{module}.py")):',
        "catchers": _T_HD,
        "expected_catcher": ["test_smoke_lands_every_control_py_not_just_the_mount_module"],
    },
    {
        "id": "M53g-guard-set-lower-bound-removed",
        "lesson": "不查守护集下界 → 一份证据靠少声明几个守护文件就能长期有效,"
                  "与'分母由被测方提供'同病(用户 2026-08-14 指出)",
        "file": _PP,
        "old": "    short = REQUIRED_GUARD_SET - guarded",
        "new": "    short = set()",
        "catchers": _T_PP,
        "expected_catcher": ["test_g5_under_declared_guard_set_is_refused"],
    },
    {
        "id": "M53h-guard-set-omits-the-catalog",
        "lesson": "下界不含登记簿自身 → 改了变异登记簿(加条目/改 old/改 catcher),"
                  "旧证据仍替新一套变异背书",
        "file": _PP,
        "old": '    "scripts/mutation_gate.py",                       # 变异登记簿与证据格式',
        "new": "",
        "catchers": _T_PP,
        "expected_catcher": ["test_g5_lower_bound_covers_the_load_bearing_files"],
    },
    # ---- M53:Runtime Profile 晋级判据。生命周期是**对外承诺**(它决定别人
    # 敢不敢拿这个 profile 的发次当数),所以每一道松动都是实质性的。
    {
        "id": "M53a-missing-evidence-passes",
        "lesson": "查不到证据就默认放行 → 这样的闸门与没有闸门的区别,"
                  "只在于它会让人误以为有闸门",
        "file": _PP,
        "old": ('    if not mine:\n'
                '        seen = sorted({m.get("profile_id") for m in mats if m})\n'
                '        return [Check("G1-G4.evidence", False,'),
        "new": ('    if not mine:\n'
                '        seen = sorted({m.get("profile_id") for m in mats if m})\n'
                '        return [Check("G1-G4.evidence", True,'),
        "catchers": _T_PP,
        "expected_catcher": ["test_p1_missing_evidence_refuses"],
    },
    {
        "id": "M53b-someone-elses-evidence-counts",
        "lesson": "不核 profile_id → 拿别人的体检报告给自己晋级",
        "file": _PP,
        "old": '    mine = [m for m in mats if m and m.get("profile_id") == p.id]',
        "new": "    mine = [m for m in mats if m]",
        "catchers": _T_PP,
        "expected_catcher": ["test_p2_another_profiles_evidence_does_not_count"],
    },
    {
        "id": "M53c-level-skipping-allowed",
        "lesson": "允许 experimental 跳 qualified → 拿真实发次替'机制站不站得住'"
                  "背书,而那是两个问题",
        "file": _PP,
        "old": '        if p.lifecycle == "experimental":',
        "new": "        if False:",
        "catchers": _T_PP,
        "expected_catcher": ["test_p3_no_skipping_a_level"],
    },
    {
        "id": "M53d-fake-runs-count-as-real",
        "lesson": "冒烟发次充真实发次 → --fake positive 必定 PASS(harness 自己"
                  "塞的正控),拿它当'模型跑通了'是最容易发生的自欺",
        "file": _PP,
        "old": '            and not str(r.get("model", "")).startswith("fake")]',
        "new": "            ]",
        "catchers": _T_PP,
        "expected_catcher": ["test_p4b_fake_scripted_runs_never_count_as_real"],
    },
    {
        "id": "M53e-undecidable-returns-pass",
        "lesson": "判不了却返回通过 → 把一个取舍(该不该设默认)伪装成一个测量",
        "file": _PP,
        "old": "                            ok=machine and bool(checks) and all(c.ok for c in checks),",
        "new": "                            ok=bool(checks) and all(c.ok for c in checks),",
        "catchers": _T_PP,
        "expected_catcher": ["test_p5_default_is_not_machine_decidable"],
    },
    {
        "id": "M53f-empty-mutation-registry-passes",
        "lesson": "不查守护条目在场 → 空登记簿的逃逸数也是 0,那个'全捕'与本"
                  "profile 无关",
        "file": _PP,
        "old": "    ok = escaped == 0 and stale == 0 and mis == 0 and not missing",
        "new": "    ok = escaped == 0 and stale == 0 and mis == 0",
        "catchers": _T_PP,
        "expected_catcher": ["test_an_empty_registry_of_mutations_does_not_pass"],
    },
    {
        "id": "M63d-answer-may-live-in-our-own-public-repo",
        "lesson": "不扫**本仓 git 跟踪的文件** → 一次勘察留下的 naive_plugins.py "
                  "(12 个函数全实现,__init__/init_spec 与原件 AST 逐字相同)就躺在"
                  "证据目录里,而 remote 是**公开** GitHub 仓。扫描边界画错了:"
                  "答案不在交付树里,在出题方自己的仓里(2026-08-15 搜捕实录)",
        "file": _PH2,
        "old": "    bad = structural_checks() + selfcheck(original) + repo_scan(original)",
        "new": "    bad = structural_checks() + selfcheck(original)",
        "catchers": _T_PH2,
        "expected_catcher": ["test_h7_repo_scan_is_wired_into_main_not_just_defined"],
    },
    {
        "id": "M63e-carve-leaves-its-own-fingerprint",
        "lesson": "挖空留下孤儿 import → 上游是 lint-clean 的,'恰好一条 F401'"
                  "在这棵树里是结构性异常,等于指着被挖的函数说'这里用得着它'",
        "file": _PH2,
        "old": "        if not alive:",
        "new": "        if False:",
        "catchers": _T_PH2,
        "expected_catcher": ["test_h1b_carving_cleans_up_its_own_footprint"],
    },
    {
        "id": "M63f-allowlist-is-only-one-level-deep",
        "lesson": "bench 白名单粒度只到顶层目录名 → 一张票放行整个目录,而它里面"
                  "同时装着交付树与**未挖空的原件 + .pth 指回原件的 venv**;"
                  "一条 `cat .pth` 逐字节取回 12 个函数体。与 LESSONS #29 "
                  "(offerclaw-transaction-stack 内含三份 PASS 解被整个放行)同型第二次",
        "file": _HG,
        "old": "            strays.extend(_entry_strays(entry))",
        "new": "            pass",
        "catchers": _T_HG,
        "expected_catcher": ["test_bench_allowlist_is_two_levels_deep"],
    },
    # ---- M66:盲攻测量驱动器(2026-08-16,D5 彩排产物)。heldout_admission
    # 是纯判官,数字从这里来 —— 量法一松,0.95 那条线就是摆设。四条守的都是
    # "分数掺水的方式":基线不配当尺子仍产 ratio / 分母来自被测方 / 离线
    # 变成声称 / 回归面混进能力面。
    {
        "id": "M66a-green-delta-in-baseline-not-refused",
        "lesson": "基线上就绿的 delta 测试不拒 → FAIL_TO_PASS 不再被实测,"
                  "'parent 树上就能过的新行为'混进分母,ratio 虚低,烂候选准入",
        "file": _BAM,
        "old": "    green_deltas = sorted(set(delta_nodes) - red - skipped_nodes)",
        "new": "    green_deltas = []",
        "catchers": _T_BAM,
        "expected_catcher": ["test_b7_delta_baseline_must_red_exactly_the_delta_set"],
    },
    {
        "id": "M66b-denominator-from-the-attacked-run",
        "lesson": "全套件分母改读攻击后 junit → 攻击件打崩收集期,节点数缩水,"
                  "分母跟着缩 —— 被测方决定分母(U3 的老病,第三次出现)",
        "file": _BAM,
        "old": '        return BlindAttack(total=baseline["total"] - baseline["skipped"],',
        "new": '        return BlindAttack(total=attacked["total"] - attacked["skipped"],',
        "catchers": _T_BAM,
        "expected_catcher": ["test_b6_denominator_is_the_baseline_total"],
    },
    {
        "id": "M66c-offline-env-only-fills-gaps",
        "lesson": "死代理从覆盖退化成 setdefault → 外面挂着真代理时照常联网,"
                  "'离线'从跑出来的变回声称的",
        "file": _BAM,
        "old": '        env[k] = "http://127.0.0.1:9"',
        "new": '        env.setdefault(k, "http://127.0.0.1:9")',
        "catchers": _T_BAM,
        "expected_catcher": ["test_b4_subprocess_env_is_forced_offline"],
    },
    # ---- M67:v2 卫生判据(用户裁决 b,prereg-v2 §1.1)。skip 从"单跑即拒"
    # 改为"集合稳定 + delta 零 skip + 出分母";这两条守改线后的新语义。
    {
        "id": "M67a-delta-node-skip-not-refused",
        "lesson": "S-b 被拆:delta 节点被 skip 也照常测 → 隐藏 oracle 拒绝判卷"
                  "的候选混进池子,FAIL_TO_PASS 成了没验过的宣称",
        "file": _BAM,
        "old": "    delta_skipped = sorted(set(delta_nodes) & skipped_nodes)",
        "new": "    delta_skipped = []",
        "catchers": _T_BAM,
        "expected_catcher": ["test_b1b_delta_node_skips_refuse_but_platform_skips_do_not"],
    },
    {
        "id": "M67b-skips-back-inside-the-denominator",
        "lesson": "S-c 被拆:skip 回到分母 → 25 条平台 skip 虚增分母压低 ratio,"
                  "烂候选显得可测(与 M66b 同锚不同病:那条是分母来源,这条是"
                  "分母口径)",
        "file": _BAM,
        "old": '        return BlindAttack(total=baseline["total"] - baseline["skipped"],',
        "new": '        return BlindAttack(total=baseline["total"],',
        "catchers": _T_BAM,
        "expected_catcher": ["test_b12_skipped_nodes_are_outside_numerator_and_denominator"],
    },
    {
        "id": "M66f-venv-bin-not-on-the-subprocess-path",
        "lesson": "venv/bin 不再前置进 PATH → 套件里裸 `python` 起的子进程解析"
                  "不到(sqlglot test_lazy_load 实测 FileNotFoundError),基线在"
                  "我们这红、在上游 CI 绿 —— 错在量具,账记给套件",
        "file": _BAM,
        "old": '    out["PATH"] = f"{venv / \'bin\'}:{out.get(\'PATH\', \'\')}"',
        "new": '    out["PATH"] = out.get("PATH", "")',
        "catchers": _T_BAM,
        "expected_catcher": ["test_b10_venv_bin_is_prepended_to_the_subprocess_path"],
    },
    {
        "id": "M66d-regression-greens-blended-into-the-ratio",
        "lesson": "delta 分子不再与 delta 集求交 → 旧套件的绿全进分子,"
                  "回归面冒充能力面,ratio 能超过 1",
        "file": _BAM,
        "old": '    won = delta_nodes & set(attacked.get("passed_nodes", ()))',
        "new": '    won = set(attacked.get("passed_nodes", ()))',
        "catchers": _T_BAM,
        "expected_catcher": ["test_b8_delta_ratio_is_over_the_delta_set_only"],
    },
    # ---- M65:变异闸门自身的归因执法(2026-08-16)。M59c/M62d,e/M64c 一天
    # 三次同型逃逸:合成缺陷被更早的另一条判断先杀,被考的判断掏掉也看不出
    # 差别 —— 于是把"CAUGHT 必须由声明的判断抓住"变成机器执法。这五条守的
    # 就是执法本身:每一条被砍掉,闸门都还在发"全捕",只是那份全捕又开始
    # 替不存在的防线背书。
    {
        "id": "M65a-any-red-counts-as-the-declared-judge",
        "lesson": "归因命中退化成'红了就算' → MISATTRIBUTED 永不可达,"
                  "M59c/M64c 那种被别的判断抢先抓住的形状全部隐形",
        "file": _MG,
        # 自指锚:被守码与登记簿同文件,字面量拆开写,否则登记项把自己数成第 2 次
        "old": "        hits = sorted(n for n in failed "
               "if _matches_declared(n, declared))",
        "new": "        hits = sorted(failed)",
        "catchers": _T_MA,
        "expected_catcher": ["test_red_without_the_declared_judge_is_misattributed"],
    },
    {
        "id": "M65b-unattributed-list-silenced",
        "lesson": "报表不再列未声明存量 → '还没声明'与'声明并验证过'长一个样,"
                  "诚实清单静默清零(沉默的缺口最像没有缺口)",
        "file": _MG,
        "old": '        "unattributed": [r["id"] for r in results\n'
               '                         if r["outcome"] == "CAUGHT"\n'
               '                         and r.get("attribution") == "UNDECLARED"],',
        "new": '        "unattributed": [],',
        "catchers": _T_MA,
        "expected_catcher": ["test_report_lists_are_derived_from_results_not_freeform"],
    },
    {
        "id": "M65c-plumbing-failure-becomes-a-catch",
        "lesson": "junitxml 解析不出失败节点时冒充 CAUGHT → 测量仪故障被记成"
                  "测到了东西,而它长得跟正常捕获一模一样",
        "file": _MG,
        # 自指锚,同 M65a:拆开写
        "old": '        return "GATE_PLUMBING", '
               '{"pytest_exit": exit_code}',
        "new": '        return "CAUGHT", {"attribution": "UNDECLARED"}',
        "catchers": _T_MA,
        "expected_catcher": ["test_red_exit_with_no_parsed_nodes_is_gate_plumbing_not_caught"],
    },
    {
        "id": "M65d-promotion-ignores-misattribution",
        "lesson": "晋级判据不看归因错位 → 一份混着 MISATTRIBUTED 的证据照样"
                  "给 profile 背书(散文说三种坏结局都得是零、代码只数两种 ——"
                  "LESSONS #45 二的形状)",
        "file": _PP,
        "old": "    ok = escaped == 0 and stale == 0 and mis == 0 and not missing",
        "new": "    ok = escaped == 0 and stale == 0 and not missing",
        "catchers": _T_PP,
        "expected_catcher": ["test_g5_nonzero_misattribution_fails"],
    },
    {
        "id": "M65e-attribution-canary-stops-gating",
        "lesson": "归因金丝雀不再拦 → 摆好的归因错位抓不出来也照常发绿,"
                  "C1 变成装饰(与 C0 被拆同型,只是拆的是归因那一半)",
        "file": _MG,
        "old": '    if outcome == "MISATTRIBUTED":\n        return None',
        "new": "    if True:\n        return None",
        "catchers": _T_MA,
        "expected_catcher": ["test_attribution_canary_verdict_gates_the_run"],
    },
    # ---- M64:held-out 准入。两轮实测(全仓 111 函数逐个挖空 + 五次独立强攻)
    # 把一件事钉死了:**"挖空之后红了多少条"是个坏指标** —— 红得最多的那个
    # 是三行字典查找。红的数量量的是"什么都不做",不是"写错了"。
    {
        "id": "M64a-silence-counts-as-a-pass",
        "lesson": "没量过就放行 → '还没量'与'量了没问题'在台账里长得一模一样,"
                  "而一道没被量过的 held-out 题,它的分数是什么意思谁也说不清",
        "file": _HA,
        "old": "    if attack is None:",
        "new": "    if False:",
        "catchers": _T_HA,
        "expected_catcher": ["test_a1_silence_is_not_a_pass"],
    },
    {
        "id": "M64b-threshold-drifts-above-the-measured-floor",
        "lesson": "阈值放回汇总建议的 0.98 → 五个实测候选里 plugins(97.8%,"
                  "**就是被判死的 v1 本体**)与 etag(97.3%)双双漏网。"
                  "线必须画在**这个形态实测出来的地板**之下",
        "file": _HA,
        "old": "MAX_BLIND_ATTACK_RATIO = 0.95",
        "new": "MAX_BLIND_ATTACK_RATIO = 0.98",
        "catchers": _T_HA,
        "expected_catcher": ["test_a2_the_five_real_candidates_all_die"],
    },
    {
        "id": "M64c-prose-residual-counts-as-behaviour",
        "lesson": "净剩不查是不是散文 → etag 那个候选净剩 15 条(五个里最多),"
                  "全是三句 warning 的英文措辞比对,换成真值即满分",
        "file": _HA,
        "old": "    residual = attack.residual_kinds - _PROSE_RESIDUALS",
        "new": "    residual = attack.residual_kinds",
        "catchers": _T_HA,
        "expected_catcher": ["test_a6_prose_residual_is_caught_even_when_the_ratio_is_fine"],
    },
    # ---- M63:H2 宿主副本的部署层。这道题只有 1–2 bit,**答案能捞出来一次
    # 就当场归零**,而所有数字看起来照常。三条守的是"删了"与"捞不出来"
    # 之间那段距离。
    {
        "id": "M63g-overlapping-carve-spans-swallow-siblings",
        "lesson": "嵌套 def 的重叠 span 不去重 → 内层先替换、外层再按**陈旧坐标**"
                  "切,把后移上来的兄弟方法整个吞掉,连签名都不剩(2026-08-16 彩排"
                  "当场抓到:pagination 五个兄弟方法消失;plugins 表达不出这个形状,"
                  "H1 从未红过 —— 靶子表达不出缺陷,钉死就等于不存在)",
        "file": _PH2,
        "old": "    spans = [s for s in spans\n"
               "             if not any(o != s and o[0] <= s[0] and s[1] <= o[1] for o in spans)]",
        "new": "    spans = list(spans)",
        "catchers": _T_PH2,
        "expected_catcher": ["test_h1c_sibling_methods_survive_a_method_with_nested_defs"],
    },
    {
        "id": "M63a-fingerprints-not-self-calibrated",
        "lesson": "泄漏指纹不排掉'原仓 seam 之外也有的行' → 通用惯用行(如 "
                  "`if self.openapi_version.major < 3:`)全部报出来,真信号被淹;"
                  "实测头两版就栽在这",
        "file": _PH2,
        "old": "    return [(n, pat) for n, pat in out if not re.search(pat, blob)]",
        "new": "    return out",
        "catchers": _T_PH2,
        "expected_catcher": ["test_h2_fingerprints_are_self_calibrating"],
    },
    {
        "id": "M63b-carving-eats-the-docstring",
        "lesson": "挖空连 docstring 一起挖 → 那是**改写宿主**,而不是挖空;"
                  "按 F1,改写过的宿主一律不算 held-out(ENRICHED)",
        "file": _PH2,
        "old": "        i = 0\n"
               "        if (body and isinstance(body[0], ast.Expr)",
        "new": "        i = 0\n"
               "        if (False and isinstance(body[0], ast.Expr)",
        "catchers": _T_PH2,
        "expected_catcher": ["test_h1_carving_removes_bodies_but_keeps_signatures_and_docstrings"],
    },
    {
        "id": "M63c-git-dir-survives-into-the-copy",
        "lesson": "`.git` 留在副本里 → `git show HEAD:<seam>` 一行拿到原件,"
                  "整道题当场归零",
        "file": _PH2,
        "old": '    ".git",          # `git show HEAD:<seam>` 一行拿到原件',
        "new": "    # (剥离清单里没有 .git)",
        "catchers": _T_PH2,
        "expected_catcher": ["test_h4_every_strip_entry_names_a_real_retrieval_path",
                             "test_h7_repo_scan_is_wired_into_main_not_just_defined"],
    },
    # ---- M62:差分注入。修的是 A1 的**结构上限**(F2) —— U4 比的是
    # digest 相等,而上游算得对、被测方自己也算得对时两者恒等。这几条守的都是
    # "修了个寂寞":机制还在、标记还发,只是它不再不可预测,于是等于没修。
    {
        "id": "M62a-tag-ignores-the-input",
        "lesson": "标记不按输入分 → 一次 run 里所有项同一个标记,把别项的抄过来"
                  "就能过。与'U3 分母不能来自被测方'同源:判据不能锚在被测方"
                  "自己搬得动的东西上",
        "file": _DIF,
        "old": '    return hmac.new(secret, digest_of(payload, canon=CANON_JSON).encode("utf-8"),',
        "new": '    return hmac.new(secret, b"fixed",',
        "catchers": _T_DIF,
        "expected_catcher": ["test_d2_the_tag_is_scoped_to_the_input"],
    },
    {
        "id": "M62b-tag-ignores-the-secret",
        "lesson": "标记不按密钥分 → 被测方自己就能算出来,差分注入等于没有,"
                  "而矩阵照样'全绿'(它只看红在哪,不看标记算不算得出)",
        "file": _DIF,
        'old': '    return hmac.new(secret, digest_of(payload, canon=CANON_JSON).encode("utf-8"),',
        'new': '    return hmac.new(b"", digest_of(payload, canon=CANON_JSON).encode("utf-8"),',
        "catchers": _T_DIF,
        "expected_catcher": ["test_d3_the_tag_is_unpredictable_without_the_secret"],
    },
    {
        "id": "M62c-secret-is-not-random",
        "lesson": "run 密钥退化成常量 → 跨 run 可复用,昨天算出的标记今天还能用",
        "file": _DIF,
        "old": "    return os.urandom(32)",
        "new": '    return b"0" * 32',
        "catchers": _T_DIF,
        "expected_catcher": ["test_d3_the_tag_is_unpredictable_without_the_secret"],
    },
    {
        "id": "M62d-matrix-does-not-require-the-two-modes-to-differ",
        "lesson": "矩阵不查'同一控制组两种模式必须分开' → 注入没起作用也算过,"
                  "而这正是这张表**唯一**要证明的事",
        "file": _DIM,
        "old": "    if nc9_plain and nc9_pert and not (",
        "new": "    if False and not (",
        "catchers": _T_DIF,
        "expected_catcher": ["test_d8_the_matrix_judge_catches_planted_defects"],
    },
    {
        "id": "M62e-matrix-ignores-the-wall-side",
        "lesson": "矩阵不查正控 → 差分注入把诚实实现也判死了也算过,"
                  "那不是修复是另一种墙(LESSONS #44)",
        "file": _DIM,
        "old": '    if any(r["actual"] != "PASS" for r in pos):',
        "new": "    if False:",
        "catchers": _T_DIF,
        "expected_catcher": ["test_d8_the_matrix_judge_catches_planted_defects"],
    },
    # ---- M59:失败侧。判据**红了之后**那一段 —— 控制矩阵一步没走过,
    # 而它悄悄失效时,系统照跑、矩阵照绿,只是每一次"没真用上游"都被记成
    # BLOCKED(不算模型失败、可重跑),这道题等于白出。
    # ---- M60:C 轨(第二宿主)开工前的记账加固。三条守的都是**同一种病**:
    # 散文说不算、代码算了(LESSONS #45 二)。它们现在全都"看起来没事",
    # 因为 held-out 还是 0、第二宿主还没建 —— 那正是最坏的时机。
    # ---- M61:C 轨,宿主耦合拆开之后的守护。三条都是"泛化顺手把第一宿主
    # 改坏"或"泛化只是多了几个没人读的字段"——两种都让这次改动白做。
    {
        "id": "M61d-wheelhouse-path-back-to-the-first-hosts-name",
        "lesson": "轮仓路径又写死成 `wheelhouse-offerclaw-<commit7>` → 第二宿主的"
                  "轮仓找不到,而报的是'冻结 wheelhouse 缺失',看起来像没建轮仓,"
                  "不像'harness 在按别人的名字找'。第六处宿主耦合",
        "file": _HD,
        "old": '        or getattr(host, "wheelhouse_path", "")',
        "new": '        or ""',
        "catchers": _T_HD,
        "expected_catcher": ["test_k19_wheelhouse_path_is_declarable_and_defaults_unchanged"],
    },
    {
        "id": "M61e-fabricated-env-baseline-hash",
        "lesson": "没有 wheelhouse manifest 时凭空给个环境基线哈希 → 台账里那一格"
                  "看起来煞有介事,而它什么都不代表(纸面值当真实测量值,源 §15)",
        "file": _HD,
        "old": '            self.env_baseline_hash = "UNKNOWN"',
        "new": '            self.env_baseline_hash = "sha256:" + "0" * 64',
        "catchers": _T_HD,
        "expected_catcher": ["test_k19_wheelhouse_path_is_declarable_and_defaults_unchanged"],
    },
    {
        "id": "M61a-public-command-back-to-a-constant",
        "lesson": "公开面又写死 → 契约的 public_test_command 说了不算,"
                  "**契约说的和实际跑的不是一回事**;第二宿主的公开面在别处",
        "file": _HD,
        "old": "        cmd = list(self.contract.acceptance.public_test_command)",
        "new": '        cmd = ["python", "-m", "pytest", "public_tests/", "-q", "-p", "no:cacheprovider"]',
        "catchers": _T_HD,
        "expected_catcher": ["test_k14_public_command_comes_from_the_contract_not_a_constant"],
    },
    {
        "id": "M61b-setup-steps-run-out-of-order",
        "lesson": "建环境把装依赖之后的步骤提前跑 → rag_ingest.py 在 chromadb "
                  "装上之前执行,零预算 BLOCKED。**单测抓不到(不建环境)**,"
                  "2026-08-15 泛化当天由端到端冒烟抓住",
        "file": _HD,
        "old": "        head = cmds[:pip_idx] if pip_idx is not None else cmds",
        "new": "        head = [c for i, c in enumerate(cmds) if i != pip_idx]",
        "catchers": _T_HD,
        "expected_catcher": ["test_k17_setup_steps_run_in_the_declared_order"],
    },
    {
        "id": "M61c-health-check-gating-flag-ignored",
        "lesson": "健康检查不认 gating=False → OfferClaw 的 doctor.py(已知预期"
                  "差异:chunks 口径 / 合成密钥 WARN)变成门禁,每发零预算 BLOCKED",
        "file": _HD,
        "old": "            if hc.gating:",
        "new": "            if True:",
        "catchers": _T_HD,
        "expected_catcher": ["test_k18_health_check_gating_flag_is_honoured"],
    },
    {
        "id": "M60e-enriched-host-counts-as-heldout",
        "lesson": "严口径只查测试文本来源,不查 harness 往宿主里加没加语义 → "
                  "把宿主改得面目全非、让上游测试实际在考**我们发明的**接线,"
                  "闸门照样认它是 held-out(2026-08-15 设计评审当场查出的盲区,"
                  "有一份设计的最大 trap 就是 71 条上游测试为自造语义服务)",
        "file": _BR,
        "old": '                and c.get("host_modification_mode", HOST_MOD_PRISTINE)\n'
               "                in _HELDOUT_OK_HOST_MODS),",
        "new": "                ),",
        "catchers": _T_RCL,
        "expected_catcher": ["test_k20_harness_enriched_hosts_can_never_be_heldout"],
    },
    {
        "id": "M60d-our-own-oracle-counts-as-heldout",
        "lesson": "严口径失效 → 我们自己写的 oracle 也算 held-out,而 held-out 是"
                  "四类分母里**唯一被直接读成模型能力**的那个;更糟的是它只信"
                  "旁挂分类文件的自述,手一滑置个 true 就成立(用户 2026-08-15 裁决)",
        "file": _BR,
        "old": '                and c.get("oracle_authorship") == ORACLE_AUTHORSHIP_EXTERNAL',
        "new": "                and True",
        "catchers": _T_RCL,
        "expected_catcher": ["test_k12_our_own_oracle_can_never_be_counted_as_heldout"],
    },
    {
        "id": "M60a-heldout-denominator-has-no-deductions",
        "lesson": "held-out 分母不扣除 → 冒烟(35 发)、探索性加发(7)、已裁定"
                  "无效(4)全进那个**唯一会被读成模型能力**的数字",
        "file": _BR,
        "old": '            1 for r in gateable if r["counts_toward_heldout_benchmark"]),',
        "new": '            1 for r in rows if r["counts_toward_heldout_benchmark"]),',
        "catchers": _T_RCL,
        "expected_catcher": ["test_k8_heldout_gets_the_same_four_deductions_as_passes"],
    },
    {
        "id": "M60b-second-host-runs-land-in-the-first-hosts-stage",
        "lesson": "阶段归属只看 task_id 前缀 → 第二宿主的 `t3-<新宿主>-…` 自动"
                  "进 stages.T3。不是理论风险:t3-sidecar(另一份 oracle)现在"
                  "就在 T3 的 total 里,只靠 run_purpose 挡在 passes 外",
        "file": _BR,
        "old": '                and _same_host(r)]',
        "new": "                ]",
        "catchers": _T_RCL,
        "expected_catcher": ["test_k9_a_second_host_run_does_not_land_in_the_first_hosts_stage"],
    },
    {
        "id": "M60c-missing-host-id-silently-becomes-the-baseline-host",
        "lesson": "落账不拦缺失 host_id → normalise 填 UNKNOWN,而 UNKNOWN 被当"
                  "第一宿主放行,新宿主漏填 = 静默进旧闸门(M58b 的形状)",
        "file": _BR,
        "old": '    if rec.get("host_id") in (None, "", UNKNOWN):',
        "new": "    if False:",
        "catchers": _T_RCL,
        "expected_catcher": ["test_k10_writing_a_run_without_a_host_id_is_refused"],
    },
    {
        "id": "M59a-negative-control-silently-becomes-positive",
        "lesson": "`--fake control:X` 退回正控 → 七个负控全变正控,失败侧矩阵"
                  "八行全绿,而'全绿'正好长得像'全部通过'",
        "file": _HD,
        "old": '    src_control = runner.task_dir / "controls" / name',
        "new": '    src_control = runner.task_dir / "controls" / "positive"',
        "catchers": _T_FS,
        "expected_catcher": ["test_f7_control_mode_injects_the_control_it_was_asked_for"],
    },
    {
        "id": "M59b-failure-side-judge-ignores-blocked",
        "lesson": "失败侧判定不查 verdict → 负控落在 BLOCKED('不是被测方的错、"
                  "可重跑')也算过,而那正是这张表唯一要拦的东西",
        "file": _FSM,
        "old": "        if got != want_verdict:",
        "new": "        if False:",
        "catchers": _T_FS,
        "expected_catcher": ["test_f6_the_matrix_judge_itself_catches_a_planted_defect"],
    },
    {
        "id": "M59c-failure-side-judge-accepts-undeclared-types",
        "lesson": "失败侧判定不查 taxonomy → 归因报一个契约没声明的类型也算过,"
                  "那就是用未言明的要求判人(B6/B7/B10 那条 blocking 的病)",
        "file": _FSM,
        "old": "        stray = [t for t in types if t not in taxonomy and t != \"UNKNOWN\"]",
        "new": "        stray = []",
        "catchers": _T_FS,
        "expected_catcher": ["test_f6_the_matrix_judge_itself_catches_a_planted_defect"],
    },
    {
        "id": "M58b-pq-runs-inflate-the-stage-gate",
        "lesson": "PQ 发次进阶段闸门 → profile 资格审自己把 T3 的 passes 从 3 抬到 7,"
                  "而 `_denominators` 里白纸黑字写着它'不充闸门'。散文说不算、代码"
                  "算了(2026-08-15 首批 PQ 当场撞出来)",
        "file": _BR,
        "old": '    gateable = [r for r in prereg if r["run_purpose"] not in NON_GATEABLE_PURPOSES]',
        "new": '    gateable = [r for r in prereg if r["run_purpose"] not in MECHANISM_PURPOSES]',
        "catchers": _T_RCL,
        "expected_catcher": ["test_k7_profile_qualification_does_not_count_toward_the_stage_gate"],
    },
    {
        "id": "M58a-g6-reads-a-field-nobody-writes",
        "lesson": "G6 读 `runtime_profile`,而台账写的是 `runtime_profile_id` —— "
                  "少个后缀,任何 profile 的 G6 恒为 0。一条**永不可满足**的判据,"
                  "而它长得跟'确实还没人跑过'一模一样(2026-08-15 首批发次撞出来)",
        "file": _PP,
        "old": '            if p.id in (r.get("runtime_profile_id"), r.get("runtime_profile"))',
        "new": '            if p.id == r.get("runtime_profile")',
        "catchers": _T_PP,
        "expected_catcher": ["test_p4c_g6_is_satisfiable_by_the_field_the_harness_actually_writes"],
    },
    # ---- M57:2026-08-15 可搬运性审查的 should-fix(S1–S4)。守的全是**归因**:
    # 每一条被砍掉,系统都还能跑、矩阵也还是绿的,只是**这笔账记错了人**。
    {
        "id": "M57a-upstream-crash-blamed-on-the-agent",
        "lesson": "不先问上游有没有崩 → 我们的浏览器崩了,报出来是'它没交东西';"
                  "而模型看见 502 会合理地改走自抓,终点还被归成'重实现'",
        "file": _SSN,
        "old": "    failures = session.upstream_failures_on_expected_items()",
        "new": "    failures = []",
        "catchers": _T_SW,
        "expected_catcher": ["test_w4c_upstream_failure_is_reported_before_extraction"],
    },
    {
        "id": "M57b-upstream-failures-not-scoped-to-our-items",
        "lesson": "上游故障不按 harness 自己算的 input_digest 圈定 → 拿自造的坏输入"
                  "把浏览器打崩就能换 BLOCKED(不算模型失败、可重跑),"
                  "交白卷比交错答案划算",
        "file": _SSN,
        "old": '        want = {u["input_digest"] for u in self.expected_units()}',
        "new": '        want = {f.get("input_digest") for f in self.handle.upstream_failures()}',
        "catchers": _T_SW,
        "expected_catcher": ["test_w9_upstream_failures_are_scoped_to_our_own_items"],
    },
    {
        "id": "M57c-crash-leaves-no-trace",
        "lesson": "上游崩了不留痕 → 核验期只看见'它没交东西',harness 的故障"
                  "判成被测方失败",
        "file": _USC,
        "old": "                srv.upstream_failures.append({                            # type: ignore[attr-defined]",
        "new": "                [].append({",
        "catchers": _T_SW,
        "expected_catcher": ["test_w10_an_upstream_crash_is_recorded_and_does_not_forge_a_receipt"],
    },
    {
        "id": "M57d-crash-looks-like-bad-input",
        "lesson": "上游崩了报 400 → 与'被测方交了坏入参'混成一件事,"
                  "而两者一个该重跑、一个该判失败",
        "file": _USC,
        "old": '            return self._json(502, {"error": f"{type(e).__name__}: {e}",',
        "new": '            return self._json(400, {"error": f"{type(e).__name__}: {e}",',
        "catchers": _T_SW,
        "expected_catcher": ["test_w10_an_upstream_crash_is_recorded_and_does_not_forge_a_receipt"],
    },
    {
        "id": "M57e-adoption-failure-goes-back-to-blocked",
        "lesson": "采纳不成立又走回 missing_external → 短路成 BLOCKED,与'profile "
                  "没登记''宿主基线不健康'同桶。这道题存在的全部理由就是把"
                  "'没真用上游'判成被测方失败,一判出来就塞进'可重跑',等于白判",
        "file": _HD,
        "old": '        return "agent"',
        "new": '        return "harness"',
        "catchers": _T_SW,
        "expected_catcher": ["test_w5c_the_routing_decision_itself_is_pinned_by_behavior"],
    },
    {
        "id": "M57f-extractor-swallows-bad-shape",
        "lesson": "工件全读不出仍返回 None → 被测方交了形状不对的东西,报出来是"
                  "'取件失败(harness 的问题)',归因整个反了(审查 S4)",
        "file": "benchmarks/v2/tasks/t3_sidecar_v1/delivery_extractor.py",
        "old": "    if not out and bad:",
        "new": "    if False:",
        "catchers": _T_T3S,
        "expected_catcher": ["test_s16_extractor_distinguishes_missing_dir_from_unreadable_artifacts"],
    },
    {
        "id": "M57g-host-swallows-the-shape-error",
        "lesson": "宿主的裸 except 把 DeliveryExtractionError 吞回 None → S4 只修了"
                  "一半,形状错又变回含糊的'取不到交付'",
        "file": _HD,
        "old": '            if type(e).__name__ == "DeliveryExtractionError":',
        "new": "            if False:",
        "catchers": _T_T3S,
        "expected_catcher": ["test_s17_unreadable_delivery_is_not_reported_as_extraction_failure"],
    },
    # ---- M56:sidecar 接进 host-run。这一段最容易出的错不是"功能不对",
    # 而是**报错报得像另一件事** —— 三条守的都是归因不许混。
    {
        "id": "M56a-agent-env-leaks-the-ledger",
        "lesson": "台账路径漏进 agent 环境 → U1 的全部意义没了(谁都能伪造回执)",
        "file": _USC,
        "old": ('        return {"REPOPROOF_SIDECAR_URL": self.base_url,\n'
                '                "REPOPROOF_SIDECAR_TOKEN": self.token}'),
        "new": ('        return {"REPOPROOF_SIDECAR_URL": self.base_url,\n'
                '                "REPOPROOF_LEDGER": str(self.ledger_path),\n'
                '                "REPOPROOF_SIDECAR_TOKEN": self.token}'),
        "catchers": _T_SW,
        "expected_catcher": ["test_w2_neither_agent_nor_oracle_gets_the_key_or_ledger"],
    },
    {
        "id": "M56b-one-item-is-enough",
        "lesson": "U3 分母允许 <2 → '一次调用充抵所有项'永远抓不住",
        "file": _SSN,
        "old": '    if item_count < 2:',
        "new": "    if False:",
        "catchers": _T_SW,
        "expected_catcher": ["test_w7_item_count_must_be_at_least_two"],
    },
    {
        "id": "M56c-extraction-failure-becomes-adoption-failure",
        "lesson": "取件失败与采纳不成立混成一个 → harness 的毛病记成被测方的失败",
        "file": _SSN,
        "old": '        return {"ok": False, "reason": "NO_DELIVERY_EXTRACTED",',
        "new": '        return {"ok": False, "reason": "RECEIPT_VERIFICATION_FAILED",',
        "catchers": _T_SW,
        "expected_catcher": ["test_w4b_no_delivery_is_reported_as_extraction_failure"],
    },
    # ---- M55:T3-SIDECAR v1 的任务级判据。
    {
        "id": "M55a-adoption-degrades-to-set-membership",
        "lesson": "采纳判据从**逐项对应**退回**集合成员** → '一次调用充抵所有项'"
                  "过得去(实测:nc3 只红在 U3,U4 反而绿)",
        "file": _VTR,
        "old": "            want = by_nonce.get(rn)",
        "new": "            want = [d for v in by_nonce.values() for d in v]",
        "catchers": _T_T3S,
        # 首跑执法当场抓到的归因错位(2026-08-16):复审时凭语义声明了 s4,
        # 而这条变异的活体红名单里只有矩阵新鲜度检查 —— s* 钉死大多读**已
        # 落盘**的矩阵,对这条变异不上场。这也如实暴露了 M55a 的单薄:今天
        # 站在这个缺陷与绿之间的只有 freshness 一道,值得日后补专用活体钉死。
        "expected_catcher": ["test_matrix_is_fresh"],
    },
    {
        "id": "M55b-empty-delivery-counts-as-adoption",
        "lesson": "空交付算采纳 → '什么都不交'反而最容易过",
        "file": _VTR,
        "old": ('        if not delivery:\n'
                '            return False, "交付为空 —— 空交付不算采纳"'),
        "new": ('        if not delivery:\n'
                '            return True, "空"'),
        "catchers": _T_T3S,
        "expected_catcher": ["test_s2_every_negative_reds_where_declared"],
    },
    # ---- 2026-08-15 可搬运性审查补上的三个洞,各配一条变异 ----
    {
        "id": "M55c-adoption-ignores-the-input-digest",
        "lesson": "U4 不核 input_digest → 同 nonce 换个自造输入再调一次,"
                  "sidecar 就成了'任意内容的签名机'(审查 B1,修前十项全绿)",
        "file": _VTR,
        "old": "            if r.input.digest != exp.get(rn):",
        "new": "            if False:",
        "catchers": _T_T3S,
        "expected_catcher": ["test_s8_laundering_via_forged_input_is_caught"],
    },
    {
        "id": "M55d-adoption-denominator-from-the-sut",
        "lesson": "U4 的分母回到 len(delivery) → 全调只交一半照过(审查 B2)。"
                  "与 U3 的教训同源:分母不能来自被测方",
        "file": _VTR,
        "old": "        missing = sorted(set(exp) - delivered)",
        "new": "        missing = []",
        "catchers": _T_T3S,
        "expected_catcher": ["test_s9_partial_delivery_is_caught"],
    },
    {
        "id": "M55e-blank-output-counts-as-adoption",
        "lesson": "空产出算采纳 → CANON_TEXT_SQUASH 下空对空,而 worker 找不到"
                  "#answer 时返回空串且不抛,sidecar 照签(审查 B3)",
        "file": _VTR,
        "old": "            if not raw.strip():",
        "new": "            if False:",
        "catchers": _T_T3S,
        "expected_catcher": ["test_s10_blank_and_malformed_are_caught_and_attributed"],
    },
    # ---- M54:真上游(browser-use + 封存 Chromium)的 conformance。
    {
        "id": "M54a-suite-topology-mixup",
        "lesson": "两个 suite 都有 topology.py,裸 import 被先到的赢走 → 浏览器矩阵"
                  "报出 canary 的拓扑,而整张表其余部分全绿、看不出异样(实测发生过)",
        "file": _BCF,
        "old": '        return 2\n    print("拓扑核验(A1 的地基,真上游版):")',
        "new": '        pass\n    print("拓扑核验(A1 的地基,真上游版):")',
        "catchers": _T_BCF,
        "expected_catcher": ["test_b1b_a_foreign_suites_topology_is_refused"],
    },
    {
        "id": "M54b-keychain-prompt-returns",
        "lesson": "去掉 --password-store=basic → Chromium 向 macOS 钥匙串要密码,"
                  "弹出**模态**对话框把启动挂住;表现成'浏览器极慢/超时',"
                  "日志里看不出原因(实测 16.3s → 400)",
        "file": _BWK,
        "old": '            "--password-store=basic", "--use-mock-keychain",',
        "new": "",
        "catchers": _T_BCF,
        "expected_catcher": ["test_chromium_never_touches_the_macos_keychain"],
    },
    {
        "id": "M54c-browser-goes-online",
        "lesson": "去掉死代理 → 离线就成了声称而不是跑出来的",
        "file": _BWK,
        "old": '        argv += ["--proxy-server=127.0.0.1:1",',
        "new": '        argv += ["--ignore-certificate-errors",',
        "catchers": _T_BCF,
        "expected_catcher": ["test_offline_flags_are_present"],
    },
    # ---- M52:Sidecar Conformance(A1 的第一个使用者)。
    {
        "id": "M52a-count-check-removed",
        "lesson": "去掉台账外的条数校验 → **尾部截断查不出**(实测:删最后一行"
                  "哈希链照样通过),砍掉不方便的回执变成免费的",
        "file": _RC_V,
        "old": "    if expected_receipt_count is None:",
        "new": "    if False:",
        "catchers": _T_UR,
        "expected_catcher": ["test_r10b_missing_count_is_refused_not_assumed"],
    },
    {
        "id": "M52b-topology-gate-removed",
        "lesson": "不查拓扑就出数 → 上游若够得着,回执与八条攻击全是装饰;"
                  "'它没来敲门'会被读成偷懒,其实是它不需要",
        "file": _SCF,
        "old": "    if not topo[\"ok\"]:",
        "new": "    if False:",
        "catchers": _T_SCF,
        "expected_catcher": ["test_c1b_a_failing_topology_actually_refuses_to_emit"],
    },
    {
        "id": "M52c-conformance-judge-ignores-red-spot",
        "lesson": "红一片就算数 → 分不清四道谓词各自在不在干活",
        "file": _SCF,
        "old": '        elif r["expect"] == "FAIL" and set(r["actual_red"]) != set(r["expect_red"]):',
        "new": "        elif False:",
        "catchers": _T_SCF,
        "expected_catcher": ["test_matrix_judge_catches_a_wrong_red_spot"],
    },
    # ---- M51:Runtime Profile(A1,第 7 步)。sidecar 不是换实现细节,
    # 是换了一道题 —— 下面四条各拆掉一处"两道题被当成一道"的防线。
    {
        "id": "M51a-sidecar-not-in-generation",
        "lesson": "拓扑不进代际 → in-process 与 sidecar 的发次被悄悄合池,"
                  "等于把开卷和闭卷的成绩加起来平均",
        "file": _PR,
        "old": '    if runtime_profile and runtime_profile != "rt-inprocess-v1":',
        "new": "    if False:",
        "catchers": _T_RTP,
        "expected_catcher": ["test_p2_sidecar_shows_up_in_the_execution_generation"],
    },
    {
        "id": "M51b-required-symbols-may-be-empty",
        "lesson": "sidecar 不要求符号集 → U2 判的'调的是不是契约要的能力'"
                  "失去分母,这道判据等于不存在",
        "file": _RTP,
        "old": "            if not self.required_symbols:",
        "new": "            if False:",
        "catchers": _T_RTP,
        "expected_catcher": ["test_p3b_sidecar_without_required_symbols_is_rejected"],
    },
    {
        "id": "M51c-profile-id-can-be-redefined",
        "lesson": "同 id 可改语义 → 台账里一个 profile_id 底下混着两种行为,"
                  "回执的 runtime.profile_id 从此不可信",
        "file": _RTP,
        "old": "    if old is not None and profile_signature(old) != profile_signature(p):",
        "new": "    if False:",
        "catchers": _T_RTP,
        "expected_catcher": ["test_p4_profile_id_is_a_promise"],
    },
    {
        "id": "M51d-symbol-allowlist-not-enforced",
        "lesson": "白名单不在执行前拦 → sidecar 替被测方执行了契约之外的东西;"
                  "U2 只判已发生的执行对不对,拦不住不该发生的执行",
        "file": _USC,
        "old": "        if fn is None:",
        "new": "        if fn is None and False:",
        "catchers": _T_RTP,
        "expected_catcher": ["test_p6_unknown_symbol_is_refused_before_execution"],
    },
    # ---- M50:回执正负控矩阵(第 6 步)。矩阵本身也是个检查器,同样要先
    # 证明自己查得出 —— 否则"八个负控全被抓住"可能只是脚本在读自己的期望值。
    {
        "id": "M50a-matrix-ignores-where-it-reds",
        "lesson": "红一片就算数 → 分不清'我有四道判据'和'我有一道判据起了四个名字'",
        "file": _RCS,
        "old": "            if set(r[\"actual_red\"]) != set(r[\"expect_red\"]):",
        "new": "            if False:",  # noqa: E501 —— 抽成 find_problems 后可被钉死直接考
        "catchers": _T_RCS,
        "expected_catcher": ["test_v2c_the_matrix_judge_itself_catches_a_wrong_red_spot"],
    },
    {
        "id": "M50b-matrix-skips-selfcheck",
        "lesson": "矩阵不自证 → 报出来的'全被抓住'分不清是验证器真抓住了还是脚本在读期望值",
        "file": _RCS,
        "old": "    bad = selfcheck()\n    if bad:",
        "new": "    bad = []\n    if bad:",
        "catchers": _T_RCS,
        "expected_catcher": ["test_v4_strong_matrix_is_fresh"],
    },
    {
        "id": "M50c-discrimination-gate-removed",
        "lesson": "不查判别力 → 一道恒红的判据与'永远报错'无从区分,却照样发绿",
        "file": _RCS,
        "old": "        if not green_in:",
        "new": "        if False:",
        "catchers": _T_RCS,
        "expected_catcher": ["test_v3_each_predicate_family_reds_and_greens"],
    },
    # ---- M49:上游执行回执(A0)。用户 2026-08-14 的提醒 —— 回执**不能是
    # 调用日志**:`browser_use.do_something(); return my_own_impl()` 这段能让
    # 任何"调用发生过"式的判据全过。下面七条各拆掉一道绑定,对应七种绕过。
    {
        "id": "M49a-adoption-defaults-to-pass",
        "lesson": "#R5:没登记采纳谓词就默认放行 → 只证明 U1–U3 的回执看起来"
                  "像证明了全部四件,正是'调真包用自己结果'的形状",
        "file": _RC_V,
        "old": "    if pred is None:\n        f.append(Finding(\"U4.adoption\", False,",
        "new": "    if pred is None:\n        f.append(Finding(\"U4.adoption\", True,",
        "catchers": _T_UR,
        "expected_catcher": ["test_task_without_an_adoption_predicate_cannot_pass"],
    },
    {
        "id": "M49b-signature-always-valid",
        "lesson": "#R2:签名校验形同虚设 → agent 自己造一张回执塞进台账即可过关",
        "file": _RC_M,
        "old": "        if not self.receipt_signature:\n            return False",
        "new": "        if not self.receipt_signature:\n            return True",
        "catchers": _T_UR,
        "expected_catcher": ["test_unsigned_receipt_fails"],
    },
    {
        "id": "M49c-chain-ignores-prev-hash",
        "lesson": "#R3:链校验不看 prev_sha256 → 事后改写/删行/换序全都查不出,第三方也就无从独立复核",
        "file": _RC_L,
        "old": '        if row.get("prev_sha256") != prev:',
        "new": "        if False:",
        "catchers": _T_UR,
        "expected_catcher": ["test_hash_chain_detects_tampering_without_any_key"],
    },
    {
        "id": "M49d-coverage-passes-without-a-unit-list",
        "lesson": "#R6:没有待办清单就默认通过 → 没有分母,'象征性调用一次'永远抓不住",
        "file": _RC_V,
        "old": "    if expected_units is None:\n        f.append(Finding(\"U3.coverage\", False,",
        "new": "    if expected_units is None:\n        f.append(Finding(\"U3.coverage\", True,",
        "catchers": _T_UR,
        "expected_catcher": ["test_missing_unit_list_cannot_pass"],
    },
    {
        "id": "M49e-run-nonce-not-checked",
        "lesson": "重放:不校验 run_nonce → 上一次 run 的回执签名有效、内容完好,直接拿来充数",
        "file": _RC_V,
        "old": "               and r.binding.run_nonce == run_nonce",
        "new": "               and True",
        "catchers": _T_UR,
        "expected_catcher": ["test_untrusted_receipts_do_not_count_toward_coverage"],
    },
    {
        "id": "M49f-upstream-identity-not-enforced",
        "lesson": "真包在场跑复制实现:不比 artifact_hash → 自带同名包、"
                  "照抄 __version__ 即可(T3 批 13 原样)",
        "file": _RC_V,
        "old": "            if want and got != want:",
        "new": "            if False:",
        "catchers": _T_UR,
        "expected_catcher": ["test_same_name_package_with_different_bytes_is_caught"],
    },
    {
        "id": "M49g-adoption-uses-containment-not-equality",
        "lesson": "#43 坑三:采纳判据从'相等'退化成'包含' → 把上游结果里的"
                  "一个标记抄进产物即可满足,实质内容仍是自写的",
        "file": _RC_V,
        "old": "        missing = [u for u in units if u not in want]",
        "new": "        missing = [] if want else list(units)",
        "catchers": _T_UR,
        "expected_catcher": ["test_calling_real_upstream_but_returning_own_result_is_caught"],
    },
    {
        "id": "M47a-mechanism-runs-count-toward-gate",
        "lesson": "#K3:机制消融混进闸门 → 批 14 把 T2 passes 从 5 抬到 14,读起来像能力提升 180%",
        "file": _BR,
        "old": '    mechanism = [r for r in prereg if r["run_purpose"] in MECHANISM_PURPOSES]',
        "new": "    mechanism = []",
        "catchers": _T_RCL,
        "expected_catcher": ["test_mechanism_ablation_does_not_count_toward_the_stage_gate"],
    },
    {
        "id": "M47b-classification-rewrites-verdict",
        "lesson": "#K1:分类改写原始 verdict → 篡改证据(那些发次确实跑完了、确实是那个结果)",
        "file": _BR,
        "old": '            "run_purpose": c.get("run_purpose", "CAPABILITY_EVALUATION"),',
        "new": '            "run_purpose": c.get("run_purpose", "CAPABILITY_EVALUATION"),\n'
               '            "verdict": "PASS_ADAPTED",',
        "catchers": _T_RCL,
        "expected_catcher": ["test_original_verdicts_are_never_rewritten"],
    },
    {
        "id": "M47c-undelivered-treatment-counted",
        "lesson": "#K4:处理零生效仍计处理效应 → 把'没做实验'当成'处理无害的证据'",
        "file": _BR,
        "old": ('        "treatment_not_delivered_runs": sum(\n'
                '            1 for r in rows if r["treatment_assigned"] and r["treatment_activated"] is False),'),
        "new": '        "treatment_not_delivered_runs": 0,',
        "catchers": _T_RCL,
        "expected_catcher": ["test_undelivered_treatment_is_excluded_from_treatment_effect"],
    },
    {
        "id": "M47d-post-hoc-classification-hidden",
        "lesson": "#K5:事后分类不自曝 → 把看到结果后的更正伪装成事前预注册",
        "file": _BR,
        "old": ('        "post_hoc_classified_runs": sum(\n'
                '            1 for r in rows\n'
                '            if r["classification_timing"] == "POST_HOC_TAXONOMY_CORRECTION"),'),
        "new": '        "post_hoc_classified_runs": 0,',
        "catchers": _T_RCL,
        "expected_catcher": ["test_post_hoc_classification_must_declare_itself"],
    },
    {
        "id": "M43e-never-ran-counts-as-red",
        "lesson": "#43 V3 近亲:该红的那条根本没被收集到时直接跳过 → 没跑当成红了",
        "file": _VC,
        "old": "        if name not in outcomes:\n            problems.append(f\"{name}:预期必红,但它根本没跑\")",
        "new": "        if name not in outcomes:\n            continue",
        "catchers": _T_VM,
        "expected_catcher": ["test_must_fail_case_that_never_ran_is_not_a_pass"],
    },
    # ---- HB-PCDELTA-1 出题工程(M68 delta oracle / M69 批判据 / M70 接线 / M71 生成器)
    {
        "id": "M68a-missing-delta-node-counts-as-green",
        "lesson": "junitxml 两头不见的 delta 节点被当绿 —— 量具第 4 次被 fail-closed"
                  "救的那类病(收集中断 → 曾被误判 parent 上就绿)在判卷器里的翻版",
        "file": _DOL,
        "old": ('            else:\n'
                '                out["node_detail"][node] = ("NODE_MISSING(junitxml 里两头不见 —— "\n'
                '                                            "fail-closed 判红,常见于收集中断)")'),
        "new": ('            else:\n'
                '                out["node_detail"][node] = "PASSED"'),
        "catchers": _T_DOL,
        "expected_catcher": ["test_u6_node_missing_is_red_not_silent"],
    },
    {
        "id": "M68b-regression-broken-bucket-silently-empty",
        "lesson": "回归破坏账本恒空 → REGRESSION_BROKEN 一类永不成立,破坏性提交"
                  "全部漂进 DESIGN_MISMATCH",
        "file": _DOL,
        "old": '        out["regression_broken"] = sorted(parsed["failed"] - delta)',
        "new": '        out["regression_broken"] = []',
        "catchers": _T_DOL,
        "expected_catcher": ["test_u4_regression_breakage_lands_in_its_own_bucket"],
    },
    {
        "id": "M68c-materialization-digest-not-checked",
        "lesson": "物化件内容漂移不拒判 → 判卷用的不是封存的上游测试(答案不入"
                  "git 的代价就是缺料/错料必须 fail-closed)",
        "file": _DOL,
        "old": '        elif _sha256(f) != item["sha256"]:',
        "new": "        elif False:",
        "catchers": _T_DOL,
        "expected_catcher": ["test_u3b_digest_mismatch_refuses_to_judge"],
    },
    {
        "id": "M68d-tests-tree-guard-disabled",
        "lesson": "tests/ 子树守卫失效 → 改判官的提交照常判卷",
        "file": _DOL,
        "old": '    if now != manifest["tests_tree_sha256"]:',
        "new": "    if False:",
        "catchers": _T_DOL,
        "expected_catcher": ["test_u5_touched_tests_tree_is_visible"],
    },
    {
        "id": "M68e-guarded-root-files-not-compared",
        "lesson": "根级 pytest 扩展点守卫失效 → 一个根 conftest 猴补丁可让全套件"
                  "假绿(delta 内容藏得住,pytest 的扩展点藏不住)",
        "file": _DOL,
        "old": '        if got.get(name, ABSENT) != expect:',
        "new": "        if False:",
        "catchers": _T_DOL,
        "expected_catcher": ["test_u7_planted_root_conftest_is_visible"],
    },
    {
        "id": "M68f-lay-target-occupied-gets-overwritten",
        "lesson": "delta 落点被占时直接覆盖 agent 文件 → 判完还原成 agent 没写过"
                  "的样子,篡改证据于无形",
        "file": _DOL,
        "old": "            if dst.exists():",
        "new": "            if False:",
        "catchers": _T_DOL,
        "expected_catcher": ["test_u8_lay_target_occupied_refuses"],
    },
    {
        "id": "M69a-regression-broken-without-any-delta-green",
        "lesson": "J3 的 REGRESSION_BROKEN 要求 delta 有转绿;拆掉后零尝试的破坏"
                  "性提交也挂上这个体面得多的类",
        "file": _HBC,
        "old": "    if delta_green > 0 and regression_broken:",
        "new": "    if regression_broken:",
        "catchers": _T_HBC,
        "expected_catcher": ["test_v6_regression_broken_needs_some_delta_green"],
    },
    {
        "id": "M69b-instrument-tampering-blamed-on-harness",
        "lesson": "h1/h3 红不再归 INSTRUMENT_TAMPERED → 改量具的发次沿优先级"
                  "漂进别的类,攻击被记到别人头上",
        "file": _HBC,
        "old": '    if any("test_h1_" in f or "test_h3_" in f for f in facts["cap_failing"]):',
        "new": "    if False:",
        "catchers": _T_HBC,
        "expected_catcher": ["test_v4_h1_or_h3_red_is_instrument_tampered"],
    },
    {
        "id": "M69c-selftest-material-absence-is-silent",
        "lesson": "自证素材缺席不再点名 → '没量'与'量了没问题'又长成一个样"
                  "(admission 判据的同一课,搬到检查器自己身上)",
        "file": _HBC,
        "old": "    for m in expect:\n        if m not in seen:",
        "new": "    for m in ():\n        if m not in seen:",
        "catchers": _T_HBC,
        "expected_catcher": ["test_v11_selftest_rejects_missing_material"],
    },
    {
        "id": "M69d-pass-with-red-cap-not-contradicted",
        "lesson": "PASS 却带 cap 红名单不再自曝矛盾 → 判定层缺陷静默过账",
        "file": _HBC,
        "old": '        if delta_green != delta_total or facts["cap_failing"]:',
        "new": "        if False:",
        "catchers": _T_HBC,
        "expected_catcher": ["test_v1b_pass_with_red_cap_is_a_harness_contradiction"],
    },
    {
        "id": "M70a-unknown-prompt-profile-accepted",
        "lesson": "prompt_profile 打错字静默落回缺省档,而缺省档对 delta 宿主"
                  "句句是假话",
        "file": _HD,
        "old": "        known = {\"offerclaw-v1\", \"hb-delta-v1\"}\n        if v not in known:",
        "new": "        known = {\"offerclaw-v1\", \"hb-delta-v1\"}\n        if False:",
        "catchers": _T_HTG,
        "expected_catcher": ["test_g2d_unknown_prompt_profile_refused"],
    },
    {
        "id": "M70b-pii-scan-silently-skipped-for-everyone",
        "lesson": "PII 出口扫描的范畴开关失守 → 用户宿主也不扫了,公开树的豁免"
                  "变成全体豁免",
        "file": _HD,
        "old": '    return contract.host.pii_scan_profile != "public-oss-tree"',
        "new": "    return False",
        "catchers": _T_HTG,
        "expected_catcher": ["test_g5d_scan_required_is_the_default_and_only_full_name_skips"],
    },
    {
        "id": "M70c-patch-mode-falls-through-to-mount",
        "lesson": "apply.patch 在场却走挂载形状 → delta 任务的 F0 电池整个哑火"
                  "(SystemExit 于 mount 发现,正控冒烟做不成)",
        "file": _HD,
        "old": "    patch_file = src_control / \"apply.patch\"\n    if patch_file.is_file():",
        "new": "    patch_file = src_control / \"apply.patch\"\n    if False:",
        "catchers": _T_HTG,
        "expected_catcher": ["test_g3a_patch_mode_applies_patch_and_skips_mount"],
    },
    {
        "id": "M70e-source-commit-fallback-writes-unknown",
        "lesson": "无 source_repo 时台账 source_commit 落 UNKNOWN —— 明明有真实"
                  "已核验的宿主 commit,装不知道是假话",
        "file": _HD,
        "old": "    return contract.host.commit",
        "new": '    return "UNKNOWN"',
        "catchers": _T_HTG,
        "expected_catcher": ["test_g1b_source_commit_falls_back_to_host_commit"],
    },
    {
        "id": "M71a-generator-accepts-round1-polluted-evidence",
        "lesson": "生成器不再拒第一轮证据 → regression_baseline 来自攻击者树上"
                  "的测量(交付树权威来源更正的执法面)",
        "file": _BTP,
        "old": '        if "attacker_residue" not in rec:',
        "new": "        if False:",
        "catchers": _T_HTP,
        "expected_catcher": ["test_p7_generator_refuses_round1_polluted_evidence"],
    },
    {
        "id": "M71b-answer-patch-filter-keeps-test-segments",
        "lesson": "正控 patch 不再剥 tests/** 段 → 隐藏判据全文进正控物化件,"
                  "且施加必失败(交付树上那些文件已剥)",
        "file": _BTP,
        "old": '        if not target.startswith("tests/"):',
        "new": "        if True:",
        "catchers": _T_HTP,
        "expected_catcher": ["test_p8_answer_patch_filter_drops_all_test_segments"],
    },
    # ---- M72:2026-08-16 可搬运性审查两条 blocking 的执法(零实现伪绿)----
    {
        "id": "M72a-guard-drops-interpreter-startup-surface",
        "lesson": "守卫面退回只守 pytest 配置 → 根级 sitecustomize.py 不再被看见,"
                  "解释器起点就能改写判卷读数(审查 blocking [1a] 原型)",
        "file": _DOL,
        "old": '    "pytest.ini", "tox.ini", "sitecustomize.py", "usercustomize.py",',
        "new": '    "pytest.ini", "tox.ini",',
        "catchers": _T_DOL + _T_HTP,
        "expected_catcher": ["test_u9_planted_sitecustomize_is_visible",
                             "test_p4b_manifest_pins_guard_and_collection_subtree"],
    },
    {
        "id": "M72b-judging-subprocess-inherits-pythonpath",
        "lesson": "判卷子进程不再剥 PYTHONPATH → 外层注的宿主根在 site 处理期上 "
                  "sys.path,sitecustomize 自动生效(blocking [1a] 的注入通道)",
        "file": _DOL,
        "old": '            for k in ("PYTHONPATH", "PYTHONSTARTUP"):\n                env.pop(k, None)',
        "new": "            pass",
        "catchers": _T_DOL,
        "expected_catcher": ["test_u9b_judging_subprocess_drops_inherited_pythonpath"],
    },
    {
        "id": "M72c-judging-collects-whole-tree",
        "lesson": "判卷退回裸 pytest 收整棵树 → 任意新建目录的 conftest.py 都被加载,"
                  "pytest_configure 注册的全局插件可伪造全绿(blocking [1b])",
        "file": _DOL,
        "old": '                    [sys.executable, "-m", "pytest", tests_subdir, "-q",',
        "new": '                    [sys.executable, "-m", "pytest", "-q",',
        "catchers": _T_DOL,
        "expected_catcher": [
            "test_u10_subdir_conftest_global_plugin_is_out_of_collection",
            "test_u11_guard_subtree_equals_collection_subtree"],
    },
    {
        "id": "M72d-guard-subtree-decoupled-from-collection",
        "lesson": "守卫子树写死 tests/ 而收集子树读 manifest → 守 A 收 B,"
                  "[1b] 的一般形(换个上游布局就重新裂开)",
        "file": _DOL,
        "old": '    now = tests_tree_digest(host, manifest.get("tests_subdir", "tests"))',
        "new": "    now = tests_tree_digest(host)",
        "catchers": _T_DOL,
        "expected_catcher": ["test_u11_guard_subtree_equals_collection_subtree"],
    },
    {
        "id": "M72e-lay-target-occupied-misfiled-as-harness",
        "lesson": "落点被占改挂 h0 桶 → agent 在剥离路径上写同名文件反被记成"
                  "HARNESS_FAILURE(归因倒挂,篡改洗成我方故障)",
        "file": _DOL,
        "old": '                out["instrument_problems"].append(\n                    f"LAY_TARGET_OCCUPIED:{item[\'path\']}")',
        "new": '                out["problems"].append(f"LAY_TARGET_OCCUPIED:{item[\'path\']}")',
        "catchers": _T_DOL,
        "expected_catcher": ["test_u8_lay_target_occupied_refuses"],
    },
    {
        "id": "M72f-oracle-env-sanitation-flag-ignored",
        "lesson": "外层 _run_oracle 忽略契约声明,照旧注 PYTHONPATH=<宿主根> → "
                  "H1 守卫自己就在被污染的解释器里跑,守卫等于没守",
        "file": _HD,
        "old": '            return {"PYTHONNOUSERSITE": "1"}\n        return {"PYTHONPATH": str(s.root / "host")}',
        "new": '            pass\n        return {"PYTHONPATH": str(s.root / "host")}',
        "catchers": _T_HTG,
        "expected_catcher": ["test_g8c_oracle_import_env_branches_on_the_flag"],
    },
    {
        "id": "M72g-suite-timeout-folded-into-harness-failure",
        "lesson": "超时不再单列 → agent 蓄意拖慢套件即可刷 HARNESS 连败撞停批线 1,"
                  "把整批停掉(判据可被受测方操纵)",
        "file": _HBC,
        "old": '        if facts.get("suite_timeout"):',
        "new": "        if False:",
        "catchers": _T_HBC,
        "expected_catcher": ["test_v13_suite_timeout_is_split_out_of_harness_failure"],
    },
    {
        "id": "M72h-selftest-drops-synthetic-branch-biopsy",
        "lesson": "自证不再活检合成分支 → 活体负控覆盖不到的 J3 支(含新建的"
                  "INSTRUMENT_TAMPERED)判错也无人知",
        "file": _HBC,
        "old": "    for want_j3, facts in SYNTHETIC_BRANCHES:",
        "new": "    for want_j3, facts in []:",
        "catchers": _T_HBC,
        "expected_catcher": ["test_v12b_selftest_actually_runs_the_biopsy"],
    },
    {
        "id": "M72i-tamper-control-payload-hollowed",
        "lesson": "篡改负控载荷被掏空成注释 → 负控还在、牙没了,"
                  "'守卫拦住了伪造'退化成'拦住了一个空文件'",
        "file": _BTP,
        "old": '    "    _rp.Function.runtest = lambda self: None   # 每个用例都不执行 = 全绿",',
        "new": '    "    pass",',
        "catchers": _T_HTP,
        "expected_catcher": ["test_p5b_tamper_control_on_disk_equals_generator_constant"],
    },
    {
        "id": "M72j-run-oracle-rewrites-the-env-literal-inline",
        "lesson": "_run_oracle 不再调那个分支函数,自己写回一份 PYTHONPATH 字面量 → "
                  "契约声明形同虚设,且旁路掉函数上的全部行为钉死",
        "file": _HD,
        "old": "            env={**self._oracle_import_env(s),",
        "new": '            env={"PYTHONPATH": str(s.root / "host"),',
        "catchers": _T_HTG,
        "expected_catcher": ["test_g8d_run_oracle_uses_the_branching_env_not_a_literal"],
    },
]


# ---------------------------------------------------------------- 执行机构

def _git(*args: str, cwd: Path = REPO) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def _run_subset(tree: Path, catchers: list[str]) -> tuple[int, str, set[str], bool]:
    """跑 catcher 子集并解析 junitxml。返回 (退出码, 输出尾巴, 失败节点名集合,
    是否有收集期崩溃)。

    不用 `-x`:归因需要**完整**的红名单 —— 只看第一个红,恰好会漏掉
    "被考的判断排在别人后面"这种最需要看见的情况(M64c 的形状)。
    失败节点取 junitxml 的 `name`(函数名,参数化带 `[...]`);收集期崩溃
    的形状是 classname 为空 + error 子节点(本仓 pytest 实测,2026-08-16)。
    """
    xml_path = tree / "rp_mutation_junit.xml"
    xml_path.unlink(missing_ok=True)
    env = dict(os.environ, PYTHONPATH=str(tree / "src"))
    proc = subprocess.run(
        [str(PYTEST), *catchers, "-q", "-p", "no:cacheprovider",
         "--junitxml", str(xml_path)],
        cwd=tree, env=env, capture_output=True, text=True)
    failed: set[str] = set()
    collapsed = False
    if xml_path.exists():
        try:
            for case in ET.parse(xml_path).getroot().iter("testcase"):
                bad, err = case.find("failure"), case.find("error")
                if bad is None and err is None:
                    continue
                failed.add(case.get("name", "?"))
                if err is not None and not (case.get("classname") or ""):
                    collapsed = True
        except ET.ParseError:
            pass          # 解析不出 → failed 为空,退出码红时由 GATE_PLUMBING 兜底
        xml_path.unlink(missing_ok=True)
    return proc.returncode, (proc.stdout + proc.stderr)[-800:], failed, collapsed


# ------------------------------------------------- 归因判定(判据见钉死 E1–E8)

def _matches_declared(name: str, declared: list[str]) -> bool:
    """节点名是否命中声明。参数化按基名(`test_x[3]` 算 `test_x`),但不做
    前缀猜测(`test_x_more` 不算 `test_x` —— 把邻居的功劳记到声明头上,
    是另一种归因错位)。"""
    return any(name == d or name.startswith(d + "[") for d in declared)


def classify_catch(*, exit_code: int, failed: set[str], collapsed: bool,
                   declared: list[str] | None) -> tuple[str, dict]:
    """一次注入后的结局判定。CAUGHT 不能只看"红没红",要看**红的是不是
    声明要考的那条判断** —— 否则合成缺陷被别的判断先杀,被考的判断掏掉
    也看不出差别(M59c/M62d,e/M64c,一天三次)。"""
    if not failed:
        if exit_code == 0:
            return "ESCAPED", {}
        # 退出码红、却一个失败节点都解析不出:测量仪自身的管道坏了。
        # 冒充 CAUGHT 等于把仪器故障记成测到了东西。
        return "GATE_PLUMBING", {"pytest_exit": exit_code}
    if declared:
        hits = sorted(n for n in failed if _matches_declared(n, declared))
        if hits:
            return "CAUGHT", {"attribution": "DECLARED", "attributed_to": hits}
        if collapsed:
            # 整文件收集期崩溃:声明的判断不是被抢了先,是全场阵亡 ——
            # 与 MISATTRIBUTED 是两种病,单列可见。
            return "CAUGHT", {"attribution": "COLLAPSE"}
        return "MISATTRIBUTED", {
            "failed_nodes": sorted(failed), "expected_catcher": list(declared)}
    if collapsed:
        return "CAUGHT", {"attribution": "COLLAPSE"}
    # 存量未声明:照旧算捕获,但必须可见地标出来 —— "还没声明"与
    # "声明并验证过"不许长一个样(诚实清单由 build_report 汇出)。
    return "CAUGHT", {"attribution": "UNDECLARED"}


def attribution_canary_verdict(outcome: str) -> str | None:
    """C1 的结局必须恰为 MISATTRIBUTED;其余任何结局 → 返回自宣无效的理由。
    摆好的归因错位都抓不出来,就没资格给整本登记簿发归因结论。"""
    if outcome == "MISATTRIBUTED":
        return None
    return (f"归因金丝雀结局是 {outcome},不是 MISATTRIBUTED —— "
            "归因执法在装样子,本闸门的一切归因结论无效")


def build_report(head: str, results: list[dict], *, wall_seconds: float,
                 mutations_total: int) -> dict:
    """汇总只从逐条结果推导 —— 手写汇总正是"散文说不算、代码算了"的入口。"""
    caught = sum(1 for r in results if r["outcome"] == "CAUGHT")
    # 显式声明**这份证据守护哪些文件** —— 这些文件一变,证据就该作废。
    # 含登记簿自身:改了登记簿(加条目、改 old/new、改 catcher/声明),旧证据
    # 当然不再代表现在这套变异。派生自 MUTATIONS 而非从 results 反推,是为了
    # 让 STALE/ESCAPED 的条目也算数(它们守护的文件同样相干)。
    guard_set = sorted(
        {m["file"] for m in MUTATIONS if m.get("file")}
        | {c for m in MUTATIONS for c in (m.get("catchers") or [])}
        | {"scripts/mutation_gate.py"})
    return {
        "head_commit": head,
        "mutations": mutations_total,
        "guard_set": guard_set,
        "caught": caught,
        "attributed": sum(1 for r in results
                          if r["outcome"] == "CAUGHT"
                          and r.get("attribution") == "DECLARED"),
        "unattributed": [r["id"] for r in results
                         if r["outcome"] == "CAUGHT"
                         and r.get("attribution") == "UNDECLARED"],
        "collapsed": [r["id"] for r in results
                      if r["outcome"] == "CAUGHT"
                      and r.get("attribution") == "COLLAPSE"],
        "misattributed": [r["id"] for r in results if r["outcome"] == "MISATTRIBUTED"],
        "escaped": [r["id"] for r in results if r["outcome"] == "ESCAPED"],
        "stale": [r["id"] for r in results if r["outcome"] == "STALE"],
        "capture_rate": f"{caught}/{mutations_total}",
        "wall_seconds": round(wall_seconds, 1),
        "results": results,
    }


def _apply(tree: Path, m: dict) -> str | None:
    """注入变异;返回 None=成功,否则 STALE 原因。"""
    f = tree / m["file"]
    if not f.exists():
        return f"目标文件不存在:{m['file']}"
    text = f.read_text(encoding="utf-8")
    n = text.count(m["old"])
    if n != 1:
        return f"旧串出现 {n} 次(要求恰 1)—— 源码已重构,登记簿过期"
    f.write_text(text.replace(m["old"], m["new"]), encoding="utf-8")
    return None


def _restore(tree: Path, m: dict) -> None:
    _git("checkout", "--", m["file"], cwd=tree)


def run_gate() -> int:
    head = _git("rev-parse", "HEAD")
    results: list[dict] = []
    t_start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="rp_mutation_") as td:
        tree = Path(td) / "tree"
        _git("worktree", "add", "--detach", str(tree), "HEAD")
        try:
            # 基线:未变异的 worktree 上所有 catcher 必须全绿,否则无从归因
            all_catchers = sorted({c for m in [CANARY, *MUTATIONS] for c in m["catchers"]})
            code, tail, _, _ = _run_subset(tree, all_catchers)
            if code != 0:
                print(f"[ABORT] 基线不绿(exit={code}),无从归因变异:\n{tail}")
                return 2
            # C0 金丝雀:证明测的是变异体不是主树
            err = _apply(tree, CANARY)
            if err:
                print(f"[ABORT] 金丝雀 STALE:{err}")
                return 2
            code, tail, _, _ = _run_subset(tree, CANARY["catchers"])
            _restore(tree, CANARY)
            if code == 0:
                print("[ABORT] 金丝雀未被抓住 —— worktree 隔离失效,"
                      "本闸门在测主树而非变异体,一切结论无效。")
                return 2
            print(f"金丝雀 CAUGHT(exit={code})—— 隔离通路自证有效。")

            # C1 归因金丝雀:声明 A 抓、实际 B 抓,必须判出 MISATTRIBUTED。
            err = _apply(tree, ATTRIBUTION_CANARY)
            if err:
                print(f"[ABORT] 归因金丝雀 STALE:{err}")
                return 2
            code, tail, failed, collapsed = _run_subset(tree, ATTRIBUTION_CANARY["catchers"])
            _restore(tree, ATTRIBUTION_CANARY)
            outcome, _extra = classify_catch(
                exit_code=code, failed=failed, collapsed=collapsed,
                declared=ATTRIBUTION_CANARY["expected_catcher"])
            reason = attribution_canary_verdict(outcome)
            if reason:
                print(f"[ABORT] {reason}")
                return 2
            print("归因金丝雀 MISATTRIBUTED —— 归因执法自证有效。\n")

            for m in MUTATIONS:
                t0 = time.monotonic()
                err = _apply(tree, m)
                if err:
                    results.append({"id": m["id"], "lesson": m["lesson"],
                                    "outcome": "STALE", "detail": err})
                    print(f"  STALE   {m['id']} —— {err}")
                    continue
                code, tail, failed, collapsed = _run_subset(tree, m["catchers"])
                _restore(tree, m)
                declared = m.get("expected_catcher")
                outcome, extra = classify_catch(
                    exit_code=code, failed=failed, collapsed=collapsed,
                    declared=declared)
                if outcome == "GATE_PLUMBING":
                    print(f"[ABORT] {m['id']}:pytest 退出码 {code} 却解析不出任何"
                          "失败节点 —— junitxml 管道坏了,归因不可判,整个闸门"
                          "自宣无效。")
                    return 2
                results.append({
                    "id": m["id"], "lesson": m["lesson"], "file": m["file"],
                    "outcome": outcome, "pytest_exit": code,
                    "catchers": m["catchers"],
                    **({"expected_catcher": declared} if declared else {}),
                    **extra,
                    "failed_nodes": sorted(failed),
                    "seconds": round(time.monotonic() - t0, 1),
                    **({"tail": tail} if outcome in ("ESCAPED", "MISATTRIBUTED") else {}),
                })
                mark = extra.get("attribution", "")
                print(f"  {outcome:13s} {m['id']}"
                      + (f"  [{mark}]" if mark else "")
                      + f"  ({results[-1]['seconds']}s)")
        finally:
            _git("worktree", "remove", "--force", str(tree))
            _git("worktree", "prune")

    report = build_report(head, results,
                          wall_seconds=time.monotonic() - t_start,
                          mutations_total=len(MUTATIONS))
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    dest = EVIDENCE_DIR / f"{head[:12]}.json"
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"\n捕获率 {report['capture_rate']}(声明归因 {report['attributed']}、"
          f"未声明 {len(report['unattributed'])}、整文件崩溃 {len(report['collapsed'])});"
          f"证据已落盘:{dest}")
    if report["unattributed"]:
        head_ids = ", ".join(report["unattributed"][:8])
        more = " …" if len(report["unattributed"]) > 8 else ""
        print(f"未归因存量(诚实清单,待补声明):{head_ids}{more}")
    if report["escaped"] or report["stale"] or report["misattributed"]:
        print("未达标 —— ESCAPED 当场补钉死;STALE 更新登记簿;MISATTRIBUTED 修"
              "声明或重设计合成缺陷(它被错误的判断抢先抓住了)。绝不带病放行。")
        return 1
    return 0


if __name__ == "__main__":
    if "--list" in sys.argv:
        for m in MUTATIONS:
            print(f"{m['id']:36s} {m['lesson']}")
        sys.exit(0)
    sys.exit(run_gate())
