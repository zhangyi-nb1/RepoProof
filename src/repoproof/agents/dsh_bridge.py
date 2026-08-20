"""B-dsh 桥接的裁决面配件(DSH 阶段 8):预算映射 · 组合指纹 · 送达判读。

三件都跑在**裁决面**(host runner),不进 worker:发次前映射预算、算组合
指纹,发次后判 treatment fidelity。对应报告 §17.2 的批层变异面:

    M-DSH-14  指纹缺字段        → `composition_fingerprint` 的键集钉死
    M-DSH-15  两臂预算不等      → `bridge_budget` 的等总额映射钉死
    M-DSH-16  未送达仍计治疗效应 → `treatment_fidelity` 九项判读钉死
    M-DSH-13  DSH 发次计入能力池 → 执法点**不在这里**,在
              bench_records.classify_runs 的 backend 第三锁(与 held-out
              oracle 两道锁同款结构:自述不能自证)

**判读律(报告 §17.3)**:九项里任何一项缺失 = 该发次
TREATMENT_NOT_DELIVERED,只能读作"治疗未送达",**不得读作 H0/H1 无差异**
—— 差异问题只在送达的发次上问。送达率 < 80% 即停批修 instrument,
新代际重跑,不回填。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from repoproof.agents.dsh_backend import DshBudget

BACKEND_ID = "dsh"

# 上游协议真身(GPT×DSH,2026-08-20)。runtime 永远说 deepseek 线;它对面
# 站的是谁必须进指纹 —— 换上游 = 换被测组合,台账列不许猜(M-DSH-17 同律)。
UPSTREAM_DEEPSEEK = "deepseek-native"
UPSTREAM_GPT_SHIM = "openai-compatible+dsh_gpt_shim"


def upstream_protocol_for_provider(ptype: str) -> str:
    """provider 通道 → dsh 臂上游协议真身(准入单一事实源,M92c 面)。

    - deepseek-native:runtime 直连 deepseek 端点(DQ/E1 既证组合);
    - openai-compatible:必须经 dsh_gpt_shim 回环转译(runtime 不会说
      openai 方言;直连会静默变成另一个未声明的组合)。
    其余通道拒绝 —— 不猜、不降级。
    """
    if ptype == "deepseek-native":
        return UPSTREAM_DEEPSEEK
    if ptype == "openai-compatible":
        return UPSTREAM_GPT_SHIM
    raise ValueError(
        f"B-dsh 桥接臂不认识 provider 通道 {ptype!r} —— 上游真身无从声明,"
        "拒绝把未知组合记进台账")

# 组合三缺省(指导报告钉进预注册的值;fingerprint 必含,B3 钉键集)。
# 这些是 DSH minimal 组合的**有效值**声明 —— reasoning_effort 是 SDK
# 0.1.0rc6 的内部缺省,我们的 config 面设不了它,声明进指纹的意义是:
# 换 SDK 版本(缺省可能变)必然换 sdk_version,指纹跟着变,批不可混。
DSH_SYSTEM_PROMPT = "You are a helpful software engineer assistant."
DSH_MAX_TOKENS = 256000
DSH_REASONING_EFFORT = "high"

# C8 实测(2026-08-17):HTTP 500 → 恰 2 次重试,每逻辑请求至多 3 次物理
# POST。attempts 轴按这个系数从 logical 轴派生,不另设自由参数。
RETRY_ATTEMPT_FACTOR = 3


def bridge_budget(hb) -> DshBudget:
    """HostBudgets(H0 臂的预算源)→ DshBudget,**等总额**映射(M-DSH-15 面)。

    四条共享轴逐一映射:模型调用数→logical_requests、双 token 轴原值、
    墙钟分→秒。attempts 轴 = logical × RETRY_ATTEMPT_FACTOR(实测系数,
    不是新预算)。max_commands / patch 轴不映射:patch 上限在裁决面
    (Completion Gate)执法,天然臂中立;命令数是 mini-swe 环的内部
    机制,DSH 侧的等价约束就是请求数轴。

    只接受 semantics="total":等总额是臂间同一性的一半,per_round 语义
    下"总额相等"无从定义,直接拒绝而不是猜。多轮切分(若 max_rounds>1)
    是 runner 的责任 —— 本函数只承诺映射后的**总额**与 H0 臂逐轴相等。
    """
    semantics = getattr(hb, "semantics", "total")
    if semantics != "total":
        raise ValueError(
            f"bridge_budget 只接受 semantics='total'(实得 {semantics!r})—— "
            "等总额是 H0/H1 臂间同一性的一半,per_round 下没有'总额相等'可言")
    return DshBudget(
        max_wall_seconds=hb.max_wall_time_minutes * 60.0,
        max_logical_requests=hb.max_model_calls,
        max_llm_attempts=hb.max_model_calls * RETRY_ATTEMPT_FACTOR,
        max_input_tokens=hb.max_input_tokens_total,
        max_output_tokens=hb.max_output_tokens_total,
    )


# 封存 runtime 的缺省落点(阶段 1 供应链固化的产物;runtime_manifest.json
# 是路径与版本的唯一权威,本模块不猜文件名)。
DEFAULT_RUNTIME_ROOT = Path.home() / "RepoProofRuntimes" / "rt-dsh-minimal-0.1.0rc6-v1"


def _manifest_and_cordis(root: Path) -> tuple[dict, str]:
    manifest = json.loads((root / "runtime_manifest.json").read_text(encoding="utf-8"))
    pins: dict[str, str] = manifest["extras"]["pins"]
    cordis_keys = [k for k in pins if k.endswith(".cordis.yml")]
    if len(cordis_keys) != 1:
        raise ValueError(f"封存清单里 cordis 钉不是恰好一条:{cordis_keys}")
    return manifest, cordis_keys[0]


def runtime_paths(runtime_root: str | Path = DEFAULT_RUNTIME_ROOT) -> tuple[Path, Path]:
    """封存根 → (worker_python, cordis)。全按清单现物解析,不硬编码文件名。"""
    root = Path(runtime_root)
    manifest, cordis_rel = _manifest_and_cordis(root)
    return Path(manifest["python_executable"]), root / cordis_rel


def composition_fingerprint(runtime_root: str | Path, *, model: str,
                            system_prompt: str = DSH_SYSTEM_PROMPT,
                            max_tokens: int = DSH_MAX_TOKENS,
                            reasoning_effort: str = DSH_REASONING_EFFORT,
                            upstream_protocol: str = UPSTREAM_DEEPSEEK) -> dict:
    """DSH 组合的**有效面指纹**(M-DSH-14 面),供 exec profile 哈希与预注册冻结。

    版本与 cordis 哈希取自封存清单 `runtime_manifest.json`(供应链权威),
    且 cordis **现物重算** sha256 与清单比对 —— 不一致直接炸:指纹只认
    现场,不认清单的一面之词。
    """
    root = Path(runtime_root)
    manifest, cordis_rel = _manifest_and_cordis(root)
    versions = {p["distribution"]: p["version"] for p in manifest["pinned"]}
    pins: dict[str, str] = manifest["extras"]["pins"]
    actual = hashlib.sha256((root / cordis_rel).read_bytes()).hexdigest()
    if actual != pins[cordis_rel]:
        raise ValueError(
            f"cordis 现物与封存清单不符:{cordis_rel} 现算 {actual[:12]}… ≠ "
            f"清单 {pins[cordis_rel][:12]}… —— 封存被动过,拒绝出指纹")
    return {
        "backend_id": BACKEND_ID,
        "runtime_profile_id": manifest["profile_id"],
        "sdk_version": versions["deepseek-harness-sdk"],
        "runtime_bin_version": versions["deepseek-harness-runtime-bin"],
        "cordis_sha256": actual,
        "model": model,
        "system_prompt": system_prompt,
        "max_tokens": max_tokens,
        "reasoning_effort": reasoning_effort,
        # 第 10 键(2026-08-20):runtime 对面站的是谁。GPT 组合若在这里
        # 扮成 deepseek,DQ 的 qualified 背书会被静默冒领(M92a 面)。
        "upstream_protocol": upstream_protocol,
    }


# ---------------------------------------------------------- treatment fidelity
#
# 报告 §17.3 的九项送达证据。命名编号进缺失文案,批报按编号点名。

FIDELITY_ITEMS = (
    "①backend 身份", "②封存版本", "③组合一致", "④工具面白名单",
    "⑤无扩展面", "⑥runtime 事件存在", "⑦会话唯一", "⑧预算生效",
    "⑨workspace 出处",
)

TREATMENT_NOT_DELIVERED = "TREATMENT_NOT_DELIVERED"

# 严格最小组合的工具面(指导报告:Bash + 编辑器,不多不少)
ALLOWED_TOOLS = frozenset({"bash", "str_replace_editor"})

# 严格最小组合不许出现的扩展面(首轮无 compaction/子代理/联网/技能)
FORBIDDEN_EVENT_PREFIXES = ("compaction/", "subagent/", "web/", "skill/")


def treatment_fidelity(*, report, fingerprint: dict, expected_fingerprint: dict,
                       budget: DshBudget, host_budgets,
                       seen_session_ids, job: dict,
                       expected_workspace: str | Path) -> list[str]:
    """九项逐一验,返回**缺失清单**(空 = 送达)。M-DSH-16 的判读面。

    输入全是裁决面自己手里的东西:report 是父侧 watchdog 的回执(可信
    events 汇),fingerprint/budget/job 是我们发出去的,expected_* 是
    预注册冻结值 —— 没有一项来自 worker 的自述。
    """
    missing: list[str] = []
    fp, exp = fingerprint, expected_fingerprint

    if fp.get("backend_id") != BACKEND_ID:
        missing.append(f"①backend_id 不是 {BACKEND_ID!r}:{fp.get('backend_id')!r}")
    for k in ("sdk_version", "runtime_bin_version"):
        if fp.get(k) != exp.get(k):
            missing.append(f"②{k} 与预注册钉不符:{fp.get(k)!r} ≠ {exp.get(k)!r}")
    diff = sorted(k for k in set(fp) | set(exp) if fp.get(k) != exp.get(k))
    if diff:
        missing.append(f"③组合指纹与预注册冻结值不一致:{diff}")
    tools = {r.get("tool") for r in report.trace.records
             if r.get("type") == "tool/call"}
    extra_tools = sorted(str(t) for t in tools if t not in ALLOWED_TOOLS)
    if extra_tools:
        missing.append(f"④出现白名单外工具:{extra_tools}")
    seen_ext = sorted({str(r.get("type")) for r in report.trace.records
                       if any(str(r.get("type", "")).startswith(p)
                              for p in FORBIDDEN_EVENT_PREFIXES)})
    if seen_ext:
        missing.append(f"⑤出现扩展面事件:{seen_ext}")
    if report.trace.counters.get("session_events", 0) < 1:
        missing.append("⑥可信事件汇里没有任何 DSH runtime 事件 —— 治疗未发生")
    sid = report.trace.session_id or ((report.result or {}).get("session_id"))
    if not sid:
        missing.append("⑦发次没有 session_id —— 无从证明会话独立")
    elif sid in seen_session_ids:
        missing.append(f"⑦session_id 重复:{sid} 本批已出现过")
    if budget != bridge_budget(host_budgets):
        missing.append("⑧下发预算不等于等总额映射值 —— 两臂预算同一性破")
    if Path(job["workspace"]).resolve() != Path(expected_workspace).resolve():
        missing.append(f"⑨workspace 出处不对:{job['workspace']} ≠ {expected_workspace}")
    return missing


def fidelity_verdict(missing: list[str]) -> str | None:
    """缺任一项 → TREATMENT_NOT_DELIVERED;None = 送达。

    判读律再说一遍:TREATMENT_NOT_DELIVERED 的发次**不得读作 H0/H1
    无差异** —— 治疗没送到,臂间比较对它不存在。
    """
    return TREATMENT_NOT_DELIVERED if missing else None
