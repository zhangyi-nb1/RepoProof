"""执行侧四类 profile 指纹与代际标签(EXECUTOR-UPGRADE-PLAN S1)。

**为什么拆成四个 hash 而不是一个**:一个大 hash 只能告诉你"配置变了",
拆开才能告诉你"变的是工具面、上下文面还是预算面"。E1 消融的全部意义是
单变量归因,而单变量归因要求指纹也是单变量的。

四面:

    provider_profile   谁在答(provider/model/协议/采样)—— 已由
                       provider_gate.ProviderConfig.config_sha256 承担,本模块不重做
    tool_profile       给它什么工具:action_protocol / tools / obs_char_cap /
                       persistent_shell / repeat_guard
    context_profile    给它看什么:policy / obs_char_cap / spill_threshold_chars /
                       prune_policy / contract_capsule / requirement_state
    budget_profile     给它多少额度:契约 budgets 全量(预算改动必须让批次不可比,§39)

三面都是普通 dict,直接传给 `profile_hashes()` —— 不设包装函数,那种
`def f(**kw): return dict(kw)` 只是噪声。

外加两个派生量:

    exec_fingerprint   发次路径上的代码内容哈希(只认 src/repoproof/**)
    exec_generation    代际标签,**由内容推导**,不由调用方声明

`exec_fingerprint` 刻意不用 `git rev-parse HEAD`:改一个 docs 错别字就会
让全部历史发次"不可比",而它们其实逐字节同源(实测 0d35856..HEAD 只动了
scripts/ 与 docs/,src/ 未变 —— 批 11 的 E0 格子因此可以在 HEAD 直接补齐)。
"""

from __future__ import annotations

import json
from pathlib import Path

from repoproof.domain.models import sha256_bytes

# 代际标签。E0 = 当前执行器;上任何一步就自动离开 E0(见 exec_generation)。
E0 = "E0"

# 发次路径上的代码根。scripts/ 是闸门与分析工具,不参与发次;docs/ tests/
# 更不参与。只有这一棵树的内容变化才构成"换了被测系统"。
_EXEC_ROOT = ("src", "repoproof")

# E0 的三条特征:全历史重发、无 spill、单 bash 无 editor。
_E0_CONTEXT_POLICY = "full-history-resend"
_E0_TOOLS = ("bash",)


def _hash(obj: dict) -> str:
    """稳定哈希:排序键 + 紧凑分隔符。不含时间、路径、插入序。"""
    return sha256_bytes(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False).encode())[:16]


def exec_fingerprint(repo: Path) -> str:
    """发次路径上的代码内容哈希。只走 `src/repoproof/**/*.py`。

    按 (相对路径, 内容哈希) 排序后整体再哈希 —— 与文件系统枚举顺序无关,
    与绝对路径无关,故同一份代码在任何机器上算出同一个值。"""
    root = repo.joinpath(*_EXEC_ROOT)
    if not root.is_dir():
        return _hash({"missing": "/".join(_EXEC_ROOT)})
    items = []
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        items.append([p.relative_to(root).as_posix(),
                      sha256_bytes(p.read_bytes())[:16]])
    return _hash({"files": items})


def exec_generation(*, context: dict, tool: dict) -> str:
    """代际标签,**从内容推导**。

    不接受调用方声明 —— 上了 spill 却忘了改标签,E0 与 E1 的数据就会混进
    同一个池子,而"E0/E1 永不互比"是硬规则(§2 规则 1)。标签里带上是哪
    一步带来的差异,便于批报直接引用。"""
    steps = []
    if context.get("spill_threshold_chars") or context.get("prune_policy"):
        steps.append("S2")
    if tool.get("persistent_shell") or tool.get("repeat_guard"):
        steps.append("S3")
    tools = tuple(tool.get("tools") or _E0_TOOLS)
    if tools != _E0_TOOLS:
        steps.append("S4")
    if context.get("contract_capsule") or context.get("requirement_state"):
        steps.append("S5")
    if context.get("policy", _E0_CONTEXT_POLICY) != _E0_CONTEXT_POLICY and "S2" not in steps:
        steps.append("S2")
    if not steps:
        return E0
    return "E1-" + "+".join(sorted(set(steps)))


def profile_hashes(*, tool: dict, context: dict, budget: dict,
                   repo: Path | None = None) -> dict:
    """四面里本模块负责的三面 + 指纹 + 代际,一次给全。

    provider 面不在这里 —— 它由 provider_gate 在 preflight 时算好并冻结,
    真实发次必须绑定同一个 hash(那是 Gate 4B 的既有约束,不动它)。"""
    out = {
        "tool_profile_hash": _hash(tool),
        "context_profile_hash": _hash(context),
        "budget_profile_hash": _hash(budget),
        "exec_generation": exec_generation(context=context, tool=tool),
    }
    if repo is not None:
        out["exec_fingerprint"] = exec_fingerprint(repo)
    return out


