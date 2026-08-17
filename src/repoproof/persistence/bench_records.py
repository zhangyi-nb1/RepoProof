"""Benchmark V2 记录器(Phase 0 ⑥,TESTPLAN-V2 §9)。

单一事实源:`benchmarks/v2/runs.jsonl`,每 run 一行 append-only。
纪律:字段缺失/None 一律写 "UNKNOWN",**绝不写 0 冒充**(源方案 §15
与项目踩坑史:纸面 0 会被当成真实测量值,污染后续统计);未知字段
不丢弃(如实入行,便于 schema 演进);同 run_id 重复追加拒绝。

**人工再分类旁挂**(2026-08-11 增补,LESSONS #24/#26):系统 verdict
与人工取证判定可能相左(首例:order-38 系统 PASS_ADAPTED,人工判
FALSE PASS)。runs.jsonl **永不改写**——再分类写入旁挂
`adjudications.jsonl`,按 run_id 连接。**闸门与任何 PASS 统计必须走
`adjudicated_runs()` / `count_passes()`,不得直接数 runs.jsonl 的
verdict**,否则会把已判无效的假 PASS 计入。

目录布局(TESTPLAN §7/§9):

    benchmarks/v2/
    ├── runs.jsonl            事实源(本模块唯一写入点,append-only 不改写)
    ├── adjudications.jsonl   人工再分类旁挂(按 run_id 连接,亦 append-only)
    ├── preregistrations/     预注册(冻结时落盘,批作废需重预注册)
    └── reports/              停点报告(源 §48 清单)
"""

from __future__ import annotations

import json
from pathlib import Path

# TESTPLAN §9 的最少字段集(缺失写 UNKNOWN)
REQUIRED_FIELDS = (
    "run_id", "task_id", "task_version", "harness_commit", "host_commit",
    "source_commit", "model", "provider", "provider_config_hash",
    "run_index", "run_order", "guided", "max_rounds", "rounds_used",
    "model_calls", "commands", "input_tokens", "output_tokens", "wall_time",
    "cost", "public_passed_by_round", "regression_by_round", "rollback_count",
    "scope_change_count", "stagnation", "final_capability", "final_regression",
    "policy", "replay", "verdict", "failure_types", "execution_backend",
    "env_baseline_hash", "main_dir_integrity", "trace_sha256", "bundle_path",
    # 执行侧四面指纹(S1,2026-08-14)。provider 面沿用 provider_config_hash;
    # 其余三面 + 代际 + 代码内容指纹拆开记,供 E1 消融单变量归因。
    # 历史行无这些字段 —— 只增不改,取数时按缺失=E0 处理。
    "tool_profile_hash", "context_profile_hash", "budget_profile_hash",
    "exec_generation", "exec_fingerprint",
    # 语义分面(2026-08-14):按谁拥有这段语义划,不按目录划。改量具/验证器
    # 不再让执行语义指纹变动 —— 那种跨代失配没有信息量,只有摩擦。
    "executor_semantics_fingerprint", "model_profile_fingerprint",
    "verifier_fingerprint", "instrumentation_fingerprint", "analysis_schema_version",
    # 上游交付拓扑(A1,2026-08-14)。单独一个字段而不是只藏在 exec_generation
    # 串里 —— 分析时要能直接按 profile 分组,不必去解析标签字符串。
    # 历史行无此字段 = rt-inprocess-v1(那时只有这一种拓扑)。
    "runtime_profile_id",
    # Agent backend 轴(DSH 阶段 2,2026-08-17)。谁在跑 agent 循环 ——
    # 与 execution_backend(命令落地基底,local-worktree)是两个轴。
    # 历史行无此字段 = mini-swe(那时只有这一个循环)。
    "backend_id",
    # 宿主身份(C 轨,2026-08-15)。阶段闸门是**第一宿主**上的存在性证明,
    # 而阶段归属一直靠 task_id 前缀 —— 第二宿主的 `t3-<新宿主>-…` 会自动
    # 进 stages.T3。历史行无此字段 = 第一宿主(那时只有这一个)。
    "host_id",
)

