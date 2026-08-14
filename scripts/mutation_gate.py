"""变异闸门:把**已付过学费的缺陷**逐个注回源码,钉死套件必须 100% 抓住。

这是"评测者的评测者"(PROCESS-INDEPENDENCE-PLAN §5-P1-5)。回答的问题:
我的钉死到底护住了什么?——不是"测试全绿"(照着实现写的测试永远全绿),
而是"把 LESSONS 里每一条历史缺陷(及其近似变体)重新犯一遍,套件会不会红"。
变体的意义:抓得住原案却抓不住变体 = 钉死过拟合到了事发实例,护不住缺陷类。

三种结局:
    CAUGHT   注入后指定测试子集变红(期望值)
    ESCAPED  注入后子集仍绿 —— 套件没在护这条教训,当场补钉死
    STALE    旧串在源里找不到/不唯一 —— 源码重构后登记簿未更新,必须维护

自证机制(先于一切变异运行):金丝雀变异(掏空 PASS_VERDICTS)若未被抓住,
说明 worktree 隔离失效(测的是主树不是变异体),整个闸门自宣无效退出——
检查器必须先证明自己在检查,才有资格给别人发绿。

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

CANARY = {
    "id": "C0-plumbing-canary",
    "lesson": "自证:worktree 隔离必须真的生效",
    "file": _BR,
    "old": 'PASS_VERDICTS = frozenset({"PASS", "PASS_ADAPTED"})',
    "new": "PASS_VERDICTS = frozenset()",
    "catchers": _T_BR,
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
    },
    {
        "id": "M30b-smoke-prefix-case-variant",
        "lesson": "#30 变体:前缀大小写错配,fake-scripted 漏网",
        "file": _BR,
        "old": 'SMOKE_MODEL_PREFIX = "fake"',
        "new": 'SMOKE_MODEL_PREFIX = "FAKE"',
        "catchers": _T_BR,
    },
    # ---- LESSONS #27:探索性加发未与预注册批次隔离 ----
    {
        "id": "M27-exploratory-counts",
        "lesson": "#27 探索性加发充闸门(真话写在机器读不到的地方)",
        "file": _BR,
        "old": '    prereg = [r for r in real if r.get("batch") != EXPLORATORY_BATCH]',
        "new": "    prereg = list(real)",
        "catchers": _T_BR,
    },
    # ---- LESSONS #26:裁定不进统计,台账自失真 ----
    {
        "id": "M26-verdict-not-effective",
        "lesson": "#26 闸门数原始 verdict 而非 effective_verdict(order-38 假 PASS 复活)",
        "file": _BR,
        "old": '    passes = [r for r in gateable if r["effective_verdict"] in PASS_VERDICTS]',
        "new": '    passes = [r for r in gateable if r.get("verdict") in PASS_VERDICTS]',
        "catchers": _T_BR,
    },
    {
        "id": "M26b-substring-pass-variant",
        "lesson": '#26 变体:"PASS" in verdict 子串判定(FALSE_PASS 含 PASS)',
        "file": _BR,
        "old": '    passes = [r for r in gateable if r["effective_verdict"] in PASS_VERDICTS]',
        "new": '    passes = [r for r in gateable if "PASS" in str(r["effective_verdict"])]',
        "catchers": _T_BR,
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
    },
    {
        "id": "M29b-upstream-whitelisted",
        "lesson": "#29 变体:给无害兄弟目录 upstream 开口子(该迁走的是整套栈)",
        "file": _HG,
        "old": '    "offerclaw-t3-browser-use",      # T3 宿主副本\n})',
        "new": '    "offerclaw-t3-browser-use",      # T3 宿主副本\n    "upstream",\n})',
        "catchers": _T_HG,
    },
    {
        "id": "M29c-answer-key-registered",
        "lesson": "#29 变体:把答案卷目录本身登记进白名单",
        "file": _HG,
        "old": '    "offerclaw-t3-browser-use",      # T3 宿主副本\n})',
        "new": ('    "offerclaw-t3-browser-use",      # T3 宿主副本\n'
                '    "offerclaw-transaction-stack",\n})'),
        "catchers": _T_HG,
    },
    # ---- 主目录硬护栏(红线,无单独 lesson 号) ----
    {
        "id": "MGuard-case-sensitive",
        "lesson": "护栏红线变体:路径比较丢大小写归一(APFS 大小写不敏感可绕)",
        "file": _HG,
        "old": '    return os.path.realpath(os.path.expanduser(str(p))).lower().rstrip("/")',
        "new": '    return os.path.realpath(os.path.expanduser(str(p))).rstrip("/")',
        "catchers": _T_HG,
    },
    # ---- LESSONS #31:harness 替模型认领错 ----
    {
        "id": "M31a-attribution-neutered",
        "lesson": "#31 归因分支被掏空(一切依赖失败重新都算 harness)",
        "file": _HD,
        "old": "            added = added_problem_dists(full, self._baseline_dists())",
        "new": "            added = []",
        "catchers": _T_HD,
    },
    {
        "id": "M31b-attribution-flipped",
        "lesson": "#31 变体:归因标签写反(agent 缺陷标成 harness)",
        "file": _HD,
        "old": '                               "attribution": "agent",',
        "new": '                               "attribution": "harness",',
        "catchers": _T_HD,
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
    },
    {
        "id": "M31d-pep503-dropped",
        "lesson": "#31 变体:丢 PEP 503 归一(Browser_Use ≠ browser-use,基线比对失效)",
        "file": _HD,
        "old": '    return re.sub(r"[-_.]+", "-", name).lower()',
        "new": "    return name.lower()",
        "catchers": _T_HD,
    },
    # ---- LESSONS #33:轮内约束不反馈,终局才伏击 ----
    {
        "id": "M33a-denied-cumulative-restored",
        "lesson": "#33 denied 退回会话累计(一轮违规永久拖累后续所有轮)",
        "file": _HD,
        "old": "                denied_round = env.denied_count - denied_before",
        "new": "                denied_round = env.denied_count",
        "catchers": _T_CF,
    },
    {
        "id": "M33b-green-stop-ignores-fatal",
        "lesson": "#33 全绿即停无视 fatal 违规(剩余轮次全弃,盖棺被击杀)",
        "file": _RL,
        "old": "                    and not result.fatal_violations):",
        "new": "                    ):",
        "catchers": _T_CF,
    },
    {
        "id": "M33c-rollback-detail-mismatch",
        "lesson": "#33 回滚后失败包配错细节(best 的节点 × 劣化轮的 details)",
        "file": _RL,
        "old": "            packets = build_failure_packets(src_cp.failed_nodes, src_cp.failure_details)",
        "new": "            packets = build_failure_packets(src_cp.failed_nodes, result.failure_details)",
        "catchers": _T_CF,
    },
    {
        "id": "M33d-violation-packets-dropped",
        "lesson": "#33 变体:违规判据引擎在,但包不进下一轮提示(agent 仍瞎)",
        "file": _HD,
        "old": ("                    failure_packets=[p.to_dict()\n"
                "                                     for p in (*packets_next, *violation_packets)],"),
        "new": "                    failure_packets=[p.to_dict() for p in packets_next],",
        "catchers": _T_CF,
    },
    {
        "id": "M33e-patch-overage-poisons-ranking",
        "lesson": "#33 变体:patch 超限计进 policy_violations(超重全绿轮被回滚,逼重做)",
        "file": _HD,
        "old": "    return packets, fatal, len(tampered)",
        "new": "    return packets, fatal, len(tampered) + len(fatal)",
        "catchers": _T_CF,
    },
    # ---- LESSONS #34:红绿守卫两义性 ----
    {
        "id": "M34a-exit4-blanket-reject",
        "lesson": "#34 exit 4 一律否掉(ImportError 型最强的红被判假阴性)",
        "file": _RG,
        "old": "        if not genuine:",
        "new": "        if True:",
        "catchers": _T_PI,
    },
    {
        "id": "M34b-exit4-blanket-accept",
        "lesson": "#34 反向:exit 4 一律算红(守卫被拆,名字打错也能冒充红)",
        "file": _RG,
        "old": "    if red_exit == 4:",
        "new": "    if False:",
        "catchers": _T_PI,
    },
    # ---- LESSONS #35:排序只对齐终局判据 ----
    {
        "id": "M35a-denied-poisons-ranking-again",
        "lesson": "#35 denied 退回排序(21/23 的轮因一条零执行的调试命令被弃)",
        "file": _HD,
        "old": "    return packets, fatal, len(tampered)",
        "new": "    return packets, fatal, len(tampered) + denied_delta",
        "catchers": _T_CF,
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
    },
    # ---- LESSONS #36:反馈量足够、形状错误 ----
    {
        "id": "M36a-collapse-disabled",
        "lesson": "#36 同根因不再折叠(15 项同话包重回,信息 1 句噪声 60 行)",
        "file": _FP,
        "old": "COLLAPSE_MIN = 3   # 同签名达此数量才合并;2 条不值得抽象",
        "new": "COLLAPSE_MIN = 9999",
        "catchers": _T_RC,
    },
    {
        "id": "M36b-timeout-rule-dropped",
        "lesson": "#36 超时规则被摘(超时按测试名误判成 SCHEMA_ERROR)",
        "file": _FP,
        "old": '    (TIMEOUT, ("未在", "内终结", "timed out", "timeout", "timeouterror")),',
        "new": "",
        "catchers": _T_RC,
    },
    {
        "id": "M36c-victim-list-truncated",
        "lesson": "#36 折叠包截断受害者名单(静默丢信息,开发中真犯过)",
        "file": _FP,
        "old": '                         f"(判定类型 {cause}):" + "、".join(names)),',
        "new": '                         f"(判定类型 {cause}):" + "、".join(names[:6])),',
        "catchers": _T_RC,
    },
    {
        "id": "M36d-collapse-too-eager",
        "lesson": "#36 变体:阈值降到 1,单条失败也被抽象成'根因',旧形态回退",
        "file": _FP,
        "old": "    collapsed = {n for sig, ns in groups.items() if len(ns) >= COLLAPSE_MIN for n in ns}",
        "new": "    collapsed = {n for sig, ns in groups.items() if len(ns) >= 1 for n in ns}",
        "catchers": _T_RC,
    },
    # ---- LESSONS #37:修剪轮不能白干 ----
    {
        "id": "M37a-compliance-term-removed",
        "lesson": "#37 排序丢掉二元合规位(修剪轮与超重轮同分,先到先得选中超重的)",
        "file": _HD,
        "old": "        1.0 if not r.fatal_violations else 0.0,\n        1.0 if r.within_budget else 0.0,",
        "new": "        1.0 if r.within_budget else 0.0,",
        "catchers": _T_CF,
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
    },
    # ---- LESSONS #38:探针失败不得沉默;冲突也是一种死法 ----
    {
        "id": "M38a-probe-failure-swallowed",
        "lesson": "#38 探针非零退出但认不出名字就放行(order-59:全绿即停→重放击杀)",
        "file": _HD,
        "old": "    if unresolvable_dists or dependency_probe_failed:",
        "new": "    if unresolvable_dists:",
        "catchers": _T_CF,
    },
    {
        "id": "M38b-conflict-pattern-dropped",
        "lesson": "#38 只认「找不到分发」不认 ResolutionImpossible(harness 替模型认领)",
        "file": _HD,
        "old": "    return [d for d in conflicting_dists(pip_output) if d not in baseline]",
        "new": "    return []",
        "catchers": _T_CF,
    },
    # ---- LESSONS #39:执法读到陈旧总量 + 固定内移是猜的 ----
    {
        "id": "M39a-enforcement-back-to-async-hook",
        "lesson": "#39 执法只信异步钩子(order-63:读到落后一次调用的 703,172 就放行)",
        "file": _TB,
        "old": '        return max(self.sync_in, int(self.totals.get("in", 0) or 0))',
        "new": '        return int(self.totals.get("in", 0) or 0)',
        "catchers": _T_TE,
    },
    {
        "id": "M39b-pre-call-projection-disabled",
        "lesson": "#39 调用前不投影,只在越线后才拦(803,310 > 800,000 的直接成因)",
        "file": _TB,
        "old": "            if used_in + projected > self.max_input_tokens:",
        "new": "            if used_in + projected > self.max_input_tokens * 100:",
        "catchers": _T_TE,
    },
    {
        "id": "M39c-observed-max-floor-dropped",
        "lesson": "#39 投影只剩估算一条腿(估算失准时又变成拍脑袋)",
        "file": _TB,
        "old": "        return max(math.ceil(est * self.ratio * SAFETY_FACTOR), self.max_call_in)",
        "new": "        return math.ceil(est * self.ratio * SAFETY_FACTOR)",
        "catchers": _T_TE,
    },
    {
        "id": "M39d-round-bucket-back-to-hook",
        "lesson": "#39 轮桶回到异步钩子(上一轮末次调用被记进下一轮,拿别人的 token 杀这一轮)",
        "file": _HD,
        "old": '    if getattr(model, "seen", False):',
        "new": '    if not getattr(model, "seen", False):',
        "catchers": _T_TE,
    },
    {
        "id": "M39e-estimator-ignores-cjk",
        "lesson": "#39 估算照搬 chars/4(order-63 实测低估 33%,投影跟着塌)",
        "file": _TB,
        "old": "    cjk = len(_CJK.findall(text))",
        "new": "    cjk = 0",
        "catchers": _T_TE,
    },
    {
        "id": "M39f-enforcement-line-inset-again",
        "lesson": "#39 有人又把执法线往里挪(拍常数替代投影,单次调用比常数大就翻车)",
        "file": _HD,
        "old": "    return budgets.max_input_tokens_total",
        "new": "    return max(1, budgets.max_input_tokens_total - 50_000)",
        "catchers": _T_HD,
    },
    # ---- LESSONS #40:fixtures 是量具,不是实现面 ----
    {
        "id": "M40a-fixtures-out-of-public-surface",
        "lesson": "#40 公开面只认 public_tests(order-20/21:oracle 拿被测者写的假模型当量具)",
        "file": _HD,
        "old": 'PROTECTED_PUBLIC_DIRS = ("public_tests", "fixtures")',
        "new": 'PROTECTED_PUBLIC_DIRS = ("public_tests",)',
        "catchers": _T_PS,
    },
    {
        "id": "M40b-final-check-back-to-public-tests-only",
        "lesson": "#40 终局对账退回只哈希 public_tests(改 fixtures 盖棺时查不出)",
        "file": _HD,
        "old": "                public_before, hash_public_surface(s.root / \"host\"))",
        "new": "                public_before, hash_tree(s.root / \"host\" / \"public_tests\"))",
        "catchers": _T_PS,
    },
    {
        "id": "M40c-prompt-drops-the-fixtures-rule",
        "lesson": "#40 终局会杀却不在提示里教(#33 的老病:agent 改了 19 轮没人告诉过它)",
        "file": _HD,
        "old": '        + "\\n- Do not modify ./public_tests, ./fixtures or ../upstream. The fixtures\\n"',
        "new": '        + "\\n- Do not modify ./public_tests or ../upstream.\\n"',
        "catchers": _T_PS,
    },
    {
        "id": "M41a-answer-key-markers-gone",
        "lesson": "#41 政策不认答案树路径(order-21:cp 正控 research_jobs.py 进工作区)",
        "file": _PO,
        "old": '    "_scratch_t",                 # 正控/负控安装树(order-21 抄的就是它)',
        "new": '    "__never_matches_anything__",',
        "catchers": _T_WC,
    },
    {
        "id": "M41b-root-sweep-not-detected",
        "lesson": "#41 根扫描放行(发现答案的第一步:find / -name fake_llm_server.py)",
        "file": _PO,
        "old": "    if root_sweeping(lowered):",
        "new": "    if False:",
        "catchers": _T_WC,
    },
    {
        "id": "M41c-sweep-detector-ignores-separators",
        "lesson": "#41 变体:根检测不在分隔符处复位 → `find . -name x ; cp a /` 被误伤",
        "file": _PO,
        "old": "        if tok in _SEPARATORS:\n            active = False\n            continue",
        "new": "        if tok in _SEPARATORS:\n            continue",
        "catchers": _T_WC,
    },
    {
        "id": "M41d-root-sweep-promoted-to-a-kill",
        "lesson": "#41 变体:把根扫描也判死 —— 27 发越界里 24 发只是在找 wheelhouse(#35 反面)",
        "file": _PO,
        "old": "        reasons.append(ROOT_SWEEP)",
        "new": "        reasons.append(f\"{OUT_OF_WORKSPACE}:{ROOT_SWEEP}\")",
        "catchers": _T_WC,
    },
    {
        "id": "M41d2-heredoc-body-scanned-as-a-command",
        "lesson": "#41 变体:heredoc 正文当命令扫 → 写文件被误判成全盘扫描(误伤毁一轮)",
        "file": _PO,
        "old": "    for tok in strip_heredocs(command).split():",
        "new": "    for tok in command.split():",
        "catchers": _T_WC,
    },
    {
        "id": "M41e-denial-reasons-only-counted",
        "lesson": "#41 只记 denied_count 不记原因 → 越界与预算耗尽分不出来",
        "file": _EV,
        "old": "            self.policy_denials.extend(decision.reasons)",
        "new": "            pass",
        "catchers": _T_WC,
    },
    {
        "id": "M41f-residue-scan-skips-scratch-trees",
        "lesson": "#41 H9-a 不认 _scratch_t* 安装树(order-21 抄的那棵就在其中)",
        "file": _HD,
        "old": '                    if e.name.startswith("_scratch_t"):',
        "new": '                    if False:',
        "catchers": _T_WC,
    },
    {
        "id": "M41g-residue-scan-flags-the-live-session",
        "lesson": "#41 变体:H9-a 不跳过 _sessions → 每一发都拒开自己(过度封锁)",
        "file": _HD,
        "old": '                if e.name == _SESSION_DIR:\n                    continue',
        "new": '                if False:\n                    continue',
        "catchers": _T_WC,
    },
    {
        "id": "M41h-residue-is-a-warning-not-a-block",
        "lesson": "#41 H9-a 查到残留只告警不拒开(判据原文:拒开,不是告警)",
        "file": _HD,
        "old": "        residue = reachable_answer_keys(Path(contract_path).parent, blind=blind)\n        if residue:",
        "new": "        residue = reachable_answer_keys(Path(contract_path).parent, blind=blind)\n        if False:",
        "catchers": _T_WC,
    },
    {
        "id": "M41i-out-of-workspace-not-fatal",
        "lesson": "#41 越界不进 fatal/排序 → 终局要杀,循环既不防也不报(#33/#35 老病)",
        "file": _HD,
        "old": '        fatal.append("out_of_workspace")',
        "new": '        pass',
        "catchers": _T_WC,
    },
    {
        "id": "M41j-prompt-drops-the-workspace-boundary",
        "lesson": "#41 H9-c:终局以 OUT_OF_WORKSPACE_ACCESS 击杀却不在提示里教(27 发无一被告知)",
        "file": _HD,
        "old": '        + "\\n- STAY INSIDE THE WORKSPACE. Everything you need is here: ./ and the\\n"',
        "new": '        + "\\n- Prefer to work inside the workspace.\\n"',
        "catchers": _T_WC,
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
    },
    {
        "id": "M42f-trash-added-back-as-a-scan-root",
        "lesson": "#42 H9-a:废纸篓加回扫描根 → 它列不动,每一发都判 SCAN_BLIND(不可满足的闸门必被关掉)",
        "file": _HD,
        "old": 'ANSWER_KEY_SCAN_ROOTS = ("~/RepoProofBench", "~/RepoProofBench-quarantine", "/tmp")',
        "new": 'ANSWER_KEY_SCAN_ROOTS = ("~/RepoProofBench", "~/RepoProofBench-quarantine", "/tmp", "~/.Trash")',
        "catchers": _T_WC,
    },
    {
        "id": "M42a-control-tree-missing-the-mount",
        "lesson": "#41 C1:装配漏掉挂载 → 控制组装不起来,五物验证得到的是假阴性",
        "file": _BC,
        "old": "    if marker not in text:\n        rag.write_text(text + block)",
        "new": "    if False:\n        rag.write_text(text + block)",
        "catchers": _T_CT,
    },
    {
        "id": "M42b-control-tree-drags-venv-and-git",
        "lesson": "#41 C2:不排除 .venv/.git → 7 棵手搓树各 78MB 的 .git(上游完整历史)被复制进可达树,"
                  ".venv 那条软链更直接指向隔离区",
        "file": _BC,
        "old": "    return {n for n in names if n in SKIP_DIRS}",
        "new": "    return set()",
        "catchers": _T_CT,
    },
    {
        "id": "M42c-control-tree-mounts-twice",
        "lesson": "#41 C3 反面:无条件追加 → 上游自带挂载时重复挂载(另一种装错)",
        "file": _BC,
        "old": "    if marker not in text:\n        rag.write_text(text + block)",
        "new": "    if True:\n        rag.write_text(text + block)",
        "catchers": _T_CT,
    },
    {
        "id": "M42d-control-tree-defaults-to-residue",
        "lesson": "#41 C4:默认留树 → 每验证一次五物就多 7 棵残留(这正是 7 棵手搓树的来历)",
        "file": _BC,
        "old": "        if args.keep:",
        "new": "        if True:",
        "catchers": _T_CT,
    },
    {
        "id": "M42e-control-tree-selfcheck-is-decorative",
        "lesson": "#41 C1:自检不逐字节比对 → 装错了要等五物验证出结论才发现(只写文字不执法)",
        "file": _BC,
        "old": "        if got.read_bytes() != f.read_bytes():",
        "new": "        if False:",
        "catchers": _T_CT,
    },
    {
        "id": "M44a-mount-symbol-hardcoded-to-t2",
        "lesson": "#41 C5:挂载符号写死 → 装配器只服务 T2,T3 的控制组装出来的树根本起不来",
        "file": _BC,
        "old": "            return f.stem, fn, f\"\\nfrom {f.stem} import {fn}  # noqa: E402\\n{fn}(app)\\n\"",
        "new": "            return \"research_jobs\", \"mount_research_api\", \"\\nmount_research_api(app)\\n\"",
        "catchers": _T_CT,
    },
    {
        "id": "M44b-missing-mount-is-guessed-not-refused",
        "lesson": "#41 C5:找不到挂载函数就猜一个 → 装出一棵哑树,而自检比对的是自己写进去的那行,照样发绿",
        "file": _BC,
        "old": "    raise SystemExit(f\"控制组里找不到 `def mount_*(app)`,装不出能跑的树:{src_control}\")",
        "new": "    return \"research_jobs\", \"mount_research_api\", \"\\nmount_research_api(app)\\n\"",
        "catchers": _T_CT,
    },
    {
        "id": "M43a-must-fail-all-green-still-passes",
        "lesson": "#43 V1:该红的全绿也判通过 → 需求只有文字没有执法,而验证发绿",
        "file": _VC,
        "old": "        elif name not in red:",
        "new": "        elif False:",
        "catchers": _T_VM,
    },
    {
        "id": "M43b-nothing-collected-counts-as-pass",
        "lesson": "#43 V3:一条都没跑起来时正控 must_fail 为空 → 把'什么都没跑'判成'全绿'",
        "file": _VC,
        "old": "    if not outcomes:\n        return False,",
        "new": "    if False:\n        return False,",
        "catchers": _T_VM,
    },
    {
        "id": "M43c-collateral-damage-ignored",
        "lesson": "#43 V2:不查波及 → nc6 把半套用例打红也算数,证明不了是哪条判据抓住的它",
        "file": _VC,
        "old": "        for name in sorted(red & should_be_green):",
        "new": "        for name in sorted(set()):",
        "catchers": _T_VM,
    },
    {
        "id": "M43d-green-overwrites-red-in-parametrized",
        "lesson": "#43 V4:参数化用例被后续绿覆盖 → 3 个参数红 1 个也算整体绿",
        "file": _VC,
        "old": "        if out.get(name) == \"FAILED\":       # 已经红了就不被后续绿覆盖",
        "new": "        if False:       # 已经红了就不被后续绿覆盖",
        "catchers": _T_VM,
    },
    {
        "id": "M43f-empty-suite-is-not-noticed",
        "lesson": "#43 V5:套件整跑丢失不报 → 实测中 oracle 那 10 条一条没跑,正控仍判'符合预期'",
        "file": _VC,
        "old": "        elif n == 0:",
        "new": "        elif False:",
        "catchers": _T_VM,
    },
    {
        "id": "M43g-void-exit-codes-accepted",
        "lesson": "#43 V5:pytest 内部错误/用法错误的那一跑也拿来下结论",
        "file": _VC,
        "old": "        if rc in VOID_EXITS:",
        "new": "        if False:",
        "catchers": _T_VM,
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
    },
    {
        "id": "M45b-fingerprint-not-content-stable",
        "lesson": "#S1 P1:哈希输入不排序 → 同一配置每次算出不同指纹,历史发次无法配对",
        "file": _PR,
        "old": '    return sha256_bytes(json.dumps(obj, sort_keys=True, separators=(",", ":"),',
        "new": '    return sha256_bytes(json.dumps(obj, sort_keys=False, separators=(",", ":"),',
        "catchers": _T_EP,
    },
    {
        "id": "M45c-fingerprint-covers-whole-repo",
        "lesson": "#S1 P3:指纹扩到全仓 → 改一个 docs 错别字就让全部历史发次'不可比'",
        "file": _PR,
        "old": '_EXEC_ROOT = ("src", "repoproof")',
        "new": '_EXEC_ROOT = ()',
        "catchers": _T_EP,
    },
    {
        "id": "M45d-generation-ignores-spill",
        "lesson": "#S1 P4:上了 spill 仍标 E0 → E0/E1 数据混进同一个池子(§2 规则 1 被架空)",
        "file": _PR,
        "old": '    if context.get("spill_threshold_chars") or context.get("prune_policy"):',
        "new": "    if False:",
        "catchers": _T_EP,
    },
    {
        "id": "M45e-generation-ignores-new-tools",
        "lesson": "#S1 P4:多了 editor 仍标 E0 → S4 上线后代际标签失真",
        "file": _PR,
        "old": '    tools = tuple(tool.get("tools") or _E0_TOOLS)',
        "new": "    tools = _E0_TOOLS",
        "catchers": _T_EP,
    },
    {
        "id": "M46a-window-folds-exec-results",
        "lesson": "#S2' W1:把 pytest/pip 的结果也折了 → 模型失去修复依据,且重跑要 95 秒",
        "file": _CP,
        "old": "    if not cmd or _EXEC_CMD.search(cmd):\n        return False",
        "new": "    if not cmd:\n        return False",
        "catchers": _T_WP,
    },
    {
        "id": "M46b-window-folds-everything",
        "lesson": "#S2' W2:窗口失效 → 连最近读过的代码都折掉,模型只能重读,省下的被吃回去",
        "file": _CP,
        "old": "    keep = set(reads[-window:]) if window > 0 else set()",
        "new": "    keep = set()",
        "catchers": _T_WP,
    },
    {
        "id": "M46c-window-stub-drops-the-command",
        "lesson": "#S2' W4:存根不给原命令 → 丢了还不告诉你怎么找回",
        "file": _CP,
        "old": '                f"(窗口外的旧读取结果)。需要时重跑该命令即可取回:`{cmd}`]")[:_STUB_MAX]',
        "new": '                f"(窗口外的旧读取结果)。]")[:_STUB_MAX]',
        "catchers": _T_WP,
    },
    {
        "id": "M46d-window-hides-its-lossiness",
        "lesson": "#S2' W6:有损投影不标 lossy → 后来者当成零风险,批报少一条诚实边界",
        "file": _CP,
        "old": '                 "lossy": True,',
        "new": '                 "lossy": False,',
        "catchers": _T_WP,
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
    },
    {
        "id": "M48b-blocked-directive-ignored",
        "lesson": "#N2:忽略 #!BLOCKED 照常跑 → 台账里多一条与'模型失败'同型的记录,而它其实是环境不可满足,含义相反",
        "file": _HD,
        "old": '        if line.strip().startswith("#!BLOCKED:"):',
        "new": "        if False:",
        "catchers": _T_HD,
    },
    {
        "id": "M48c-manifest-split-per-line",
        "lesson": "#N3:按行拆命令 → heredoc 被腰斩,垫片只写出半截而每条 rc=0,失败要到 oracle 才现形",
        "file": _HD,
        "old": '    for block in raw.split("\\n---\\n"):',
        "new": "    for block in raw.splitlines():",
        "catchers": _T_HD,
    },
    {
        "id": "M48d-smoke-lands-only-mount-module",
        "lesson": "#N5:只落挂载模块 → 冒烟看到的正控与控制树看到的不是同一个,冒烟不再是控制树的现场复现",
        "file": _HD,
        "old": '    for f in sorted(src_control.glob("*.py")):',
        "new": '    for f in sorted(src_control.glob(f"{module}.py")):',
        "catchers": _T_HD,
    },
    {
        "id": "M53g-guard-set-lower-bound-removed",
        "lesson": "不查守护集下界 → 一份证据靠少声明几个守护文件就能长期有效,"
                  "与'分母由被测方提供'同病(用户 2026-08-14 指出)",
        "file": _PP,
        "old": "    short = REQUIRED_GUARD_SET - guarded",
        "new": "    short = set()",
        "catchers": _T_PP,
    },
    {
        "id": "M53h-guard-set-omits-the-catalog",
        "lesson": "下界不含登记簿自身 → 改了变异登记簿(加条目/改 old/改 catcher),"
                  "旧证据仍替新一套变异背书",
        "file": _PP,
        "old": '    "scripts/mutation_gate.py",                       # 变异登记簿与证据格式',
        "new": "",
        "catchers": _T_PP,
    },
    # ---- M53:Runtime Profile 晋级判据。生命周期是**对外承诺**(它决定别人
    # 敢不敢拿这个 profile 的发次当数),所以每一道松动都是实质性的。
    {
        "id": "M53a-missing-evidence-passes",
        "lesson": "查不到证据就默认放行 → 这样的闸门与没有闸门的区别,"
                  "只在于它会让人误以为有闸门",
        "file": _PP,
        "old": ('    if m is None:\n'
                '        return [Check("G1-G4.evidence", False,'),
        "new": ('    if m is None:\n'
                '        return [Check("G1-G4.evidence", True,'),
        "catchers": _T_PP,
    },
    {
        "id": "M53b-someone-elses-evidence-counts",
        "lesson": "不核 profile_id → 拿别人的体检报告给自己晋级",
        "file": _PP,
        "old": '    if m.get("profile_id") != p.id:',
        "new": "    if False:",
        "catchers": _T_PP,
    },
    {
        "id": "M53c-level-skipping-allowed",
        "lesson": "允许 experimental 跳 qualified → 拿真实发次替'机制站不站得住'"
                  "背书,而那是两个问题",
        "file": _PP,
        "old": '        if p.lifecycle == "experimental":',
        "new": "        if False:",
        "catchers": _T_PP,
    },
    {
        "id": "M53d-fake-runs-count-as-real",
        "lesson": "冒烟发次充真实发次 → --fake positive 必定 PASS(harness 自己"
                  "塞的正控),拿它当'模型跑通了'是最容易发生的自欺",
        "file": _PP,
        "old": '            and not str(r.get("model", "")).startswith("fake")]',
        "new": "            ]",
        "catchers": _T_PP,
    },
    {
        "id": "M53e-undecidable-returns-pass",
        "lesson": "判不了却返回通过 → 把一个取舍(该不该设默认)伪装成一个测量",
        "file": _PP,
        "old": "                            ok=machine and bool(checks) and all(c.ok for c in checks),",
        "new": "                            ok=bool(checks) and all(c.ok for c in checks),",
        "catchers": _T_PP,
    },
    {
        "id": "M53f-empty-mutation-registry-passes",
        "lesson": "不查守护条目在场 → 空登记簿的逃逸数也是 0,那个'全捕'与本"
                  "profile 无关",
        "file": _PP,
        "old": "    ok = escaped == 0 and stale == 0 and not missing",
        "new": "    ok = escaped == 0 and stale == 0",
        "catchers": _T_PP,
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
    },
    {
        "id": "M54c-browser-goes-online",
        "lesson": "去掉死代理 → 离线就成了声称而不是跑出来的",
        "file": _BWK,
        "old": '        argv += ["--proxy-server=127.0.0.1:1",',
        "new": '        argv += ["--ignore-certificate-errors",',
        "catchers": _T_BCF,
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
    },
    {
        "id": "M52b-topology-gate-removed",
        "lesson": "不查拓扑就出数 → 上游若够得着,回执与八条攻击全是装饰;"
                  "'它没来敲门'会被读成偷懒,其实是它不需要",
        "file": _SCF,
        "old": "    if not topo[\"ok\"]:",
        "new": "    if False:",
        "catchers": _T_SCF,
    },
    {
        "id": "M52c-conformance-judge-ignores-red-spot",
        "lesson": "红一片就算数 → 分不清四道谓词各自在不在干活",
        "file": _SCF,
        "old": '        elif r["expect"] == "FAIL" and set(r["actual_red"]) != set(r["expect_red"]):',
        "new": "        elif False:",
        "catchers": _T_SCF,
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
    },
    {
        "id": "M51b-required-symbols-may-be-empty",
        "lesson": "sidecar 不要求符号集 → U2 判的'调的是不是契约要的能力'"
                  "失去分母,这道判据等于不存在",
        "file": _RTP,
        "old": "            if not self.required_symbols:",
        "new": "            if False:",
        "catchers": _T_RTP,
    },
    {
        "id": "M51c-profile-id-can-be-redefined",
        "lesson": "同 id 可改语义 → 台账里一个 profile_id 底下混着两种行为,"
                  "回执的 runtime.profile_id 从此不可信",
        "file": _RTP,
        "old": "    if p.id in _REGISTRY and _REGISTRY[p.id] != p:",
        "new": "    if False:",
        "catchers": _T_RTP,
    },
    {
        "id": "M51d-symbol-allowlist-not-enforced",
        "lesson": "白名单不在执行前拦 → sidecar 替被测方执行了契约之外的东西;"
                  "U2 只判已发生的执行对不对,拦不住不该发生的执行",
        "file": _USC,
        "old": "        if fn is None:",
        "new": "        if fn is None and False:",
        "catchers": _T_RTP,
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
    },
    {
        "id": "M50b-matrix-skips-selfcheck",
        "lesson": "矩阵不自证 → 报出来的'全被抓住'分不清是验证器真抓住了还是脚本在读期望值",
        "file": _RCS,
        "old": "    bad = selfcheck()\n    if bad:",
        "new": "    bad = []\n    if bad:",
        "catchers": _T_RCS,
    },
    {
        "id": "M50c-discrimination-gate-removed",
        "lesson": "不查判别力 → 一道恒红的判据与'永远报错'无从区分,却照样发绿",
        "file": _RCS,
        "old": "        if not green_in:",
        "new": "        if False:",
        "catchers": _T_RCS,
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
    },
    {
        "id": "M49b-signature-always-valid",
        "lesson": "#R2:签名校验形同虚设 → agent 自己造一张回执塞进台账即可过关",
        "file": _RC_M,
        "old": "        if not self.receipt_signature:\n            return False",
        "new": "        if not self.receipt_signature:\n            return True",
        "catchers": _T_UR,
    },
    {
        "id": "M49c-chain-ignores-prev-hash",
        "lesson": "#R3:链校验不看 prev_sha256 → 事后改写/删行/换序全都查不出,第三方也就无从独立复核",
        "file": _RC_L,
        "old": '        if row.get("prev_sha256") != prev:',
        "new": "        if False:",
        "catchers": _T_UR,
    },
    {
        "id": "M49d-coverage-passes-without-a-unit-list",
        "lesson": "#R6:没有待办清单就默认通过 → 没有分母,'象征性调用一次'永远抓不住",
        "file": _RC_V,
        "old": "    if expected_units is None:\n        f.append(Finding(\"U3.coverage\", False,",
        "new": "    if expected_units is None:\n        f.append(Finding(\"U3.coverage\", True,",
        "catchers": _T_UR,
    },
    {
        "id": "M49e-run-nonce-not-checked",
        "lesson": "重放:不校验 run_nonce → 上一次 run 的回执签名有效、内容完好,直接拿来充数",
        "file": _RC_V,
        "old": "               and r.binding.run_nonce == run_nonce",
        "new": "               and True",
        "catchers": _T_UR,
    },
    {
        "id": "M49f-upstream-identity-not-enforced",
        "lesson": "真包在场跑复制实现:不比 artifact_hash → 自带同名包、"
                  "照抄 __version__ 即可(T3 批 13 原样)",
        "file": _RC_V,
        "old": "            if want and got != want:",
        "new": "            if False:",
        "catchers": _T_UR,
    },
    {
        "id": "M49g-adoption-uses-containment-not-equality",
        "lesson": "#43 坑三:采纳判据从'相等'退化成'包含' → 把上游结果里的"
                  "一个标记抄进产物即可满足,实质内容仍是自写的",
        "file": _RC_V,
        "old": "        missing = [u for u in units if u not in want]",
        "new": "        missing = [] if want else list(units)",
        "catchers": _T_UR,
    },
    {
        "id": "M47a-mechanism-runs-count-toward-gate",
        "lesson": "#K3:机制消融混进闸门 → 批 14 把 T2 passes 从 5 抬到 14,读起来像能力提升 180%",
        "file": _BR,
        "old": '    mechanism = [r for r in prereg if r["run_purpose"] in MECHANISM_PURPOSES]',
        "new": "    mechanism = []",
        "catchers": _T_RCL,
    },
    {
        "id": "M47b-classification-rewrites-verdict",
        "lesson": "#K1:分类改写原始 verdict → 篡改证据(那些发次确实跑完了、确实是那个结果)",
        "file": _BR,
        "old": '            "run_purpose": c.get("run_purpose", "CAPABILITY_EVALUATION"),',
        "new": '            "run_purpose": c.get("run_purpose", "CAPABILITY_EVALUATION"),\n'
               '            "verdict": "PASS_ADAPTED",',
        "catchers": _T_RCL,
    },
    {
        "id": "M47c-undelivered-treatment-counted",
        "lesson": "#K4:处理零生效仍计处理效应 → 把'没做实验'当成'处理无害的证据'",
        "file": _BR,
        "old": ('        "treatment_not_delivered_runs": sum(\n'
                '            1 for r in rows if r["treatment_assigned"] and r["treatment_activated"] is False),'),
        "new": '        "treatment_not_delivered_runs": 0,',
        "catchers": _T_RCL,
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
    },
    {
        "id": "M43e-never-ran-counts-as-red",
        "lesson": "#43 V3 近亲:该红的那条根本没被收集到时直接跳过 → 没跑当成红了",
        "file": _VC,
        "old": "        if name not in outcomes:\n            problems.append(f\"{name}:预期必红,但它根本没跑\")",
        "new": "        if name not in outcomes:\n            continue",
        "catchers": _T_VM,
    },
]


# ---------------------------------------------------------------- 执行机构

def _git(*args: str, cwd: Path = REPO) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def _run_subset(tree: Path, catchers: list[str]) -> tuple[int, str]:
    env = dict(os.environ, PYTHONPATH=str(tree / "src"))
    proc = subprocess.run(
        [str(PYTEST), *catchers, "-q", "-x", "-p", "no:cacheprovider"],
        cwd=tree, env=env, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr)[-800:]


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
            code, tail = _run_subset(tree, all_catchers)
            if code != 0:
                print(f"[ABORT] 基线不绿(exit={code}),无从归因变异:\n{tail}")
                return 2
            # 金丝雀:证明测的是变异体不是主树
            err = _apply(tree, CANARY)
            if err:
                print(f"[ABORT] 金丝雀 STALE:{err}")
                return 2
            code, tail = _run_subset(tree, CANARY["catchers"])
            _restore(tree, CANARY)
            if code == 0:
                print("[ABORT] 金丝雀未被抓住 —— worktree 隔离失效,"
                      "本闸门在测主树而非变异体,一切结论无效。")
                return 2
            print(f"金丝雀 CAUGHT(exit={code})—— 隔离通路自证有效。\n")

            for m in MUTATIONS:
                t0 = time.monotonic()
                err = _apply(tree, m)
                if err:
                    results.append({"id": m["id"], "lesson": m["lesson"],
                                    "outcome": "STALE", "detail": err})
                    print(f"  STALE   {m['id']} —— {err}")
                    continue
                code, tail = _run_subset(tree, m["catchers"])
                _restore(tree, m)
                outcome = "CAUGHT" if code != 0 else "ESCAPED"
                results.append({
                    "id": m["id"], "lesson": m["lesson"], "file": m["file"],
                    "outcome": outcome, "pytest_exit": code,
                    "catchers": m["catchers"],
                    "seconds": round(time.monotonic() - t0, 1),
                    **({"tail": tail} if outcome == "ESCAPED" else {}),
                })
                print(f"  {outcome:7s} {m['id']}  ({results[-1]['seconds']}s)")
        finally:
            _git("worktree", "remove", "--force", str(tree))
            _git("worktree", "prune")

    caught = sum(1 for r in results if r["outcome"] == "CAUGHT")
    bad = [r for r in results if r["outcome"] != "CAUGHT"]
    # 显式声明**这份证据守护哪些文件** —— 这些文件一变,证据就该作废。
    # 含登记簿自身:改了登记簿(加条目、改 old/new、改 catcher),旧证据当然
    # 不再代表现在这套变异。派生自 MUTATIONS 而非从 results 反推,是为了
    # 让 STALE/ESCAPED 的条目也算数(它们守护的文件同样相干)。
    guard_set = sorted(
        {m["file"] for m in MUTATIONS if m.get("file")}
        | {c for m in MUTATIONS for c in (m.get("catchers") or [])}
        | {"scripts/mutation_gate.py"})
    report = {
        "head_commit": head,
        "mutations": len(MUTATIONS),
        "guard_set": guard_set,
        "caught": caught,
        "escaped": [r["id"] for r in results if r["outcome"] == "ESCAPED"],
        "stale": [r["id"] for r in results if r["outcome"] == "STALE"],
        "capture_rate": f"{caught}/{len(MUTATIONS)}",
        "wall_seconds": round(time.monotonic() - t_start, 1),
        "results": results,
    }
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    dest = EVIDENCE_DIR / f"{head[:12]}.json"
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"\n捕获率 {report['capture_rate']};证据已落盘:{dest}")
    if bad:
        print("未达 100% —— ESCAPED 当场补钉死,STALE 更新登记簿。绝不带病放行。")
        return 1
    return 0


if __name__ == "__main__":
    if "--list" in sys.argv:
        for m in MUTATIONS:
            print(f"{m['id']:36s} {m['lesson']}")
        sys.exit(0)
    sys.exit(run_gate())