# ---------------------------------------------------------------- 语义分面
# 2026-08-14(用户指令):S1 的 `exec_fingerprint` 把整个 `src/repoproof/**`
# 当成"执行器",于是修一个冒烟脚本、收窄一个扫描边界,都会让全部历史发次
# **跨代失配**。保守,但那种失配没有信息量。
#
# 改按**语义所有权**分面:归属由"谁拥有这段语义"决定,不由目录决定 ——
# `agents/` 下既有执行语义(context_projector)也有纯量具(profiles 自己)。
#
# 判定 executor_semantics 的唯一标准:**它是否改变模型可见内容、工具行为、
# 命令执行或运行预算**。改了 → 被测系统变了 → 跨代;没改 → 不该跨代。

FACES = ("executor_semantics", "model_profile", "verifier", "instrumentation")

# 精确路径归属(前缀匹配,长者优先)。新增模块必须登记 —— 判据 F1 会红。
_FACE_MAP: tuple[tuple[str, str], ...] = (
    # ---- 执行语义:改了就是换了被测系统 ----
    ("agents/context_projector.py", "executor_semantics"),   # 模型可见内容
    ("agents/repoproof_env.py", "executor_semantics"),       # 工具行为/命令执行
    ("agents/token_budget.py", "executor_semantics"),        # 运行预算
    ("agents/backend.py", "executor_semantics"),             # agent 循环
    ("harness/budget.py", "executor_semantics"),
    ("harness/policy.py", "executor_semantics"),             # 哪些命令被拒
    ("harness/prompt_manifest.py", "executor_semantics"),    # 模型可见提示
    ("harness/coverage_ledger.py", "executor_semantics"),    # 模型可见状态
    ("runner/", "executor_semantics"),                       # 编排与轮次
    ("execution/", "executor_semantics"),                    # 命令怎么落地
    ("adoption/repair/", "executor_semantics"),              # 反馈包内容
    ("adoption/intent/", "executor_semantics"),
    ("adoption/planning/", "executor_semantics"),
    # ---- 模型面 ----
    ("agents/provider_gate.py", "model_profile"),
    # ---- 验证面:独立验证与完整性扫描 ----
    ("verification/", "verifier"),
    ("harness/oracle_guard.py", "verifier"),
    ("harness/host_guard.py", "verifier"),
    ("harness/postflight.py", "verifier"),
    ("harness/host_snapshot.py", "verifier"),
    ("harness/adaptation.py", "verifier"),
    ("harness/contract_adequacy.py", "verifier"),
    ("harness/controls_battery.py", "verifier"),
    ("harness/task_package.py", "verifier"),
    ("harness/requirement_spec.py", "verifier"),
    ("harness/wheelhouse.py", "verifier"),
    ("harness/host_task.py", "verifier"),
    ("probes/", "verifier"),
    ("adoption/admission/", "verifier"),
    ("adoption/analysis/", "verifier"),
    ("adoption/assembly/", "verifier"),
    ("adoption/delivery/", "verifier"),                      # apply/rollback 完整性
    # ---- 量具面:改它**不改变被测系统** ----
    ("agents/profiles.py", "instrumentation"),               # 指纹自己
    ("agents/fake_model.py", "instrumentation"),             # 冒烟脚本
    ("harness/trace.py", "instrumentation"),                 # 记账
    ("harness/artifacts.py", "instrumentation"),
    ("persistence/", "instrumentation"),
    ("domain/", "instrumentation"),
    ("ui/", "instrumentation"),
    ("cli.py", "instrumentation"),
    ("__init__.py", "instrumentation"),
    ("agents/__init__.py", "instrumentation"),
    ("adoption/__init__.py", "instrumentation"),   # 纯命名空间,无语义
    ("harness/__init__.py", "instrumentation"),
)

# 分析口径版本。改变**统计定义**(而非代码)时人工递增,例如换掉
# "重复输入"的算法、改变能力分母的划分规则。
ANALYSIS_SCHEMA_VERSION = 1


def face_of(rel_path: str) -> str | None:
    """模块的语义归属。未登记返回 None —— 判据 F1 会把它揪出来。"""
    best: tuple[int, str] | None = None
    for prefix, face in _FACE_MAP:
        if rel_path == prefix or rel_path.startswith(prefix):
            if best is None or len(prefix) > best[0]:
                best = (len(prefix), face)
    return best[1] if best else None


def semantic_fingerprints(repo: Path) -> dict:
    """按语义分面各算一个内容指纹 + 分析口径版本号。

    与 `exec_fingerprint()` 并存:后者是 S1 留下的粗粒度值,历史发次绑定
    着它,**不追溯改写**(判据 F5)。新发次两个都记。"""
    root = repo.joinpath(*_EXEC_ROOT)
    buckets: dict[str, list] = {f: [] for f in FACES}
    if root.is_dir():
        for p in sorted(root.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            rel = p.relative_to(root).as_posix()
            face = face_of(rel)
            if face:
                buckets[face].append([rel, sha256_bytes(p.read_bytes())[:16]])
    out = {f"{f}_fingerprint": _hash({"files": buckets[f]}) for f in FACES}
    out["analysis_schema_version"] = ANALYSIS_SCHEMA_VERSION
    return out


def comparable_for(a: dict, b: dict, *, faces: tuple[str, ...]) -> bool:
    """两发能否做严格 A/B —— **只看相关面**(判据 F4)。

    要求全部面逐字节相同,会让"修个错别字"作废整批历史;那种保守没有
    信息量,只有摩擦。"""
    return all(a.get(f"{f}_fingerprint") == b.get(f"{f}_fingerprint") for f in faces)