UNKNOWN = "UNKNOWN"

# 计入闸门的判决。**显式集合,禁止用 "PASS" in verdict 子串判断**——
# "FALSE_PASS" 含 "PASS",子串法会把已判无效的假 PASS 数成通过。
PASS_VERDICTS = frozenset({"PASS", "PASS_ADAPTED"})

# 批次归属(2026-08-12 增补)。UI 泛化到 T1–T4 后用户可随时加发观察方差,
# 而 TESTPLAN §8 要求正式批次先预注册。若台账里两者长得一样,日后重算闸门
# 会把探索性 PASS 一并数进去——与 order-38 同类:真话写在机器读不到的地方。
# 故:探索性发次**在写入时**打此标,`count_passes` 不计入闸门。
# 历史行无 batch 字段 → 视为预注册批次(它们确实是)。
EXPLORATORY_BATCH = "EXPLORATORY_UNPREREGISTERED"

# 冒烟模型前缀(2026-08-12 增补)。`--fake positive` 由 harness **把正控
# 脚本化塞进适配树**——它必定 PASS,那是机器自检,不是模型做到的。此前
# `count_passes` 未排除 fake,于是 T1 的闸门数字是 3,而真实模型 PASS 只有
# 2(第 3 个是 `fake-scripted`)。与 order-38、探索性加发同一个病:台账把
# 不该算的算进了通过数。
SMOKE_MODEL_PREFIX = "fake"

# 再分类记录的最少字段;evidence_refs 必填 = 裁定不得无出处
ADJUDICATION_REQUIRED_FIELDS = (
    "run_id", "system_verdict", "effective_verdict",
    "adjudicated_at", "adjudicated_by", "basis", "evidence_refs",
)


class BenchRecordError(RuntimeError):
    pass


def bench_root(project_root: str | Path) -> Path:
    return Path(project_root).expanduser().resolve() / "benchmarks" / "v2"


def ensure_layout(project_root: str | Path) -> Path:
    root = bench_root(project_root)
    for d in ("preregistrations", "reports"):
        (root / d).mkdir(parents=True, exist_ok=True)
    for f in ("runs.jsonl", "adjudications.jsonl"):
        if not (root / f).exists():
            (root / f).touch()
    return root


def normalise_record(record: dict) -> dict:
    """补齐必需字段(缺失/None → UNKNOWN);保留未知字段;拒绝 run_id 缺失。"""
    if not record.get("run_id"):
        raise BenchRecordError("run 记录必须携带非空 run_id")
    out = dict(record)
    for f in REQUIRED_FIELDS:
        v = out.get(f)
        if v is None or v == "":
            out[f] = UNKNOWN
    return out


def append_run(project_root: str | Path, record: dict) -> Path:
    """追加一行 run 记录;同 run_id 重复追加拒绝(append-only 事实源)。"""
    root = ensure_layout(project_root)
    rec = normalise_record(record)
    # `normalise_record` 对缺失字段一律填 UNKNOWN 而不报错 —— 所以光把
    # `host_id` 加进 REQUIRED_FIELDS 等于什么都没做:新宿主漏填就变成
    # UNKNOWN,而 `_same_host` 把 UNKNOWN 当第一宿主放行,发次照样进闸门。
    # 这里显式拒绝:**宿主是谁,写账的人必须说得出来。**
    if rec.get("host_id") in (None, "", UNKNOWN):
        raise BenchRecordError(
            "run 记录必须携带 host_id —— 阶段闸门是第一宿主上的存在性证明,"
            "宿主说不清就没法判这一发该不该进闸门")
    path = root / "runs.jsonl"
    for existing in load_runs(project_root):
        if existing.get("run_id") == rec["run_id"]:
            raise BenchRecordError(
                f"run_id 已存在,事实源 append-only 拒绝重写:{rec['run_id']}")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def load_runs(project_root: str | Path) -> list[dict]:
    path = bench_root(project_root) / "runs.jsonl"
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


# ---------------------------------------------------------------- 人工再分类

