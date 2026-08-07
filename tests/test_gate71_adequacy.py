"""Gate 7.1 — ContractAdequacyGate + RequirementSpec + prompt projection
+ InputContractGuard. Each sabotage scenario from the gate order must
turn the deterministic gate red BEFORE any agent could start."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from repoproof.domain.models import TaskContract
from repoproof.harness.contract_adequacy import evaluate_adequacy
from repoproof.harness.prompt_manifest import build_prompt_manifest, verify_prompt_manifest
from repoproof.harness.requirement_spec import RequirementSpec, SpecError, load_requirement_spec
from repoproof.runner.agent_run import render_task_prompt

REPO = Path(__file__).resolve().parent.parent
CONTRACT = REPO / "contracts" / "adopt-frontmatter-local-ingest-v1-v2.yaml"
SPEC_FILE = REPO / "contracts" / "adopt-frontmatter-local-ingest-v1-v2.requirements.yaml"
PACKAGE = REPO / "contracts" / "adopt-frontmatter-local-ingest-v1-v2.package.json"
CONSUMER = REPO / "fixtures" / "consumer_rag_ingest_v2"

needs_freeze = pytest.mark.skipif(not PACKAGE.exists(), reason="v2 package not frozen")


def _spec() -> RequirementSpec:
    spec, _ = load_requirement_spec(SPEC_FILE)
    return spec


def _contract() -> TaskContract:
    contract, _ = TaskContract.load_frozen(CONTRACT, require_sidecar=True)
    return contract


def _prompt(spec_override: RequirementSpec | None = None) -> str:
    contract = _contract()
    prompt, _s, _sha = render_task_prompt(
        contract, environment_constraints={"frontmatter": "1.3.0"}, project_root=REPO
    )
    return prompt


def _nodes() -> tuple[list[str], list[str]]:
    coll = json.loads(
        (REPO / "contracts" / "adopt-frontmatter-local-ingest-v1-v2.collection.json").read_text()
    )
    return coll["capability_nodes"], coll["regression_nodes"]


def _evaluate(spec: RequirementSpec, prompt: str, **kw):
    cap, reg = _nodes()
    return evaluate_adequacy(
        spec=spec, capability_nodes=cap, regression_nodes=reg, rendered_prompt=prompt, **kw
    )


# ---- RequirementSpec structural validation ----


def test_spec_loads_and_is_typed() -> None:
    spec = _spec()
    assert len(spec.requirements) == 12
    assert spec.controls is not None and len(spec.controls.negatives) == 4
    owners = {r.owner for r in spec.requirements}
    assert owners == {"HOST_INPUT_GUARD", "ADAPTER", "HARNESS", "UPSTREAM"}


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d["requirements"][0].update(owner="AGENT"), "owner"),
        (lambda d: d["requirements"][0].update(severity="MEDIUM"), "severity"),
        (lambda d: d["requirements"][0].update(public_text="  "), "public_text"),
        (
            lambda d: next(
                r for r in d["requirements"] if r.get("deterministic_input_boundary")
            ).update(owner="ADAPTER"),
            "HOST_INPUT_GUARD",
        ),
        (
            lambda d: d["requirements"][0].update(oracle_nodes=[], verified_by=None),
            "neither oracle_nodes nor verified_by",
        ),
    ],
    ids=["bad-owner", "bad-severity", "empty-text", "boundary-owner", "hard-unchecked"],
)
def test_spec_structural_violations_rejected(tmp_path: Path, mutate, message) -> None:
    import yaml

    data = yaml.safe_load(SPEC_FILE.read_text(encoding="utf-8"))
    mutate(data)
    bad = tmp_path / "req.yaml"
    bad.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(SpecError, match=message):
        load_requirement_spec(bad)


# ---- sabotage scenarios -> gate FAIL (INVALID_TASK_SPEC) ----


def test_gate_passes_on_the_real_frozen_task() -> None:
    result = _evaluate(_spec(), _prompt(), contract_path=CONTRACT)
    assert result.ok, result.failures
    assert result.state == "ADEQUATE"


def test_missing_public_text_rendering_fails_gate() -> None:
    spec = _spec()
    spec.requirements[0].public_text = "this normative sentence is nowhere in the prompt"
    result = _evaluate(spec, _prompt())
    assert not result.ok and result.state == "INVALID_TASK_SPEC"
    assert any("hard_public_text_rendered" in f for f in result.failures)


def test_requirement_only_in_comments_fails_gate(tmp_path: Path) -> None:
    bad_contract = tmp_path / "c.yaml"
    bad_contract.write_text(
        "# P2: has_frontmatter == (metadata != {})\ntask_id: x\n", encoding="utf-8"
    )
    result = _evaluate(_spec(), _prompt(), contract_path=bad_contract)
    assert any("normative_comment_only" in f for f in result.failures)


def test_orphan_oracle_node_fails_gate() -> None:
    spec = _spec()
    for r in spec.requirements:
        r.oracle_nodes = [n for n in r.oracle_nodes if "test_upstream_parse_error_code" not in n]
        if r.id == "upstream-error-wrapped":
            r.verified_by = "orphaned-on-purpose"
    result = _evaluate(spec, _prompt())
    assert any("orphan_oracle_nodes" in f for f in result.failures)


def test_ghost_requirement_node_fails_gate() -> None:
    spec = _spec()
    spec.requirements[0].oracle_nodes.append("test_capability::test_does_not_exist")
    result = _evaluate(spec, _prompt())
    assert any("ghost_requirement_nodes" in f for f in result.failures)


def test_hard_requirement_not_in_prompt_fails_gate() -> None:
    prompt_without = _prompt().replace(
        "never let the raw upstream exception escape", "REDACTED"
    )
    result = _evaluate(_spec(), prompt_without)
    assert any("hard_public_text_rendered" in f for f in result.failures)


def test_boolean_without_truth_table_fails_gate() -> None:
    spec = _spec()
    flag = next(r for r in spec.requirements if r.boolean_field == "frontmatter_present")
    flag.examples = flag.examples[:1]
    result = _evaluate(spec, _prompt())
    assert any("boolean_truth_table" in f for f in result.failures)


def test_undefined_reference_fails_gate() -> None:
    result = _evaluate(_spec(), _prompt() + "\nhandle flags per P2.")
    assert any("undefined_prompt_references" in f for f in result.failures)


def test_held_out_only_semantics_fails_gate() -> None:
    spec = _spec()
    spec.requirements[0].oracle_nodes = ["test_capability::test_output_matches_reference[held]"]
    result = _evaluate(spec, _prompt())
    assert any("held_out_only_semantics" in f for f in result.failures)


def test_bad_controls_fail_gate() -> None:
    result = _evaluate(
        _spec(),
        _prompt(),
        controls_summary={"positive_control": "FAIL:exit=1", "negative_control_NC1": "NOT_REJECTED"},
    )
    assert any("positive_control" in f for f in result.failures)
    assert any("negative_controls" in f for f in result.failures)


def test_prompt_leak_tokens_fail_gate() -> None:
    result = _evaluate(
        _spec(), _prompt() + "\nhint: test_output_matches_reference",
        forbidden_prompt_tokens=("test_output_matches_reference",),
    )
    assert any("prompt_leak_tokens" in f for f in result.failures)


# ---- Contract -> Prompt projection (PromptManifest) ----


def test_prompt_manifest_roundtrip_and_hard_coverage() -> None:
    spec = _spec()
    prompt = _prompt()
    pm = build_prompt_manifest(
        task_id=spec.task_id,
        public_contract_sha="c" * 64,
        requirement_spec_sha="s" * 64,
        public_examples_path=CONSUMER / "public_examples" / "truth_table.json",
        public_tests_tree_sha="t" * 64,
        rendered_prompt=prompt,
        spec=spec,
    )
    hard_ids = {r.id for r in spec.hard()}
    assert hard_ids <= set(pm["requirement_ids_rendered"])
    assert verify_prompt_manifest(pm, spec=spec, rendered_prompt=prompt) == []
    assert verify_prompt_manifest(pm, spec=spec, rendered_prompt=prompt + "x")
    pm_missing = dict(pm, requirement_ids_rendered=[])
    fails = verify_prompt_manifest(pm_missing, spec=spec, rendered_prompt=prompt)
    assert any("HARD requirements not rendered" in f for f in fails)


def test_prompt_carries_no_gate7_or_oracle_leakage() -> None:
    prompt = _prompt()
    for token in (
        "frontmatter.checks(",          # gate 7 adapter's wrong implementation
        "test_output_matches_reference",  # oracle node names
        "held_out_documents",
        "8/11",
        "PASS_ADAPTED",
        "ORACLE CALIBRATION ONLY",      # reference adapter marker
    ):
        assert token not in prompt, token


# ---- InputContractGuard (host-side, subprocess against v2 consumer) ----

GUARD_PROBE = r"""
import json, sys
from rag_ingest import IngestError, ingest_documents
cases = {
    "none": [{"doc_id": "a", "text": None}],
    "missing": [{"doc_id": "a"}],
    "int": [{"doc_id": "a", "text": 123}],
    "list": [{"doc_id": "a", "text": []}],
    "empty_id": [{"doc_id": "", "text": "x"}],
    "nondict": ["x"],
}
out = {}
for name, docs in cases.items():
    try:
        ingest_documents({"documents": docs})
        out[name] = "NO_ERROR"
    except IngestError as e:
        out[name] = e.code
    except Exception as e:  # noqa: BLE001
        out[name] = f"RAW:{type(e).__name__}"
