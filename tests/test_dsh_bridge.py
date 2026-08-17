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
    bridge_budget,
    composition_fingerprint,
    fidelity_verdict,
    treatment_fidelity,
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
    """键集**恰好**九枚(少一枚 = M-DSH-14 的指纹缺字段),三缺省逐字入指纹。"""
    fp = composition_fingerprint(_runtime_root(tmp_path), model="deepseek-v4-pro")
    assert set(fp) == {
        "backend_id", "runtime_profile_id", "sdk_version", "runtime_bin_version",
        "cordis_sha256", "model", "system_prompt", "max_tokens", "reasoning_effort",
    }
    assert fp["backend_id"] == BACKEND_ID == "dsh"
    assert fp["runtime_profile_id"] == "rt-dsh-minimal-0.1.0rc6-v1"
    assert fp["sdk_version"] == fp["runtime_bin_version"] == "0.1.0rc6"
    assert fp["system_prompt"] == DSH_SYSTEM_PROMPT \
        == "You are a helpful software engineer assistant."
    assert fp["max_tokens"] == DSH_MAX_TOKENS == 256000
    assert fp["reasoning_effort"] == DSH_REASONING_EFFORT == "high"
    assert fp["cordis_sha256"] == hashlib.sha256(
        (_runtime_root(tmp_path / "again") / "config" / "mini.cordis.yml")
        .read_bytes()).hexdigest()


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