def load_adjudications(project_root: str | Path) -> list[dict]:
    path = bench_root(project_root) / "adjudications.jsonl"
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def append_adjudication(project_root: str | Path, record: dict) -> Path:
    """追加一条人工再分类。

    校验:①必需字段齐全(含 evidence_refs,裁定不得无出处);②run_id 必须
    存在于 runs.jsonl(不得裁定不存在的运行);③system_verdict 必须与台账
    实际值一致(防止照着记忆写错行);④同 run_id 不得重复裁定。
    **不触碰 runs.jsonl。**
    """
    root = ensure_layout(project_root)
    rec = dict(record)
    missing = [f for f in ADJUDICATION_REQUIRED_FIELDS if not rec.get(f)]
    if missing:
        raise BenchRecordError(f"再分类记录缺字段:{missing}")

    runs = {r.get("run_id"): r for r in load_runs(project_root)}
    run = runs.get(rec["run_id"])
    if run is None:
        raise BenchRecordError(f"run_id 不在 runs.jsonl 中,拒绝裁定:{rec['run_id']}")
    if run.get("verdict") != rec["system_verdict"]:
        raise BenchRecordError(
            "system_verdict 与台账不一致,拒绝写入(疑似写错行):"
            f"台账={run.get('verdict')} 记录={rec['system_verdict']}")
    for existing in load_adjudications(project_root):
        if existing.get("run_id") == rec["run_id"]:
            raise BenchRecordError(f"该 run 已有裁定,append-only 拒绝重写:{rec['run_id']}")

    path = root / "adjudications.jsonl"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def adjudicated_runs(project_root: str | Path) -> list[dict]:
    """runs.jsonl ⋈ adjudications.jsonl。

    每行附加 `effective_verdict`(无裁定则等于系统 verdict)与 `adjudication`
    (裁定原文或 None)。**闸门/统计的唯一入口**,原始 verdict 字段原样保留。
    """
    by_run = {a["run_id"]: a for a in load_adjudications(project_root)}
    out: list[dict] = []
    for run in load_runs(project_root):
        adj = by_run.get(run.get("run_id"))
        merged = dict(run)
        merged["effective_verdict"] = adj["effective_verdict"] if adj else run.get("verdict")
        merged["adjudication"] = adj
        out.append(merged)
    return out


# ---------------------------------------------------------------- 用途分类
# 2026-08-14:批 14 的 12 发机制消融跑在 T2v5 上,把 T2 的 passes 从 5 抬到
# 14 —— 那个数字读起来像"模型能力通过数",而它们回答的是"S2' 在**已见任务**
# 上的局部机制效应"。分类**旁挂**在 run_classifications.jsonl,原始 verdict
# 一字不动(与 adjudications 同源纪律:runs.jsonl 只追加)。

CLASSIFICATIONS_FILE = "run_classifications.jsonl"

# 不计阶段闸门的用途:它们不回答"这个任务可判且可过"。
MECHANISM_PURPOSES = frozenset({
    "MECHANISM_ABLATION",      # E1 执行器消融(批 14)
    "CRITERIA_INTEGRITY",      # AR 判据完整性(批 13)
    "HARNESS_SELFCHECK",       # F0 自检
})

# 同样不充闸门,但**不是机制消融** —— 分开一个集合是为了别把它们计进
# `mechanism_ablation_runs`,那个数字有自己的含义。
#
# 2026-08-15 首批 PQ 发次当场撞出来的:`_denominators` 里白纸黑字写着
# "PQ:runtime profile 资格审 —— **不充闸门、不计模型能力**",而扣除逻辑
# 只认 MECHANISM_PURPOSES,于是四发 PQ 直接把 T3 的 passes 从 3 抬到 7。
# **散文说不算,代码算了** —— 这正是 process-independence 要防的那种缝。
QUALIFICATION_PURPOSES = frozenset({
    "RUNTIME_PROFILE_QUALIFICATION",   # PQ:profile 资格审(G6/G7)
})

