"""Gate 8 — scaffold (task init/check), no-model demos, fact-source
consistency. Zero LLM anywhere in this file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repoproof.runner.demo import CASES, demo_list, demo_verify
from repoproof.runner.scaffold import task_check, task_init

REPO = Path(__file__).resolve().parent.parent


def _mini_root(tmp_path: Path) -> Path:
    for d in ("contracts", "oracle", "docs/tasks", "fixtures", "controls"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


# ---- task init ----


def test_init_creates_draft_skeleton(tmp_path: Path) -> None:
    root = _mini_root(tmp_path)
    out = task_init(root, task_id="adopt-demo-lib-v1")
    assert out["ok"] and out["state"] == "DRAFT" and not out["dry_run"]
    for rel in out["files"]:
        assert (root / rel).exists(), rel
    text = (root / "contracts" / "adopt-demo-lib-v1.yaml").read_text()
    assert "TODO" in text  # explicit decisions left to the author

def test_init_dry_run_writes_nothing(tmp_path: Path) -> None:
    root = _mini_root(tmp_path)
    out = task_init(root, task_id="adopt-demo-lib-v1", dry_run=True)
    assert out["ok"] and out["dry_run"]
    assert not (root / "contracts" / "adopt-demo-lib-v1.yaml").exists()
    assert list((root / "oracle").iterdir()) == []


def test_init_refuses_overwrite(tmp_path: Path) -> None:
    root = _mini_root(tmp_path)
    assert task_init(root, task_id="adopt-demo-lib-v1")["ok"]
    again = task_init(root, task_id="adopt-demo-lib-v1")
    assert not again["ok"] and "refusing to overwrite" in again["error"]


def test_init_rejects_bad_task_id(tmp_path: Path) -> None:
    assert not task_init(_mini_root(tmp_path), task_id="Bad Name!")["ok"]


# ---- task check ----


def test_check_fails_on_unresolved_todos(tmp_path: Path) -> None:
    root = _mini_root(tmp_path)
    task_init(root, task_id="adopt-demo-lib-v1")
    out = task_check(root, "adopt-demo-lib-v1")
    assert out["state"] == "INVALID_TASK_SPEC" and not out["ready"]
    assert any("TODO" in g for g in out["gaps"])


def test_check_missing_contract(tmp_path: Path) -> None:
    out = task_check(_mini_root(tmp_path), "nope")
    assert out["state"] == "INVALID_TASK_SPEC"
    assert any("contract missing" in g for g in out["gaps"])


MINI_CONTRACT = """\
task_id: {tid}
source_repo:
  url: https://example.org/lib
  revision: v1.0.0
  resolved_commit: {commit}
  license: MIT
  distribution: demo-lib
target_project:
  kind: consumer_fixture
  path: fixtures/consumer_demo
  package: demo_pkg
  entry_point: run_demo
requirement_spec_file: {tid}.requirements.yaml
capability:
  statement: >
    Adopt demo-lib. {extra}
  output_schema: DemoRecord
environment: {{os: linux, arch: arm64, python: "3.12", cpu_only: true, network_install: true, network_test: false}}
constraints: {{forbidden: [gpu], editable_zones: [adaptation], forbidden_install_extras: []}}
budgets:
  max_agent_steps: 20
  max_wall_time_minutes: 30
  max_command_minutes: 5
  max_semantic_recoveries: 3
  max_same_action: 2
  max_patch_files: 8
  max_patch_lines: 400
  max_input_tokens_total: 400000
  max_output_tokens_total: 40000
  monetary_soft_cap_usd: 5.0
acceptance:
  capability_command: ["pytest", "-q", "/oracle/test_capability.py"]
  regression_command: ["pytest", "-q", "/oracle/test_regression.py"]
  probe_script: demo_probe.py
"""

MINI_SPEC = """\
task_id: {tid}
controls:
  positive: controls/{tid}/positive
  negatives:
    - path: controls/{tid}/negative_nc1
      label: NC1_cheat
      must_fail_nodes: ["test_core"]
requirements:
  - id: core-rule
    owner: {owner}
    severity: HARD
    source_field: capability.statement
    public_text: >
      {public_text}
    examples: ["in -> out"]
    oracle_nodes: ["test_capability::test_core"]
