"""B-dsh 桥接件的钉(DSH 阶段 8,报告 §17.2/§17.3)。

- B1/B2 等总额预算映射(M88c = M-DSH-15)
- B3/B3b 组合指纹键集·三缺省·现物哈希复核(M88b = M-DSH-14)
- B4/B5 treatment fidelity 九项与判读律(M88d = M-DSH-16)
- B6 backend 第三锁:DSH 发次永不入能力池/held-out(M88a = M-DSH-13)

全部钉都是**密闭**的(合成 runtime 清单 + 合成台账,不碰封存 runtime、
不起 worker)—— 变异闸门在任何环境都跑得动,skip 不会放走变异体。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from repoproof.agents.dsh_backend import DshBudget, DshRunReport
from repoproof.agents.dsh_bridge import (
    ALLOWED_TOOLS,
    BACKEND_ID,
    DSH_MAX_TOKENS,
    DSH_REASONING_EFFORT,
    DSH_SYSTEM_PROMPT,
    RETRY_ATTEMPT_FACTOR,
    TREATMENT_NOT_DELIVERED,
    UPSTREAM_DEEPSEEK,
    UPSTREAM_GPT_SHIM,
    bridge_budget,
    composition_fingerprint,
    fidelity_verdict,
    treatment_fidelity,
    upstream_protocol_for_provider,
)
from repoproof.agents.dsh_events import DshTrace
from repoproof.persistence.bench_records import classify_runs


class _HB:
    """HostBudgets 的鸭型替身(桥不 import runner 层,测试也不必)。"""
    semantics = "total"
    max_rounds = 2
    max_model_calls = 40
    max_commands = 120
    max_patch_files = 8
    max_patch_lines = 800
    max_wall_time_minutes = 30
    max_input_tokens_total = 900_000
    max_output_tokens_total = 120_000


def test_b1_budget_mapping_is_equal_total() -> None:
    """四条共享轴逐轴恒等:分→秒、调用数→logical、双 token 原值;
    attempts = logical × 实测重试系数(不是新预算)。"""
    got = bridge_budget(_HB())
    assert got == DshBudget(
        max_wall_seconds=1800.0,
        max_logical_requests=40,
        max_llm_attempts=40 * RETRY_ATTEMPT_FACTOR,
        max_input_tokens=900_000,
        max_output_tokens=120_000,
    )


def test_b2_per_round_semantics_refused() -> None:
    hb = _HB()
    hb.semantics = "per_round"
    with pytest.raises(ValueError, match="等总额"):
        bridge_budget(hb)


# ---------------------------------------------------------------- 组合指纹

def _runtime_root(tmp: Path, *, break_cordis: bool = False) -> Path:
    """合成封存根:manifest + cordis,哈希自洽(break_cordis=True 时故意不符)。"""
    root = tmp / "rt"
    (root / "config").mkdir(parents=True)
    cordis = root / "config" / "mini.cordis.yml"
    cordis.write_text("tools:\n  - bash\n  - str_replace_editor\n", encoding="utf-8")
    digest = hashlib.sha256(cordis.read_bytes()).hexdigest()
    if break_cordis:
        cordis.write_text("tools:\n  - bash\n  - web_search\n", encoding="utf-8")
    manifest = {
        "profile_id": "rt-dsh-minimal-0.1.0rc6-v1",
        "pinned": [
            {"distribution": "deepseek-harness-sdk", "version": "0.1.0rc6"},
            {"distribution": "deepseek-harness-runtime-bin", "version": "0.1.0rc6"},
        ],
        "extras": {"pins": {"config/mini.cordis.yml": digest}},
    }
    (root / "runtime_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return root


def test_b3_fingerprint_keys_and_composition_defaults(tmp_path: Path) -> None:
    """键集**恰好**十枚(少一枚 = M-DSH-14 的指纹缺字段),三缺省逐字入指纹;
    第 10 键 upstream_protocol(2026-08-20)缺省 = deepseek 直连。"""
    fp = composition_fingerprint(_runtime_root(tmp_path), model="deepseek-v4-pro")
    assert set(fp) == {
        "backend_id", "runtime_profile_id", "sdk_version", "runtime_bin_version",
        "cordis_sha256", "model", "system_prompt", "max_tokens", "reasoning_effort",
        "upstream_protocol",
    }
    assert fp["backend_id"] == BACKEND_ID == "dsh"
    assert fp["runtime_profile_id"] == "rt-dsh-minimal-0.1.0rc6-v1"
    assert fp["sdk_version"] == fp["runtime_bin_version"] == "0.1.0rc6"
    assert fp["system_prompt"] == DSH_SYSTEM_PROMPT \
        == "You are a helpful software engineer assistant."
    assert fp["max_tokens"] == DSH_MAX_TOKENS == 256000
    assert fp["reasoning_effort"] == DSH_REASONING_EFFORT == "high"
    assert fp["upstream_protocol"] == UPSTREAM_DEEPSEEK == "deepseek-native"
    assert fp["cordis_sha256"] == hashlib.sha256(
        (_runtime_root(tmp_path / "again") / "config" / "mini.cordis.yml")
        .read_bytes()).hexdigest()


def test_b3c_fingerprint_records_upstream_truth_not_a_disguise(
        tmp_path: Path) -> None:
    """B3c(M92a 面):upstream_protocol 参数必须逐字进指纹 —— GPT 组合若在
    指纹里扮成 deepseek,DQ 的 qualified 背书会被静默冒领。"""
    fp = composition_fingerprint(_runtime_root(tmp_path), model="gpt-5.5",
                                 upstream_protocol=UPSTREAM_GPT_SHIM)
    assert fp["upstream_protocol"] == UPSTREAM_GPT_SHIM \
        == "openai-compatible+dsh_gpt_shim"
    assert fp["model"] == "gpt-5.5"


def test_b7_upstream_protocol_for_provider_single_source(
) -> None:
    """B7(M92c 面):通道→上游真身的单源判定 —— openai-compatible 必须
    映到 shim 协议(直连会静默变成未声明组合);未知通道拒绝不猜。"""
    assert upstream_protocol_for_provider("deepseek-native") == UPSTREAM_DEEPSEEK
    assert upstream_protocol_for_provider("openai-compatible") == UPSTREAM_GPT_SHIM
    with pytest.raises(ValueError, match="不认识 provider 通道"):
        upstream_protocol_for_provider("anthropic")


def test_b3b_fingerprint_refuses_tampered_cordis(tmp_path: Path) -> None:
    """指纹只认现物:cordis 与封存清单不符 → 拒绝出指纹,不出降级指纹。"""
    root = _runtime_root(tmp_path, break_cordis=True)
    with pytest.raises(ValueError, match="封存被动过"):
        composition_fingerprint(root, model="deepseek-v4-pro")


# ---------------------------------------------------------------- fidelity 九项

def _trace(**over) -> DshTrace:
    t = DshTrace(session_id="sess-1")
    t.records = [{"kind": "event", "seq": 3, "type": "tool/call",
                  "turn": 1, "tool": "bash"}]
    t.counters = {"session_events": 5}
    for k, v in over.items():
        setattr(t, k, v)
    return t


def _report(trace: DshTrace | None = None, result: dict | None = None) -> DshRunReport:
    return DshRunReport(
        exit_code=0, attribution="ok",
        result={"session_id": "sess-1"} if result is None else result,
        trace=trace if trace is not None else _trace())


def _fidelity(tmp: Path, **over) -> list[str]:
    root = _runtime_root(tmp) if not (tmp / "rt").exists() else tmp / "rt"
    fp = composition_fingerprint(root, model="deepseek-v4-pro")
    ws = tmp / "ws"
    ws.mkdir(exist_ok=True)
    kw = dict(report=_report(), fingerprint=fp, expected_fingerprint=dict(fp),
              budget=bridge_budget(_HB()), host_budgets=_HB(),
              seen_session_ids=set(), job={"workspace": str(ws)},
              expected_workspace=ws)
    kw.update(over)
    return treatment_fidelity(**kw)


def test_b4_fidelity_all_delivered(tmp_path: Path) -> None:
    missing = _fidelity(tmp_path)
    assert missing == []
    assert fidelity_verdict(missing) is None


def test_b5_each_degradation_is_named_and_not_readable_as_no_difference(
        tmp_path: Path) -> None:
    """九项逐一降级 → 各自被点名;判读只能是 TREATMENT_NOT_DELIVERED。"""
    root = _runtime_root(tmp_path)
    fp = composition_fingerprint(root, model="deepseek-v4-pro")

    cases: list[tuple[str, dict]] = [
        ("①", {"fingerprint": dict(fp, backend_id="mini-swe")}),
        ("②", {"fingerprint": dict(fp, sdk_version="0.2.0")}),
        ("③", {"expected_fingerprint": dict(fp, model="deepseek-v4-flash")}),
        ("④", {"report": _report(trace=_trace(records=[
            {"kind": "event", "seq": 3, "type": "tool/call",
             "turn": 1, "tool": "web_search"}]))}),
        ("⑤", {"report": _report(trace=_trace(records=[
            {"kind": "event", "seq": 3, "type": "subagent/spawn", "turn": 1}]))}),
        ("⑥", {"report": _report(trace=_trace(counters={"session_events": 0}))}),
        ("⑦", {"report": _report(trace=_trace(session_id=None),
                                 result={"session_id": None})}),
        ("⑦", {"seen_session_ids": {"sess-1"}}),
        ("⑧", {"budget": DshBudget(max_wall_seconds=1.0)}),
        ("⑨", {"job": {"workspace": str(tmp_path / "elsewhere")}}),
    ]
    for marker, over in cases:
        missing = _fidelity(tmp_path, **over)
        assert any(m.startswith(marker) for m in missing), (marker, over, missing)
        # 判读律:缺项只有一种读法 —— 治疗未送达,不是"两臂无差异"
        assert fidelity_verdict(missing) == TREATMENT_NOT_DELIVERED

    assert "web_search" not in ALLOWED_TOOLS  # 白名单恰 bash+编辑器
    assert ALLOWED_TOOLS == {"bash", "str_replace_editor"}


# ---------------------------------------------------------------- backend 第三锁

def test_b6_backend_third_lock_dsh_rows_never_count(tmp_path: Path) -> None:
    """M-DSH-13:backend_id=dsh 的行,分类旁挂把能力/held-out 全说成 true
    也不算(自述不能自证);历史行(缺列)照旧按基线处理。"""
    v2 = tmp_path / "benchmarks" / "v2"
    v2.mkdir(parents=True)
    rows = [
        {"run_id": "r-dsh-1", "verdict": "PASS", "backend_id": "dsh", "host_id": "h"},
        {"run_id": "r-old-1", "verdict": "PASS", "host_id": "h"},
    ]
    (v2 / "runs.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")
    cls = {"run_id": "r-dsh-1",
           "counts_toward_model_capability": True,
           "counts_toward_heldout_benchmark": True,
           "oracle_authorship": "UPSTREAM_OWN_TEST_SUITE",
           "host_modification_mode": "HOLLOW_ONLY"}
    (v2 / "run_classifications.jsonl").write_text(
        json.dumps(cls, ensure_ascii=False) + "\n", encoding="utf-8")

    out = {r["run_id"]: r for r in classify_runs(tmp_path)}
    assert out["r-dsh-1"]["counts_toward_model_capability"] is False
    assert out["r-dsh-1"]["counts_toward_heldout_benchmark"] is False
    assert out["r-old-1"]["counts_toward_model_capability"] is True


# ---------------------------------------------------------------- 层 2 集成缝

_RT_ROOT = Path.home() / "RepoProofRuntimes" / "rt-dsh-minimal-0.1.0rc6-v1"

needs_runtime = pytest.mark.skipif(
    not (_RT_ROOT / ".venv" / "bin" / "python").exists(),
    reason="封存 DSH runtime 不在本机")


@needs_runtime
def test_r1_run_dsh_round_end_to_end_over_fake_endpoint(tmp_path: Path) -> None:
    """runner 缝的活钉:模块级 run_dsh_round 走真 worker 环 + 脚本化假端点
    (127.0.0.1,假 key 字面量,不出网)。编辑器写盘可收割、回执适配纪律
    (calls=logical、commands=bash 计数、cost=UNKNOWN)、指纹/会话齐全。"""
    from repoproof.agents.dsh_fake_provider import FakeDeepSeekProvider
    from repoproof.runner.host_guided import run_dsh_round

    ws = tmp_path / "ws"
    ws.mkdir()
    out_file = str(ws / "out.txt")

    class _Total(_HB):
        max_wall_time_minutes = 3

    with FakeDeepSeekProvider([
        {"tool": "str_replace_editor",
         "args": {"command": "create", "path": out_file, "file_text": "hola\n"}},
        {"text": "done"},
    ]) as fake:
        result, info = run_dsh_round(
            workspace=ws, side_dir=tmp_path / "side", prompt="写 out.txt。",
            budgets=_Total(), model_name="deepseek-v4-flash",
            api_base=fake.base_url, api_key="sk-canary-invalid-0000",
            runtime_root=_RT_ROOT, request_timeout_s=60.0)

    assert (ws / "out.txt").read_text(encoding="utf-8") == "hola\n"
    assert result.exit_status == "submitted"
    assert result.n_model_calls == 2          # 周期计数(E5):两次走完的调用
    assert result.commands_used == 0          # 无 bash,只有编辑器
    assert result.cost == "UNKNOWN"           # DSH 无费率读数,绝不写 0 冒充
    assert result.denied_count == 0
    assert info["attribution"] == "ok"
    assert info["session_id"]
    assert info["usage"] == {"input_tokens": 24, "output_tokens": 10}
    assert info["fingerprint"]["backend_id"] == "dsh"
    assert Path(info["events_path"]).exists()
    assert info["trace_problems"] == [] and info["selfcheck_problems"] == []
    # fidelity 九项对着真回执全绿(⑧ 用同一份 HostBudgets 重算恒等)
    missing = treatment_fidelity(
        report=info["report"], fingerprint=info["fingerprint"],
        expected_fingerprint=dict(info["fingerprint"]),
        budget=info["budget"], host_budgets=_Total(),
        seen_session_ids=set(), job=info["job"], expected_workspace=ws)
    assert missing == []


# ------------------------------------------------- R2:台账回执块(装配面)
#
# DQ-SDK-1 发 1 实证(2026-08-18):agent 环、验证、oracle 全走完,记录
# 装配在 _finish 引 run() 局部名 NameError,发次没落账。回执块自此独立
# 成签名传参的纯函数 —— 这两条钉形状与判读来源。

def test_r2_dsh_receipt_block_delivered_shape() -> None:
    from repoproof.runner.host_guided import dsh_receipt_block

    info = {"attribution": "ok", "session_id": "s-1",
            "counters": {"logical_requests": 7},
            "usage": {"input_tokens": 24, "output_tokens": 10},
            "fidelity_missing": []}
    out = dsh_receipt_block([], [info])
    assert out == {
        "fidelity_missing": [],
        "fidelity_verdict": "DELIVERED",
        "rounds": [{"attribution": "ok", "session_id": "s-1",
                    "logical_requests": 7,
                    "usage": {"input_tokens": 24, "output_tokens": 10},
                    "fidelity_missing": []}],
    }


# ---------------------------------------------- P1-d:shim 用量进回执面(仪器)
#
# V2GEN-GPT-EXT-1 发 5 实证(2026-08-21):R6 前置预算闸拒发了 3 次、
# exit_status = dsh:budget_refused:input_tokens,而 report.json 与台账
# rounds 块里**一个字都没有** —— 报告面据此把"没查到"写成了"没发生"。
# 病灶是仪器:shim 形状记录只活在 runtime 局部,没进回执。
#   ①  拒发计数与上游用量进 rounds;
#   ②  **不造零**:上游没报 cached_tokens 就不落该键(M69c 同律),
#       deepseek 直连(无 shim)返回空 dict 而不是一排 0。

def test_p1d_shim_usage_totals_counts_dispatch_and_refusal() -> None:
    from repoproof.runner.host_guided import shim_usage_totals

    out = shim_usage_totals([
        {"usage": {"prompt_tokens": 100, "cached_tokens": 90}},
        {"refused_pre_budget": True},
        {"usage": {"prompt_tokens": 50, "cached_tokens": 40}},
        {"refused_pre_budget": True},
    ])
    assert out == {"dispatched": 2, "refused_pre_budget": 2,
                   "upstream_prompt_tokens": 150, "cached_tokens": 130}


def test_p1d_shim_usage_totals_does_not_manufacture_zeros() -> None:
    from repoproof.runner.host_guided import shim_usage_totals

    assert shim_usage_totals(None) == {}          # 无 shim(直连)= 没量,不是 0
    assert shim_usage_totals([]) == {}
    # 上游没报 cached_tokens → 键缺席,而不是 0("没量"≠"量了是零")
    out = shim_usage_totals([{"usage": {"prompt_tokens": 7}}])
    assert "cached_tokens" not in out and out["upstream_prompt_tokens"] == 7


def test_p1d_receipt_rounds_carry_shim_refusals_when_present() -> None:
    from repoproof.runner.host_guided import dsh_receipt_block

    info = {"attribution": "ok", "session_id": "s-1",
            "counters": {"logical_requests": 2},
            "usage": {"input_tokens": 24, "output_tokens": 10},
            "fidelity_missing": [], "shim_refusals": 3,
            "shim_requests": [{"usage": {"prompt_tokens": 100}},
                              {"refused_pre_budget": True}]}
    rec = dsh_receipt_block([], [info])["rounds"][0]
    assert rec["shim_refusals"] == 3
    assert rec["shim_usage"]["refused_pre_budget"] == 1
    assert rec["shim_usage"]["dispatched"] == 1
    # 无 shim 的发次形状不变(deepseek 直连的既有回执逐键不动)
    plain = dsh_receipt_block([], [{k: v for k, v in info.items()
                                    if k not in ("shim_refusals", "shim_requests")}])
    assert "shim_usage" not in plain["rounds"][0]


def test_r2_dsh_receipt_block_not_delivered_and_verdict_source() -> None:
    """缺项判读必须走 dsh_bridge.fidelity_verdict(M88d 钉那份),
    不许在装配处另写第二套判读。"""
    from repoproof.runner.host_guided import dsh_receipt_block

    out = dsh_receipt_block(["⑥可信事件汇里没有任何 DSH runtime 事件"], [])
    assert out["fidelity_verdict"] == TREATMENT_NOT_DELIVERED
    assert out["rounds"] == []


# ------------------------------------------- R3:台账 runtime_profile_id(挂靠面)
#
# DQ-SDK-1 实证(2026-08-18):dsh 发次的台账列从契约缺省转录成
# rt-inprocess-v1(假话 —— agent 段跑在封存 runtime),而 G6 恰按此列
# 挂靠,晋级判据恒读 0。列与代际标签必须记"实际跑了什么"。

_CONTRACT_TOTAL = Path(__file__).resolve().parents[1] / (
    "benchmarks/v2/tasks/hb1_sqlglot_8042/contract-dsh-total.yaml")


def test_r3_dsh_run_ledger_binds_to_sealed_runtime_profile() -> None:
    from repoproof.runner.host_guided import HostContract, _exec_profile_fields

    contract, _sha = HostContract.load(_CONTRACT_TOTAL)
    comp = {"runtime_profile_id": "rt-dsh-minimal-0.1.0rc6-v1",
            "backend_id": "dsh", "model": "deepseek-v4-pro"}
    out = _exec_profile_fields(contract, None, backend="dsh",
                               backend_composition=comp)
    assert out["runtime_profile_id"] == "rt-dsh-minimal-0.1.0rc6-v1"
    assert out["backend_id"] == "dsh"
    # 代际标签与单列同源:标签串里必须带封存 runtime,而不是契约缺省
    assert "rt-dsh-minimal-0.1.0rc6-v1" in out["exec_generation"]
    assert "rt-inprocess-v1" not in out["exec_generation"]


def test_r3_dsh_without_composition_refuses_to_guess() -> None:
    import pytest

    from repoproof.runner.host_guided import HostContract, _exec_profile_fields

    contract, _sha = HostContract.load(_CONTRACT_TOTAL)
    with pytest.raises(ValueError, match="不许猜"):
        _exec_profile_fields(contract, None, backend="dsh",
                             backend_composition=None)
    # mini-swe 臂行为不变:仍按契约声明落列(历史发次的那条老路)
    out = _exec_profile_fields(contract, None)
    assert out["runtime_profile_id"] == "rt-inprocess-v1"