# 阶段闸门的扣除面 = 机制类 ∪ 资格审类。
NON_GATEABLE_PURPOSES = MECHANISM_PURPOSES | QUALIFICATION_PURPOSES

# Agent backend 基线(DSH 阶段 8,M-DSH-13)。能力池与 held-out 只收基线
# 循环的发次:换 agent 循环 = 换执行语义 = 另一道题(与 runtime profile
# 永不互比同律)。历史行缺列/UNKNOWN = mini-swe(backend_id 字段注释的
# 既定语义:那时只有这一个循环)。放开一个新 backend 进能力池必须改这行
# 代码 —— 显式 diff,不是分类旁挂里一句自述。
BASELINE_BACKEND = "mini-swe"


def load_classifications(project_root: str | Path) -> dict[str, dict]:
    """→ {run_id: 分类记录}。文件缺失即空 —— 未分类的历史发次按常规处理。"""
    path = Path(project_root) / "benchmarks" / "v2" / CLASSIFICATIONS_FILE
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            out[rec["run_id"]] = rec          # 后写覆盖前写,便于更正
    return out


# 分类旁挂允许出现的键。**白名单而非黑名单**:字段名打错(如
# `evidence_strenght`)会让该字段静默取默认值 —— `evidence_strength` 的默认
# 是 "STANDARD",也就是**打错字 = 降级悄悄失效**,失效方向朝松。值打错反而
# 安全(非 STANDARD 一律算降级)。所以要防的是键,不是值。
CLASSIFICATION_KEYS = frozenset({
    "run_id", "run_order", "basis", "classified_at", "notes",
    "test_mode", "run_purpose", "task_seen",
    "counts_toward_model_capability", "counts_toward_heldout_benchmark",
    "counts_toward_mechanism_effect", "counts_toward_treatment_effect",
    "treatment_assigned", "treatment_activated", "exclusion_reason",
    "assistance_level", "classification_timing",
    "evidence_strength", "evidence_caveat",
    "counts_toward_profile_qualification",
    # 严口径 held-out(用户 2026-08-15 裁决):oracle 是谁写的。
    # 只有 UPSTREAM_OWN_TEST_SUITE 才让 counts_toward_heldout_benchmark 生效。
    "oracle_authorship",
    # 第二道:harness 对宿主做了什么。加语义(ENRICHED)的一律不算 held-out ——
    # 上游测试此刻在考我们发明的东西,oracle 文本谁写的就不重要了。
    "host_modification_mode",
})


def unknown_classification_keys(project_root: str | Path) -> dict[str, list[str]]:
    """分类旁挂里出现的未登记键 —— 空字典才算干净。"""
    bad: dict[str, list[str]] = {}
    for rid, c in load_classifications(project_root).items():
        extra = sorted(set(c) - CLASSIFICATION_KEYS)
        if extra:
            bad[rid] = extra
    return bad