"""


def _write_mini_task(root: Path, tid: str, *, owner: str = "ADAPTER",
                     public_text: str = "The demo capability must round-trip records.",
                     statement_extra: str = "The demo capability must round-trip records.") -> None:
    (root / "contracts" / f"{tid}.yaml").write_text(
        MINI_CONTRACT.format(tid=tid, commit="a" * 40, extra=statement_extra), encoding="utf-8")
    (root / "contracts" / f"{tid}.requirements.yaml").write_text(
        MINI_SPEC.format(tid=tid, owner=owner, public_text=public_text), encoding="utf-8")
    (root / "oracle" / tid).mkdir(parents=True, exist_ok=True)
    (root / "oracle" / tid / "test_capability.py").write_text("def test_core():\n    pass\n", encoding="utf-8")
    (root / "fixtures" / "consumer_demo").mkdir(parents=True, exist_ok=True)


def test_check_flags_missing_owner_enum(tmp_path: Path) -> None:
    root = _mini_root(tmp_path)
    _write_mini_task(root, "adopt-demo-lib-v1", owner="SOMEONE")
    out = task_check(root, "adopt-demo-lib-v1")
    assert not out["ready"] and any("owner" in g for g in out["gaps"])


def test_check_flags_hard_requirement_not_in_prompt(tmp_path: Path) -> None:
    # projection break: contract forgets requirement_spec_file, so the
    # renderer emits no REQUIREMENTS section -> HARD text missing
    root = _mini_root(tmp_path)
    _write_mini_task(root, "adopt-demo-lib-v1",
                     public_text="This exact sentence is nowhere in the statement.",
                     statement_extra="Something else entirely.")
    cpath = root / "contracts" / "adopt-demo-lib-v1.yaml"
    cpath.write_text(cpath.read_text().replace(
        "requirement_spec_file: adopt-demo-lib-v1.requirements.yaml\n", ""), encoding="utf-8")
    out = task_check(root, "adopt-demo-lib-v1")
    assert not out["ready"]
    assert any("hard_public_text_rendered" in g for g in out["gaps"])
    assert any("requirement_spec_file not set" in g for g in out["gaps"])


def test_check_flags_orphan_oracle_node_with_frozen_collection(tmp_path: Path) -> None:
    root = _mini_root(tmp_path)
    _write_mini_task(root, "adopt-demo-lib-v1")
    (root / "contracts" / "adopt-demo-lib-v1.collection.json").write_text(json.dumps({
        "capability_nodes": ["test_capability::test_core", "test_capability::test_unmapped"],
        "regression_nodes": [],
    }), encoding="utf-8")
    out = task_check(root, "adopt-demo-lib-v1")
    assert any("orphan_oracle_nodes" in g for g in out["gaps"])


def test_check_minimal_task_passes_schema_but_blocks_on_controls(tmp_path: Path) -> None:
    root = _mini_root(tmp_path)
    _write_mini_task(root, "adopt-demo-lib-v1")
    out = task_check(root, "adopt-demo-lib-v1")
    # schema-level items are clean; the freeze blockers are controls + collection
    assert not any("contract schema" in g or "requirement spec:" in g for g in out["gaps"])
    assert any("controls:" in g for g in out["gaps"])
    assert out["state"] == "INVALID_TASK_SPEC"


def test_check_ready_prints_existing_freeze_command(tmp_path: Path) -> None:
    root = _mini_root(tmp_path)
    tid = "adopt-demo-lib-v1"
    _write_mini_task(root, tid)
    for sub in ("positive", "negative_nc1"):
        d = root / "controls" / tid / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / "adapter.py").write_text("def run_demo(x):\n    return x\n", encoding="utf-8")
    out = task_check(root, tid)
    assert out["ready"] and out["state"] == "READY_TO_FREEZE", out["gaps"]
    assert out["next"].startswith("repoproof freeze-task --contract")


def test_scaffold_never_touches_existing_tasks_and_calls_no_llm() -> None:
    src = (REPO / "src" / "repoproof" / "runner" / "scaffold.py").read_text(encoding="utf-8")
    for banned in ("litellm", "openai", "provider_gate", "MiniSWE", "requests", "urllib"):
        assert banned not in src, banned
    # refuses to overwrite the real frozen v2 task even if invoked on the repo
    out = task_init(REPO, task_id="adopt-frontmatter-local-ingest-v1-v2", dry_run=False)
    assert not out["ok"] and "refusing to overwrite" in out["error"]


# ---- demos + fact source (read-only over committed evidence) ----


def test_demo_list_has_three_cases() -> None:
    out = demo_list()
    assert {c["case"] for c in out["cases"]} == set(CASES) and out["model_calls"] == 0


@pytest.mark.parametrize("case", ["frontmatter-v2-pass", "chonkie-agent-fail", "bm25-agent-fail"])
def test_demo_verify_recomputes_recorded_verdicts(case: str) -> None:
    out = demo_verify(REPO, case)
    assert out["verdict_recomputation_matches"], out
    assert out["model_calls"] == 0 and out["agent_claim_consulted"] is False
    if case == "frontmatter-v2-pass":
        assert out["recomputed_verdict"] == "PASS_ADAPTED"
        assert out["inputs_to_gate"]["replay_mode"] == "clean_adoption"
    else:
        assert out["recomputed_verdict"] == "FAIL"


def test_benchmark_summary_is_current_and_consistent() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("bbs", REPO / "scripts" / "build_benchmark_summary.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    fresh = mod.build()
    committed = json.loads((REPO / "docs" / "benchmark_summary.json").read_text(encoding="utf-8"))
    assert fresh == committed, "benchmark_summary.json stale — re-run scripts/build_benchmark_summary.py"
    assert committed["totals"]["pass_adapted"] == 1
    assert committed["totals"]["runs_recorded"] == len(committed["runs"]) == 12


def test_public_claims_check_passes() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("cpc", REPO / "scripts" / "check_public_claims.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    assert mod.check() == []
