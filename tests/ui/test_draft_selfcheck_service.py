"""起草自检自修编排(incident-draft-controls-unverified-*)。

不变量:
  I1 自检 = 现有候选生成尺子(builder→去重→reference→verifier+反事实+覆盖)
     + 判别力探针;不另造比对逻辑;
  I2 失败按公开码路由到 builder / reference / verifier 的**有界**修复(最多
     两轮),每轮修复走快照/标记/回滚事务,drafter 异常必回滚到修前字节;
  I3 修复上下文只含公开合同、当前源码与公开失败分类;不含候选字节、期望树、
     held-out;verifier 修复不得看 reference 源码;
  I4 系统性故障(HARNESS)不触发修复;repair=False 零模型调用;
  I5 报告落盘并绑定修复后的控制件指纹。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from repoproof.adoption.intake.draft_selfcheck import read_draft_self_check
from repoproof.adoption.intake.tool_drafter import DraftError
from repoproof.ui.services import product_jobs


def _draft(tmp_path: Path, monkeypatch) -> Path:
    state = tmp_path / "state"
    monkeypatch.setenv("REPOPROOF_UI_STATE_ROOT", str(state))
    draft_dir = state / "drafts" / "anon"
    (draft_dir / "examples").mkdir(parents=True)
    (draft_dir / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    doc = {
        "task_id": "tool-anon-v1",
        "tool": {
            "name": "anon",
            "summary": "anonymous",
            "schema_version": 4,
            "delivery_profile_id": "workspace_bundle_v1",
            "interface": {
                "input": {"kind": "directory", "format": "dir"},
                "output": {"kind": "directory", "format": "workspace"},
            },
            "workspace_contract": {"schema_version": 1, "rules": [], "require_offline_wheelhouse": False},
        },
        "capability": {"statement": "s", "output_schema": "WorkspaceBundleV1"},
        "source_repo": {
            "url": "https://github.com/anon/anon",
            "resolved_commit": "a" * 40,
            "distribution": "anon",
            "import_module": "anon",
            "license": "MIT",
        },
        "_delivery_profile": {"schema_version": 1, "profile_id": "workspace_bundle_v1"},
        "_intent_contract": {
            "schema_version": 1,
            "user_goal": "g",
            "commitments": [{"commitment_id": "c1", "public_text": "t", "rationale": "r", "origin": "MODEL_PROPOSED"}],
            "artifact_protocol": {
                "schema_version": 1,
                "protocol_id": "p",
                "observations": [
                    {"observation_id": "o", "commitment_ids": ["c1"], "locator": "l", "value_encoding": "v"}
                ],
            },
            "delivery": None,
            "confirmation": None,
        },
    }
    (draft_dir / "draft.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (draft_dir / "fixture_builder.py").write_text("def build(blueprint, output_path):\n    pass\n", encoding="utf-8")
    (draft_dir / "fixture_blueprints.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "blueprints": [
                    {
                        "blueprint_id": "one",
                        "title": "One",
                        "scenario": "s",
                        "input_kind": "directory",
                        "parameters": {"k": 1},
                    },
                    {
                        "blueprint_id": "two",
                        "title": "Two",
                        "scenario": "s",
                        "input_kind": "directory",
                        "parameters": {"k": 2},
                    },
                    {
                        "blueprint_id": "three",
                        "title": "Three",
                        "scenario": "s",
                        "input_kind": "directory",
                        "parameters": {"k": 3},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (draft_dir / "reference_impl.py").write_text(
        "import anon\n\ndef build_workspace(input_path, output_dir):\n    anon.run()\n", encoding="utf-8"
    )
    (draft_dir / "semantic_verifier.py").write_text(
        "import anon\n\ndef verify(input_path, artifact_path):\n    return {'ok': True, "
        "'reason_codes': [], 'checked_commitment_ids': ['c1']}\n",
        encoding="utf-8",
    )
    (draft_dir / "draft_meta.json").write_text('{"drafter": "anonymous-drafter"}\n', encoding="utf-8")
    (draft_dir / "reference.lock.txt").write_text("anon==1.0\n", encoding="utf-8")
    monkeypatch.setattr(product_jobs, "_probe_draft_verifier_discrimination", lambda *_a, **_k: None)
    monkeypatch.setattr(product_jobs, "_core_draft_readiness", lambda *_a, **_k: _readiness())
    monkeypatch.setattr(product_jobs, "resolved_dependency_lock", lambda *_a, **_k: "anon==1.0\n")
    return draft_dir


def _readiness():
    from types import SimpleNamespace

    return SimpleNamespace(
        compatible=True,
        current=True,
        ready=False,
        ready_to_confirm=True,
        reason_codes=[],
        recommended_action="",
        model_dump=lambda mode: {},
    )


class _ScriptedDrafter:
    name = "scripted-drafter"

    def __init__(self, *, verifier=None, reference=None, builder=None, raise_on=None, vary=False):
        self.calls: list[tuple[str, dict]] = []
        self._vary = vary
        self._verifier = verifier
        self._reference = reference
        self._builder = builder
        self._raise_on = raise_on

    def repair_verifier(self, context):
        self.calls.append(("verifier", context))
        if self._raise_on == "verifier":
            raise DraftError("semantic_verifier_contract_repair:INVALID_MODEL_OUTPUT")
        if self._vary:
            return {"semantic_verifier": f"{self._verifier}# attempt {len(self.calls)}\n"}
        return {"semantic_verifier": self._verifier}

    def repair_workspace_reference(self, context):
        self.calls.append(("reference", context))
        if self._raise_on == "reference":
            raise DraftError("workspace_reference_execution_repair:INVALID_MODEL_OUTPUT")
        return {"reference_impl": self._reference}

    def repair_workspace_contract(self, context):
        # Hands the contract back unchanged: the honest shape of an owner that
        # was given its turn and had nothing to change.
        self.calls.append(("contract", context))
        if self._raise_on == "contract":
            raise DraftError("workspace_contract_structural_repair:INVALID_MODEL_OUTPUT")
        return {"workspace_contract": context["current_workspace_contract"]}

    def repair_fixture_builder(self, context):
        self.calls.append(("builder", context))
        return {
            "fixture_builder": self._builder,
            "fixture_blueprints": [
                {
                    "blueprint_id": "one",
                    "title": "One",
                    "scenario": "s",
                    "input_kind": "directory",
                    "parameters": {"k": 10},
                },
                {
                    "blueprint_id": "two",
                    "title": "Two",
                    "scenario": "s",
                    "input_kind": "directory",
                    "parameters": {"k": 20},
                },
                {
                    "blueprint_id": "three",
                    "title": "Three",
                    "scenario": "s",
                    "input_kind": "directory",
                    "parameters": {"k": 30},
                },
            ],
        }


def _scripted_candidates(monkeypatch, outcomes: list[dict]):
    calls: list[int] = []

    def fake(draft_dir, *, n, offline):
        if offline is False:
            # The fresh-input agreement probe (one online proposal) runs before the
            # drafted generation; these scripts describe the drafted generation only.
            return {"ok": True, "candidates": [{}], "generation_id": "probe"}
        assert offline is True and n == 3
        calls.append(1)
        outcome = outcomes[min(len(calls), len(outcomes)) - 1]
        if outcome.get("ok"):
            (Path(draft_dir) / "workspace_fixture_candidates.json").write_text(
                json.dumps({"schema_version": 1, "generation_id": "g", "records": []}), encoding="utf-8"
            )
        return {**outcome, "generation_id": "g" if outcome.get("ok") else None}

    monkeypatch.setattr(product_jobs, "propose_workspace_fixture_candidates", fake)
    return calls


def test_disagreement_repairs_verifier_then_passes(tmp_path: Path, monkeypatch) -> None:
    draft_dir = _draft(tmp_path, monkeypatch)
    calls = _scripted_candidates(
        monkeypatch,
        [
            {
                "ok": False,
                "reason_codes": ["WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"],
                "diagnostics": ["VALUE_MISMATCH"],
                "failure_owner": "CONTRACT",
            },
            {"ok": True, "candidates": [{}, {}, {}]},
        ],
    )
    fixed = (
        "import anon\n\ndef verify(input_path, artifact_path):\n    anon.run()\n    return {'ok': True, "
        "'reason_codes': [], 'checked_commitment_ids': ['c1']}\n"
    )
    drafter = _ScriptedDrafter(verifier=fixed)
    before_reference = (draft_dir / "reference_impl.py").read_bytes()

    result = product_jobs.run_draft_self_check(draft_dir, repair=True, drafter=drafter)

    assert result["ok"] is True and len(calls) == 2
    assert [name for name, _ in drafter.calls] == ["verifier"]
    context = drafter.calls[0][1]
    assert context["self_check_failure"]["reason_code"] == "WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"
    assert context["self_check_failure"]["diagnostics"] == ["VALUE_MISMATCH"]
    assert "current_reference_impl" not in context and "reference_impl" not in json.dumps(context)
    assert (draft_dir / "semantic_verifier.py").read_text(encoding="utf-8") == fixed
    assert (draft_dir / "reference_impl.py").read_bytes() == before_reference
    report = read_draft_self_check(draft_dir)
    assert report is not None and report.ok is True
    assert [r.round for r in report.rounds] == [1, 2]
    assert report.rounds[0].repair is not None and report.rounds[0].repair.target == "verifier"
    assert report.rounds[0].repair.outcome == "APPLIED"
    assert not (draft_dir / product_jobs._CONTROL_REPAIR_MARKER).exists()


def test_persistent_disagreement_alternates_to_reference_then_stops_at_bound(tmp_path: Path, monkeypatch) -> None:
    draft_dir = _draft(tmp_path, monkeypatch)
    failure = {
        "ok": False,
        "reason_codes": ["WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"],
        "diagnostics": ["VALUE_MISMATCH"],
        "failure_owner": "CONTRACT",
    }
    calls = _scripted_candidates(monkeypatch, [failure, failure, failure, failure])
    drafter = _ScriptedDrafter(
        verifier=(
            "import anon\n\ndef verify(i, a):\n    anon.run()\n    return {'ok': False, "
            "'reason_codes': ['X'], 'checked_commitment_ids': ['c1']}\n"
        ),
        reference="import anon\n\ndef build_workspace(input_path, output_dir):\n    anon.run(1)\n",
        vary=True,
    )

    result = product_jobs.run_draft_self_check(draft_dir, repair=True, max_repair_rounds=3, drafter=drafter)

    # Stall budget: an attempt is an owner plus the evidence it was handed, so the
    # same disagreement handed to a control that has not answered it yet is free.
    # The disagreement's owner sequence covers all four controls — verifier,
    # verifier, reference, reference, contract, builder — before the producer is
    # asked again, and only then is the budget spent.
    assert result["ok"] is False and len(calls) == 4
    # A reference repair whose two bounded drafter calls both return the same source
    # rolls back as NO_PROGRESS, so those repairs show up as two drafter calls each.
    assert [name for name, _ in drafter.calls] == [
        "verifier",
        "verifier",
        "reference",
        "reference",
        "reference",
        "contract",
        "builder",
        "reference",
        "reference",
    ]
    second_verifier_context = drafter.calls[1][1]
    assert second_verifier_context["self_check_failure"]["repeated_after_repair"] is True
    assert second_verifier_context["self_check_failure"]["previous_repair_targets"] == ["verifier"]
    reference_context = drafter.calls[2][1]
    assert "current_reference_impl" in reference_context and "semantic_verifier" not in json.dumps(reference_context)
    report = read_draft_self_check(draft_dir)
    assert report is not None and [r.round for r in report.rounds] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert [r.repair.target for r in report.rounds if r.repair is not None] == [
        "verifier",
        "verifier",
        "reference",
        "reference",
        "contract",
        "builder",
        "reference",
    ]
    assert report.rounds[7].repair is None
    assert report.final_reason_codes == ("WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT",)


def test_harness_failure_never_triggers_repair(tmp_path: Path, monkeypatch) -> None:
    draft_dir = _draft(tmp_path, monkeypatch)
    _scripted_candidates(
        monkeypatch,
        [{"ok": False, "reason_codes": ["PINNED_UPSTREAM_UNAVAILABLE"], "diagnostics": [], "failure_owner": "HARNESS"}],
    )
    drafter = _ScriptedDrafter(verifier="x")

    result = product_jobs.run_draft_self_check(draft_dir, repair=True, drafter=drafter)

    assert result["ok"] is False and drafter.calls == []
    report = read_draft_self_check(draft_dir)
    assert report is not None and len(report.rounds) == 1 and report.rounds[0].repair is None


def test_repair_disabled_makes_zero_model_calls(tmp_path: Path, monkeypatch) -> None:
    draft_dir = _draft(tmp_path, monkeypatch)
    _scripted_candidates(
        monkeypatch,
        [
            {
                "ok": False,
                "reason_codes": ["FIXTURE_BUILDER_FAILED"],
                "diagnostics": ["ValueError"],
                "failure_owner": "CONTRACT",
            }
        ],
    )
    drafter = _ScriptedDrafter(builder="x")

    result = product_jobs.run_draft_self_check(draft_dir, repair=False, drafter=drafter)

    assert result["ok"] is False and drafter.calls == []


def test_builder_failure_repairs_builder_and_blueprints(tmp_path: Path, monkeypatch) -> None:
    draft_dir = _draft(tmp_path, monkeypatch)
    calls = _scripted_candidates(
        monkeypatch,
        [
            {
                "ok": False,
                "reason_codes": ["FIXTURE_BUILDER_FAILED"],
                "diagnostics": ["UnicodeEncodeError"],
                "failure_owner": "CONTRACT",
            },
            {"ok": True, "candidates": [{}, {}, {}]},
        ],
    )
    new_builder = (
        "from pathlib import Path\n\ndef build(blueprint, output_path):\n"
        "    parameters = blueprint['parameters']\n    Path(output_path).mkdir(parents=True)\n"
        "    (Path(output_path) / 'k.txt').write_text(str(parameters['k']), encoding='utf-8')\n"
    )
    drafter = _ScriptedDrafter(builder=new_builder)

    result = product_jobs.run_draft_self_check(draft_dir, repair=True, drafter=drafter)

    assert result["ok"] is True and len(calls) == 2
    assert [name for name, _ in drafter.calls] == ["builder"]
    assert drafter.calls[0][1]["self_check_failure"]["public_class"] == "UnicodeEncodeError"
    assert (draft_dir / "fixture_builder.py").read_text(encoding="utf-8") == new_builder
    blueprints = json.loads((draft_dir / "fixture_blueprints.json").read_text(encoding="utf-8"))["blueprints"]
    assert [item["parameters"]["k"] for item in blueprints] == [10, 20, 30]


def test_discrimination_gap_repairs_verifier_with_public_gap_list(tmp_path: Path, monkeypatch) -> None:
    draft_dir = _draft(tmp_path, monkeypatch)
    calls = _scripted_candidates(
        monkeypatch, [{"ok": True, "candidates": [{}, {}, {}]}, {"ok": True, "candidates": [{}, {}, {}]}]
    )
    from types import SimpleNamespace

    probes: list[int] = []

    def probe(_draft_dir, _draft):
        probes.append(1)
        gaps = ("data/table.csv",) if len(probes) == 1 else ()
        return SimpleNamespace(ok=not gaps, gaps=gaps, probed_files=2)

    monkeypatch.setattr(product_jobs, "_probe_draft_verifier_discrimination", probe)
    drafter = _ScriptedDrafter(
        verifier=(
            "import anon\n\ndef verify(i, a):\n    anon.run()\n    return {'ok': True, "
            "'reason_codes': [], 'checked_commitment_ids': ['c1']}\n"
        )
    )

    result = product_jobs.run_draft_self_check(draft_dir, repair=True, drafter=drafter)

    assert result["ok"] is True and len(calls) == 2 and len(probes) == 2
    assert [name for name, _ in drafter.calls] == ["verifier"]
    assert drafter.calls[0][1]["self_check_failure"]["discrimination_gaps"] == ["data/table.csv"]
    report = read_draft_self_check(draft_dir)
    assert report is not None and report.rounds[0].discrimination_gaps == ("data/table.csv",)
    assert report.rounds[0].reason_codes == ("VERIFIER_DISCRIMINATION_GAP",)


def test_drafter_failure_rolls_back_controls_and_records_outcome(tmp_path: Path, monkeypatch) -> None:
    draft_dir = _draft(tmp_path, monkeypatch)
    _scripted_candidates(
        monkeypatch,
        [
            {
                "ok": False,
                "reason_codes": ["WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"],
                "diagnostics": ["X"],
                "failure_owner": "CONTRACT",
            }
        ],
    )
    drafter = _ScriptedDrafter(verifier="unused", raise_on="verifier")
    before = {
        name: (draft_dir / name).read_bytes()
        for name in (
            "draft.yaml",
            "reference_impl.py",
            "semantic_verifier.py",
            "fixture_builder.py",
            "fixture_blueprints.json",
        )
    }

    result = product_jobs.run_draft_self_check(draft_dir, repair=True, drafter=drafter)

    assert result["ok"] is False
    assert {name: (draft_dir / name).read_bytes() for name in before} == before
    assert not (draft_dir / product_jobs._CONTROL_REPAIR_MARKER).exists()
    report = read_draft_self_check(draft_dir)
    assert report is not None and report.rounds[0].repair is not None
    assert report.rounds[0].repair.outcome == "ROLLED_BACK"


def test_offline_drafter_cannot_repair_and_is_reported_as_unavailable(tmp_path: Path, monkeypatch) -> None:
    draft_dir = _draft(tmp_path, monkeypatch)
    _scripted_candidates(
        monkeypatch,
        [
            {
                "ok": False,
                "reason_codes": ["FIXTURE_BUILDER_FAILED"],
                "diagnostics": ["ValueError"],
                "failure_owner": "CONTRACT",
            }
        ],
    )
    from repoproof.adoption.intake.tool_drafter import FakeDrafter

    result = product_jobs.run_draft_self_check(draft_dir, repair=True, drafter=FakeDrafter())

    assert result["ok"] is False
    report = read_draft_self_check(draft_dir)
    assert report is not None and report.rounds[0].repair is not None
    assert report.rounds[0].repair.outcome == "UNAVAILABLE"


@pytest.mark.parametrize("name", ["fixture_builder.py", "fixture_blueprints.json"])
def test_rollback_file_set_covers_builder_assets(name: str) -> None:
    assert name in product_jobs._CONTROL_ROLLBACK_FILES