def classify_runs(project_root: str | Path) -> list[dict]:
    """台账 ⋈ 裁定 ⋈ 分类。**原始 verdict 原样保留**(判据 K1),分类字段
    以缺省值补齐 —— 未分类 = 常规能力评估发次。"""
    cls = load_classifications(project_root)
    rows = []
    for r in adjudicated_runs(project_root):
        c = cls.get(r.get("run_id"), {})
        # backend 第三锁(M-DSH-13,2026-08-17):非基线 backend 的发次不入
        # 能力池、不入 held-out,**分类文件说什么都不算**(自述不能自证,
        # 与下面 oracle 两道锁同款结构)。B-dsh 桥接批只回答机制效应
        # (counts_toward_mechanism_effect 走自己的轴),不回答"模型多能干"。
        backend = r.get("backend_id", UNKNOWN)
        baseline_backend = backend in (BASELINE_BACKEND, UNKNOWN)
        rows.append({
            **r,
            "test_mode": c.get("test_mode", "UNCLASSIFIED"),
            "run_purpose": c.get("run_purpose", "CAPABILITY_EVALUATION"),
            "task_seen": c.get("task_seen", True),
            "counts_toward_model_capability": bool(
                c.get("counts_toward_model_capability", True)
                and baseline_backend),
            # 严口径闸门,**两道**:
            #   ① oracle 必须是外部来的(测试文本不是我们写的);
            #   ② harness 对宿主的改动必须只是挖空,不许加语义 —— 否则上游测试
            #      实际在考我们发明的东西,oracle 的文本来源就没有意义了。
            # 分类文件说 true 也不算:自述不能自证。
            "counts_toward_heldout_benchmark": bool(
                c.get("counts_toward_heldout_benchmark", False)
                and baseline_backend
                and c.get("oracle_authorship") == ORACLE_AUTHORSHIP_EXTERNAL
                and c.get("host_modification_mode", HOST_MOD_PRISTINE)
                in _HELDOUT_OK_HOST_MODS),
            "oracle_authorship": c.get("oracle_authorship", ORACLE_AUTHORSHIP_OURS),
            "host_modification_mode": c.get("host_modification_mode", HOST_MOD_PRISTINE),
            "counts_toward_mechanism_effect": c.get("counts_toward_mechanism_effect", False),
            "counts_toward_treatment_effect": c.get("counts_toward_treatment_effect"),
            "treatment_assigned": c.get("treatment_assigned", False),
            "treatment_activated": c.get("treatment_activated"),
            "exclusion_reason": c.get("exclusion_reason"),
            "assistance_level": c.get("assistance_level"),
            "classification_timing": c.get("classification_timing"),
            # 证据强度分面(2026-08-14,判据 K7)。**与 verdict / 裁定 /
            # 闸门计数完全正交** —— 它不改判任何一发,只回答"这一发还能不能
            # 被当作强证据引用"。用户 2026-08-14 指令:那三发旧 T3v5 PASS
            # "不要追溯改判,但也不要继续当强证据"。两件事必须分开表达,
            # 因为把它们合并只有两种走法,都错:改判 = 编造当时不存在的
            # 事实;不管 = 让一份已知有疑的证据继续以全强度流通。
            "counts_toward_profile_qualification": c.get(
                "counts_toward_profile_qualification", False),
            "evidence_strength": c.get("evidence_strength", "STANDARD"),
            "evidence_caveat": c.get("evidence_caveat"),
        })
    return rows


# 阶段闸门(T1–T4)是**第一宿主**上的存在性证明。历史行没有 host_id 字段,
# 缺失 = 那时只有这一个宿主(与 runtime_profile_id 同一条处理规则)。
BASELINE_HOST = "zhangyi-nb1/offerclaw"

# ------------------------------------------------------------------ held-out 口径
# 用户 2026-08-15 裁决:**严口径 —— 我们写的 oracle 一律不算 held-out。**
#
# 在此之前盘上两套措辞并存且自相矛盾:TESTPLAN §11.4 要求"未参与 harness
# 开发",而 §7 又要求第二宿主"照旧走全流程",§7 的 hidden oracle 仍由我们写。
# 不裁的话,第一发 held-out 落账时 `counts_toward_heldout_benchmark` 填什么
# 就成了临场判断 —— 数字先出来、口径后跟上,这是本项目最贵的一种错。
#
# 严口径的可操作形式:**oracle 的作者必须不是我们**。任务包必须显式声明
# oracle 从哪来;声明不出外部来源的,`counts_toward_heldout_benchmark`
# 一律按 false 处理,**不管分类文件里写了什么**。
#
# 为什么是"不管写了什么":分类是旁挂的自述文件,手一滑就能置 true,而
# held-out 是四类分母里唯一被直接读成"模型能力"的那个。自述不能自证。
ORACLE_AUTHORSHIP_EXTERNAL = "UPSTREAM_OWN_TEST_SUITE"   # 目标仓自带,我们没碰
ORACLE_AUTHORSHIP_OURS = "AUTHORED_BY_HARNESS"           # 我们写的(T1–T3 全部)