ok = ingest_documents({"documents": [{"doc_id": "ok", "text": "Plain body."}]})
out["valid_passes_guard"] = ok
print(json.dumps(out))
"""


def test_input_guard_behaviour_via_subprocess(tmp_path: Path) -> None:
    # stub adapter: proves valid input passes the guard and REACHES the
    # adapter seam (no upstream lib needed on the host)
    (tmp_path / "adapter.py").write_text(
        "def ingest_documents(request):\n"
        "    return {'records': [{'reached_adapter': d['doc_id']} for d in request['documents']]}\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, "-c", GUARD_PROBE],
        capture_output=True,
        text=True,
        env={
            "PYTHONPATH": str(CONSUMER / "src"),
            "REPOPROOF_ADAPTATION_DIR": str(tmp_path),
            "PATH": "/usr/bin:/bin",
        },
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    out = json.loads(proc.stdout)
    for case in ("none", "missing", "int", "list", "empty_id", "nondict"):
        assert out[case] == "INVALID_DOCUMENT_INPUT", (case, out)
    # guard rejections happen BEFORE the adapter: the stub only sees valid input
    assert out["valid_passes_guard"] == {"records": [{"reached_adapter": "ok"}]}


# ---- frozen battery + e2e gate on the real task ----


@needs_freeze
def test_frozen_controls_summary_is_green() -> None:
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))
    controls = package["controls_summary"]
    assert controls["positive_control"] == "PASS"
    ncs = {k: v for k, v in controls.items() if k.startswith("negative_control")}
    assert len(ncs) == 4 and set(ncs.values()) == {"FAILED_AS_EXPECTED"}


@needs_freeze
def test_adequacy_gate_end_to_end_on_frozen_task() -> None:
    from repoproof.runner.agent_run import run_adequacy_gate

    result = run_adequacy_gate(CONTRACT, REPO)
    assert result["ok"] and result["state"] == "ADEQUATE", result["failures"]
    assert result["adequacy_applicable"] is True


def test_v1_contracts_pass_through_without_spec() -> None:
    contract, _ = TaskContract.load_frozen(
        REPO / "contracts" / "adopt-frontmatter-local-ingest-v1.yaml", require_sidecar=True
    )
    assert contract.requirement_spec_file is None