# ---- 严口径的**第二道**闸门(2026-08-15,设计评审当场查出的盲区)----
#
# 只看 oracle_authorship 是不够的:它管的是**测试文本**谁写的,对"harness 改写了
# **非测试**源码"完全无感。于是有一条又宽又隐蔽的路 ——
#
#     把宿主源码改得面目全非、往里塞进我们自己发明的接线语义,
#     上游那 554 条此刻实际在检验"你有没有猜对**我们新加的**东西",
#     而闸门照样认它是 held-out。
#
# 这不是假想:本次第二宿主的三份设计里,有一份(contrarian)的最大 trap 判的就是
# harness 自造的 `register_doc_preparer` + 现摇 priority,71 条上游测试为它服务。
# 做它等于亲手把第一发 held-out 数字喂进盲区。
#
# 可判的分界线:**只许挖空,不许加语义。**
#   HOLLOW_ONLY —— 改动只是把原件里**已存在**的符号换成 NotImplementedError。
#                  上游测试考的仍是上游自己的语义,只是实现被拿走了。
#   ENRICHED    —— 引入了原件里没有的符号/行为。上游测试此刻在考我们发明的东西,
#                  **不算 held-out**,不管 oracle 的文本是谁写的。
#   PRISTINE    —— 宿主一个字没改(T1–T3 是这种:改的是"加一个新功能",
#                  而 oracle 本来就是我们写的,已被第一道闸门挡掉)。
HOST_MOD_PRISTINE = "PRISTINE"
HOST_MOD_HOLLOW_ONLY = "HOLLOW_ONLY"
HOST_MOD_ENRICHED = "ENRICHED"
_HELDOUT_OK_HOST_MODS = frozenset({HOST_MOD_PRISTINE, HOST_MOD_HOLLOW_ONLY})


def _same_host(row: dict) -> bool:
    """这一发是不是跑在第一宿主上。

    为什么要有它(2026-08-15,C0-4):阶段归属靠 `task_id.startswith("t3-")`,
    于是**任何**叫 `t3-<新宿主>-…` 的发次都会自动进 `stages.T3`。这不是将来
    的风险 —— `t3-sidecar-page-facts-v1`(另一份 oracle、另一套判据)现在就
    被算在 stages.T3 里,只是靠 `run_purpose` 挡在 `passes` 之外,而那道挡板
    刚在 2026-08-15 补上(M58b)。第二宿主一来,同样的洞会以"能力数字"的
    形式再犯一次,后果重得多。
    """
    h = row.get("host_id")
    return h in (None, "", UNKNOWN, BASELINE_HOST)


def count_passes(project_root: str | Path, task_prefix: str | None = None) -> dict:
    """按 effective_verdict 统计 PASS(闸门判据)。

    task_prefix 形如 "t3-" 时只统计该阶段。**三道扣除**:
    1. 人工裁定不计入的假 PASS(invalidated);
    2. `batch == EXPLORATORY_BATCH` 的探索性加发(exploratory)——未经预注册
       (TESTPLAN §8),只能作观察,不得充闸门;
    3. `model` 以 `fake` 开头的冒烟发(smoke)——`--fake positive` 是 harness
       自己把正控塞进适配树,必定 PASS,那是机器自检不是模型能力。
    `total` 仍是全部发次(如实计数不挑选),`passes` 是**可充闸门**的通过数。
    """
    rows = classify_runs(project_root)
    if task_prefix:
        rows = [r for r in rows if str(r.get("task_id", "")).startswith(task_prefix)
                and _same_host(r)]
    smoke = [r for r in rows
             if str(r.get("model", "")).startswith(SMOKE_MODEL_PREFIX)]
    real = [r for r in rows
            if not str(r.get("model", "")).startswith(SMOKE_MODEL_PREFIX)]
    exploratory = [r for r in real if r.get("batch") == EXPLORATORY_BATCH]
    prereg = [r for r in real if r.get("batch") != EXPLORATORY_BATCH]
    # 第四道扣除(2026-08-14,判据 K3):机制消融/判据完整性发次不充闸门。
    # 2026-08-15 补上 PQ:它答的是"这个 runtime profile 够不够格",不是
    # "这个任务可判且可过" —— 混进去会让 profile 资格审自己抬高阶段闸门。
    mechanism = [r for r in prereg if r["run_purpose"] in MECHANISM_PURPOSES]
    gateable = [r for r in prereg if r["run_purpose"] not in NON_GATEABLE_PURPOSES]
    passes = [r for r in gateable if r["effective_verdict"] in PASS_VERDICTS]
    invalidated = [
        r for r in rows
        if r.get("verdict") in PASS_VERDICTS and r["effective_verdict"] not in PASS_VERDICTS
    ]
    return {
        "total": len(rows),
        "passes": len(passes),
        # ---- 能力分母拆分(判据 K2):闸门不得只有一个 passes 数字 ----
        "all_valid_run_outcomes": sum(
            1 for r in rows if r["effective_verdict"] in PASS_VERDICTS),
        "development_baseline_runs": len(gateable),
        "mechanism_ablation_runs": len(mechanism),
        "mechanism_ablation_passes": sum(
            1 for r in mechanism if r["effective_verdict"] in PASS_VERDICTS),
        # Held-out 能力评测。**四道扣除和 passes 一模一样** ——
        # 2026-08-15(C0-2)之前它是 `for r in rows`,一道扣除都没有:
        # 冒烟(现 35 发)、探索性加发(7)、已裁定无效(4)只要有人手滑把
        # `counts_toward_heldout_benchmark` 置 true 就全进这个数,而这个数字
        # 是四类分母里**唯一直接读成"模型能力"**的那个。现在还没有第二宿主
        # 所以它恒为 0,谁也没发现 —— 那正是最坏的时机:第一批 held-out 发次
        # 落账时,污染会和真数一起进来,而"它一直是 0"看起来像它没问题。
        "heldout_model_evaluation_runs": sum(
            1 for r in gateable if r["counts_toward_heldout_benchmark"]),
        # 通过数也要有。其余三类(机制/探索/冒烟)都有各自的 passes,
        # 唯独 held-out 只有 runs —— 只有分母没有分子,引用时必然有人自己配一个。
        "heldout_passes": sum(
            1 for r in gateable
            if r["counts_toward_heldout_benchmark"]
            and r["effective_verdict"] in PASS_VERDICTS),
        "assisted_repair_runs": sum(1 for r in rows if r.get("assistance_level")),
        "treatment_delivered_runs": sum(
            1 for r in rows if r["treatment_activated"] is True),
        "treatment_not_delivered_runs": sum(
            1 for r in rows if r["treatment_assigned"] and r["treatment_activated"] is False),
        "profile_qualification_runs": sum(
            1 for r in rows if r["counts_toward_profile_qualification"]),
        "post_hoc_classified_runs": sum(
            1 for r in rows
            if r["classification_timing"] == "POST_HOC_TAXONOMY_CORRECTION"),
        "invalidated": len(invalidated),
        "exploratory": len(exploratory),
        "exploratory_passes": sum(
            1 for r in exploratory if r["effective_verdict"] in PASS_VERDICTS),
        "smoke": len(smoke),
        "smoke_passes": sum(
            1 for r in smoke if r["effective_verdict"] in PASS_VERDICTS),
        # 降级证据:仍计入 passes(未被改判),但引用时必须带上保留意见
        "provisional_evidence_runs": sum(
            1 for r in rows if r["evidence_strength"] != "STANDARD"),
        "pass_run_ids": [r.get("run_id") for r in passes],
        "provisional_evidence": [
            {"run_id": r.get("run_id"), "strength": r["evidence_strength"],
             "caveat": r.get("evidence_caveat"),
             "still_counted_in_passes": r.get("run_id") in {x.get("run_id") for x in passes}}
            for r in rows if r["evidence_strength"] != "STANDARD"],
        "invalidated_run_ids": [r.get("run_id") for r in invalidated],
        "exploratory_run_ids": [r.get("run_id") for r in exploratory],
        "smoke_run_ids": [r.get("run_id") for r in smoke],
    }
