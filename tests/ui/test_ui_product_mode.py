"""Product Mode Studio: fact projection, safe argv and page smoke tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from repoproof.adoption.intake import example_proposer, tool_drafter
from repoproof.adoption.intake.intent_contract import (
    install_artifact_protocol,
    install_delivery_intent_from_interface,
    install_semantic_commitments,
    new_intent_contract,
    validate_intent_contract,
)
from repoproof.ui.services import product_jobs, product_mode
from repoproof.verification import semantic_artifact

REPO = Path(__file__).resolve().parents[2]
PAGES = REPO / "src" / "repoproof" / "ui" / "pages"

try:
    from streamlit.testing.v1 import AppTest

    HAVE_ST = True
except ImportError:  # pragma: no cover
    HAVE_ST = False

needs_streamlit = pytest.mark.skipif(not HAVE_ST, reason="streamlit (ui extra) not installed")


def _current_editable_draft(
    *,
    tool_name: str = "alpha-tool",
    import_module: str = "alpha",
    user_goal: str = "Transform one local input.",
    commitment_id: str = "transform-input",
) -> dict:
    draft = {
        "_delivery_profile": {"schema_version": 1, "profile_id": "cli_v2"},
        "_intent_contract": new_intent_contract(user_goal),
        "source_repo": {
            "url": "https://github.com/example/upstream",
            "resolved_commit": "a" * 40,
            "license": "MIT",
            "distribution": "alpha",
            "import_module": import_module,
        },
        "tool": {
            "schema_version": 3,
            "name": tool_name,
            "summary": "",
            "interface": {
                "usage": f"{tool_name} <input> [--out FILE]",
                "input": {"kind": "file", "format": "TXT"},
                "output": {
                    "kind": "stdout",
                    "format": "plain text",
                    "contract": {
                        "media_type": "text/plain",
                        "root_type": "text",
                        "required": {},
                        "validation_profile": "plain_text_v1",
                    },
                },
                "exit_codes": {
                    "0": "success",
                    "1": "user_error",
                    "2": "internal_error",
                },
            },
        },
        "capability": {"statement": "", "output_schema": "AlphaText"},
    }
    install_delivery_intent_from_interface(draft, profile_id="cli_v2")
    install_semantic_commitments(draft, [{
        "commitment_id": commitment_id,
        "public_text": "Transform the input through the fixed upstream.",
        "rationale": "This is the public requested behaviour.",
    }])
    install_artifact_protocol(draft, {
        "schema_version": 1,
        "protocol_id": "upstream-text-v1",
        "observations": [{
            "observation_id": "transformed-body",
            "commitment_ids": [commitment_id],
            "locator": "完整 UTF-8 文本正文",
            "value_encoding": "固定版本上游产生的 UTF-8 文本",
        }],
    })
    return draft


def test_repo_summary_receives_the_user_capability_goal(monkeypatch: pytest.MonkeyPatch) -> None:
    """主流程的 LLM 分析必须看到用户目标，而不是只做泛化 README 翻译。"""
    seen: dict = {}

    class _Drafter:
        name = "gateway-test"

        def summarize_repo(self, context: dict) -> dict:
            seen.update(context)
            return {"summary": "analysis"}

    monkeypatch.setattr(tool_drafter, "online_drafter", lambda: _Drafter())
    result = product_jobs.summarize_repo_overview(
        {
            "repository": "https://github.com/example/demo",
            "headline": "demo",
            "prose": "readme",
            "surfaces": [{"value": "merge"}],
        },
        offline=False,
        capability_goal="合并报告并输出 JSON",
    )

    assert result["ok"]
    assert seen["capability_goal"] == "合并报告并输出 JSON"
    assert seen["surfaces"] == ["merge"]
    assert result["summary"] == "analysis"
    assert result["requirement_briefs"] == []
    assert result["recommended_brief_id"] == ""


def test_repo_summary_timeout_is_structured_and_does_not_create_agent_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _TimeoutDrafter:
        name = "gateway-test"

        def summarize_repo(self, _context: dict) -> dict:
            raise tool_drafter.DraftError("DRAFTER_TIMEOUT")

    monkeypatch.setattr(tool_drafter, "online_drafter", lambda: _TimeoutDrafter())
    result = product_jobs.summarize_repo_overview(
        {"repository": "https://github.com/example/demo"},
        offline=False,
        capability_goal="整理资料",
    )

    assert result["ok"] is False
    assert result["failure_owner"] == "EXTERNAL"
    assert result["reason_codes"] == ["DRAFTER_TIMEOUT"]
    assert "没有创建 Journey" in result["recommended_action"]


def test_repo_summary_projects_structured_requirement_briefs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def delivery(output_format_id: str) -> dict:
        return {
            "inputs": [{
                "kind": "file", "location": "local",
                "representation": "utf8_text",
                "format_label": "RIS", "role": "待整理文献",
            }],
            "outputs": [{
                "kind": "text_artifact", "format_id": output_format_id,
                "format_label": output_format_id, "role": "整理结果",
            }],
            "network": "offline", "credentials": "none",
            "lifecycle": "per_invocation", "runtime": "local_cpu",
        }

    class _Drafter:
        name = "gateway-test"

        def summarize_repo(self, _context: dict) -> dict:
            return {
                "summary": "可以整理文献记录。",
                "requirement_briefs": [
                    {
                        "brief_id": "ris",
                        "title": "整理文献",
                        "scenario": "把文献记录整理后继续使用。",
                        "delivery_requirements": delivery("ris"),
                        "boundary": "不补充外部书目信息",
                        "reason": "仓库说明支持读取和写出 RIS。",
                    },
                    {
                        "brief_id": "table",
                        "title": "生成检查表",
                        "scenario": "检查文献记录里的缺失内容。",
                        "delivery_requirements": delivery("csv"),
                        "boundary": "无法判断的字段保持原样",
                        "reason": "仓库说明可以读取文献字段。",
                    },
                ],
                "recommended_brief_id": "ris",
            }

    monkeypatch.setattr(tool_drafter, "online_drafter", lambda: _Drafter())
    result = product_jobs.summarize_repo_overview(
        {"repository": "https://github.com/example/demo", "headline": "demo"},
        offline=False,
        capability_goal="帮我整理文献",
    )

    assert result["ok"]
    assert result["recommended_brief_id"] == "ris"
    assert [brief["brief_id"] for brief in result["requirement_briefs"]] == ["ris", "table"]
    assert result["requirement_briefs"][0]["delivery_shape"]["output_cardinality"] == 1


def _tool_world(root: Path) -> Path:
    tools = root / "tools"
    package = tools / "alpha-tool"
    package.mkdir(parents=True)
    manifest = {
        "name": "alpha-tool",
        "summary": "把 Alpha 文本转换为规范化结果",
        "source": {
            "url": "https://github.com/acme/alpha",
            "distribution": "alpha",
            "resolved_commit": "a" * 40,
        },
        "verification": {
            "verdict": "VERIFIED_TOOL_READY",
            "run_id": "tool-alpha-v1-20260824-000000",
            "contract_sha256": "b" * 64,
        },
    }
    (package / "tool.json").write_text(json.dumps(manifest), encoding="utf-8")
    evidence = package / "evidence"
    evidence.mkdir()
    (evidence / "provenance.json").write_text(
        json.dumps({
            "tool": "alpha-tool",
            "task_id": "tool-alpha-tool-v1",
            "run_id": manifest["verification"]["run_id"],
            "tool_contract_sha256": manifest["verification"]["contract_sha256"],
        }),
        encoding="utf-8",
    )
    (tools / ".repoproof-registry.json").write_text(
        json.dumps({
            "schema_version": 1,
            "tools": {
                "alpha-tool": {
                    "path": str(package),
                    "task_id": "tool-alpha-tool-v1",
                    "run_id": manifest["verification"]["run_id"],
                    "contract_sha256": manifest["verification"]["contract_sha256"],
                    "verdict": "VERIFIED_TOOL_READY",
                    "historical_verdict": "VERIFIED_TOOL_READY",
                    "summary": manifest["summary"],
                    "source": manifest["source"],
                }
            },
        }),
        encoding="utf-8",
    )
    return tools


def _decision(decision: str, reason_code: str) -> dict:
    return {
        "schema_version": 1,
        "tool": "alpha-tool",
        "task_id": "tool-alpha-tool-v1",
        "run_id": "tool-alpha-v1-20260824-000000",
        "decision": decision,
        "reason_code": reason_code,
        "reason": reason_code.replace("_", " ").lower(),
        "evidence_sha256": "c" * 64,
        "decided_at": "2026-08-24T00:00:00Z",
        "actor": "operator",
    }


def test_verified_tool_defaults_to_review_without_release_ledger(tmp_path: Path) -> None:
    tools = _tool_world(tmp_path)
    result = product_mode.list_tools(tools)
    assert result["release_ledger_present"] is False
    assert result["tools"][0]["historical_verdict"] == "VERIFIED_TOOL_READY"
    assert result["tools"][0]["operational_status"] == "REVIEW_REQUIRED"


def test_release_ledger_folds_without_rewriting_history(tmp_path: Path) -> None:
    tools = _tool_world(tmp_path)
    ledger = tools / product_mode.RELEASE_LEDGER_NAME
    ledger.write_text(
        "\n".join([
            json.dumps(_decision("ACTIVE", "FRESH_INPUT_PASS")),
            json.dumps(_decision("REVOKED", "USER_WITHDRAWAL")),
        ]) + "\n",
        encoding="utf-8",
    )
    row = product_mode.list_tools(tools)["tools"][0]
    assert row["historical_verdict"] == "VERIFIED_TOOL_READY"
    assert row["operational_status"] == "REVOKED"
    assert row["operational_reason"] == "USER_WITHDRAWAL"


def test_bad_release_ledger_fails_closed(tmp_path: Path) -> None:
    tools = _tool_world(tmp_path)
    (tools / product_mode.RELEASE_LEDGER_NAME).write_text(
        json.dumps({"tool": "alpha-tool", "decision": "MAGIC"}) + "\n",
        encoding="utf-8",
    )
    result = product_mode.list_tools(tools)
    assert result["release_error"]
    assert result["tools"] == []
    assert result["projection_errors"][0]["reason_code"] == "RELEASE_LEDGER_INVALID"


def test_dashboard_keeps_recorded_and_operational_counts_separate(tmp_path: Path) -> None:
    tools = _tool_world(tmp_path)
    (tools / product_mode.RELEASE_LEDGER_NAME).write_text(
        json.dumps(_decision("ACTIVE", "FRESH_INPUT_PASS")) + "\n",
        encoding="utf-8",
    )
    project = tmp_path / "project"
    (project / "docs").mkdir(parents=True)
    (project / "docs" / "m4_metrics.json").write_text(json.dumps({
        "submitted": 12, "accepted": 11, "tool_ready": 10,
        "false_success": {"audited": 10, "flagged": 1},
    }), encoding="utf-8")
    out = product_mode.dashboard_snapshot(tools, project)
    assert out["historically_verified"] == 1
    assert out["operational"]["ACTIVE"] == 1
    assert out["metrics"]["tool_ready"] == 10
    assert out["false_success"] == 1


def test_product_argv_is_shell_free_and_contains_no_credentials(tmp_path: Path) -> None:
    argv = product_jobs.tool_add_argv(
        REPO,
        repo="https://github.com/acme/alpha",
        capability="把 Alpha 能力包装成本地工具",
        draft_dir=tmp_path / "draft",
        revision="v1.0.0",
        fake_drafter=True,
    )
    assert argv[-1] == "--fake-drafter"
    assert "https://github.com/acme/alpha" in argv
    assert not any("KEY" in arg or "TOKEN" in arg or "sk-" in arg for arg in argv)
    assert all(";" not in arg for arg in argv)


def test_review_editor_and_examples_only_write_inside_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = (tmp_path / "state").resolve()
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    draft = state_root / "drafts" / "draft"
    (draft / "examples").mkdir(parents=True)
    doc = _current_editable_draft()
    (draft / "draft.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    (draft / "reference_impl.py").write_text("", encoding="utf-8")
    (draft / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    saved = product_jobs.save_draft_review(
        draft, tool_name="alpha-tool", summary="Alpha 转换",
        statement=doc["capability"]["statement"], input_format="TXT",
        output_format="plain text", output_schema="AlphaText",
        reference_impl=(
            "import alpha\n\n"
            "def extract(input_path):\n"
            "    return alpha.transform(input_path.read_text())\n"
        ),
        semantic_verifier=(
            "import alpha\n\n"
            "def verify(input_path, artifact_path):\n"
            "    return {'ok': True, 'reason_codes': [], "
            "'checked_commitment_ids': ['transform-input']}\n"
        ),
        output_contract=doc["tool"]["interface"]["output"]["contract"],
        reference_lock="alpha==1.2.3\nalpha-helper==4.5.6",
    )
    assert saved["ok"]
    assert (draft / "reference.lock.txt").read_text(encoding="utf-8") == (
        "alpha==1.2.3\nalpha-helper==4.5.6\n"
    )
    added = product_jobs.add_golden_example(
        draft, input_name="a.txt", input_bytes=b"a",
        expected_name="a.expected.txt", expected_bytes=b"A",
    )
    assert added["ok"]
    assert (draft / "examples" / "inputs" / "a.txt").read_bytes() == b"a"
    examples = yaml.safe_load((draft / "examples.yaml").read_text())
    assert examples["examples"] == [
        {
            "input_file": "inputs/a.txt",
            "expected_file": "expected/a.expected.txt",
            "truth_provenance": "USER_SUPPLIED",
        }
    ]
    review = product_jobs.read_managed_draft_review(draft)
    assert review["ok"] is True
    readiness = review["draft_readiness"]
    assert readiness["compatible"] is True
    assert readiness["current"] is True
    assert readiness["public_summary"]["example_count"] == 1
    assert review["reference_impl"].startswith("import alpha\n")
    assert review["dependency_lock"]["source"] == "user"
    assert review["dependency_lock"]["pins"] == ["alpha==1.2.3", "alpha-helper==4.5.6"]


def test_unfrozen_legacy_draft_mutations_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = (tmp_path / "state").resolve()
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    draft = state_root / "drafts" / "legacy"
    (draft / "examples").mkdir(parents=True)
    original = "tool:\n  schema_version: 2\n  name: legacy-tool\n"
    (draft / "draft.yaml").write_text(original, encoding="utf-8")
    (draft / "reference_impl.py").write_text("", encoding="utf-8")
    (draft / "examples.yaml").write_text("examples: []\n", encoding="utf-8")

    saved = product_jobs.save_draft_review(
        draft,
        tool_name="legacy-tool",
        summary="legacy",
        statement="legacy",
        input_format="TXT",
        output_format="plain text",
        output_schema="LegacyText",
        reference_impl="import legacy\n",
    )
    added = product_jobs.add_golden_example(
        draft,
        input_name="a.txt",
        input_bytes=b"a",
        expected_name="a.expected.txt",
        expected_bytes=b"A",
    )

    assert saved["error_code"] == "DRAFT_INCOMPATIBLE"
    assert added["error_code"] == "DRAFT_INCOMPATIBLE"
    assert (draft / "draft.yaml").read_text(encoding="utf-8") == original
    assert not (draft / "examples" / "inputs").exists()


def test_traced_review_compiles_public_commitments_and_reconfirms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = (tmp_path / "state").resolve()
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    draft_dir = state_root / "drafts" / "traced"
    (draft_dir / "examples").mkdir(parents=True)
    draft = _current_editable_draft(
        tool_name="trace-tool",
        user_goal="整理我的输入，方便后续工作",
        commitment_id="preserve-order",
    )
    (draft_dir / "draft.yaml").write_text(
        yaml.safe_dump(draft, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (draft_dir / "reference_impl.py").write_text("import alpha\n", encoding="utf-8")
    (draft_dir / "examples.yaml").write_text("examples: []\n", encoding="utf-8")

    saved = product_jobs.save_draft_review(
        draft_dir,
        tool_name="trace-tool",
        summary="整理工具",
        statement=draft["capability"]["statement"],
        semantic_commitments=["保留输入顺序，并删除完全相同的重复条目。"],
        input_format="TXT",
        output_format="plain text",
        output_schema="TraceText",
        reference_impl=(
            "import alpha\n\n"
            "def extract(input_path):\n"
            "    return alpha.transform(input_path.read_text())\n"
        ),
        semantic_verifier=(
            "import alpha\n\n"
            "def verify(input_path, artifact_path):\n"
            "    return {'ok': True, 'reason_codes': [], "
            "'checked_commitment_ids': ['preserve-order']}\n"
        ),
        output_contract={
                "media_type": "text/plain",
                "root_type": "text",
                "required": {},
                "validation_profile": "plain_text_v1",
        },
        reference_lock="alpha==1.2.3",
    )
    assert saved["ok"] is True
    reviewed = yaml.safe_load((draft_dir / "draft.yaml").read_text(encoding="utf-8"))
    assert "删除完全相同的重复条目" in reviewed["capability"]["statement"]
    assert reviewed["_intent_contract"]["confirmation"] is None
    (draft_dir / "examples" / "sample.txt").write_text("sample", encoding="utf-8")
    (draft_dir / "examples.yaml").write_text(
        yaml.safe_dump({"examples": [
            {"input_file": "sample.txt", "expected": "SAMPLE"},
            {"input": "second", "expected": "SECOND"},
            {"input": "third", "expected": "THIRD"},
        ]}),
        encoding="utf-8",
    )
    readiness = product_jobs.read_managed_draft_review(draft_dir)["draft_readiness"]
    assert readiness["ready_to_confirm"] is True
    assert readiness["reason_codes"] == ["INTENT_CONFIRMATION_MISSING"]

    confirmed = product_jobs.confirm_draft_intent(draft_dir)
    assert confirmed["ok"] is True
    rebound = yaml.safe_load((draft_dir / "draft.yaml").read_text(encoding="utf-8"))
    assert validate_intent_contract(rebound) == []

    resaved = product_jobs.save_draft_review(
        draft_dir,
        tool_name="trace-tool",
        summary="整理工具",
        statement=rebound["capability"]["statement"],
        semantic_commitments=["保留所有有效条目，不去重。"],
        input_format="TXT",
        output_format="plain text",
        output_schema="TraceText",
        reference_impl="import alpha\n",
        output_contract={
                "media_type": "text/plain",
                "root_type": "text",
                "required": {},
                "validation_profile": "plain_text_v1",
        },
    )
    assert resaved["ok"] is True
    changed = yaml.safe_load((draft_dir / "draft.yaml").read_text(encoding="utf-8"))
    assert changed["_intent_contract"]["confirmation"] is None


def test_candidate_confirmation_preserves_upstream_input_output_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = (tmp_path / "state").resolve()
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    draft = state_root / "drafts" / "draft"
    (draft / "examples").mkdir(parents=True)
    candidate_draft = _current_editable_draft(
        import_module="candidate_upstream",
    )
    (draft / "draft.yaml").write_text(
        yaml.safe_dump(candidate_draft),
        encoding="utf-8",
    )
    (draft / "reference_impl.py").write_text(
        "from pathlib import Path\nimport candidate_upstream\n\n"
        "def extract(input_path: Path) -> str:\n"
        "    return candidate_upstream.convert(input_path.read_text())\n",
        encoding="utf-8",
    )
    (draft / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    (upstream / "candidate_upstream.py").write_text(
        "def convert(text):\n    return 'pinned output'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        product_jobs,
        "_draft_upstream_dir",
        lambda _draft: (upstream, ""),
    )
    candidate_object = example_proposer.run_reference_on_candidates(
        example_proposer.ProposalBatch(candidates=[
            example_proposer.CandidateExample(
                input_name="bound.txt",
                input_text="original input",
            )
        ]),
        draft_dir=draft,
        upstream_dir=upstream,
        import_module="candidate_upstream",
    ).candidates[0]
    product_jobs._persist_candidate_evidence_records(draft, [candidate_object])
    candidate = candidate_object.model_dump(mode="json")

    changed_input = product_jobs.confirm_candidate_as_example(
        draft,
        candidate,
        expected_text="pinned output",
        input_text="modified input",
    )
    changed_output = product_jobs.confirm_candidate_as_example(
        draft,
        candidate,
        expected_text="modified output",
        input_text="original input",
    )
    forged_candidate = json.loads(json.dumps(candidate))
    forged_candidate["input_text"] = "browser-forged input"
    forged = product_jobs.confirm_candidate_as_example(
        draft,
        forged_candidate,
        expected_text="pinned output",
        input_text="browser-forged input",
    )
    missing_evidence = product_jobs.confirm_candidate_as_example(
        draft,
        {
            "input_name": "unsigned.txt",
            "input_text": "unsigned",
            "upstream_output": "self-asserted",
        },
        expected_text="self-asserted",
        input_text="unsigned",
    )
    assert changed_input["reason_codes"] == ["CANDIDATE_TRUTH_BINDING_MISMATCH"]
    assert changed_output["reason_codes"] == ["CANDIDATE_TRUTH_BINDING_MISMATCH"]
    assert forged["reason_codes"] == ["CANDIDATE_MANAGED_EVIDENCE_INVALID"]
    assert missing_evidence["reason_codes"] == ["CANDIDATE_MANAGED_EVIDENCE_INVALID"]
    assert not (draft / "examples" / "inputs").exists()

    confirmed = product_jobs.confirm_candidate_as_example(
        draft,
        candidate,
        expected_text="pinned output",
        input_text="original input",
    )
    assert confirmed["ok"]
    assert confirmed["truth_provenance"] == "UPSTREAM_DERIVED_USER_CONFIRMED"
    assert (draft / "examples" / "inputs" / "bound.txt").read_text() == "original input"
    assert (draft / "examples" / "expected" / "bound.expected.txt").read_text() == (
        "pinned output"
    )
    persisted = yaml.safe_load((draft / "examples.yaml").read_text())["examples"][0]
    assert persisted["truth_provenance"] == "UPSTREAM_DERIVED_USER_CONFIRMED"
    assert len(persisted["truth_binding_sha256"]) == 64
    assert persisted["candidate_evidence_id"] == (
        candidate_object.truth_evidence.evidence_id
    )
    assert persisted["candidate_truth_binding_sha256"] == (
        candidate_object.truth_evidence.truth_binding_sha256
    )


def test_fresh_audit_materialization_uses_managed_candidate_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "state"
    tools = tmp_path / "tools"
    tool_dir = tools / "demo-tool"
    tool_dir.mkdir(parents=True)
    root = tmp_path / "project"
    task_id = "tool-demo-tool-v1"
    reference_dir = root / "controls" / task_id / "reference"
    reference_dir.mkdir(parents=True)
    reference_source = (
        "from pathlib import Path\nimport audit_upstream\n\n"
        "def extract(input_path: Path) -> str:\n"
        "    return audit_upstream.convert(input_path.read_text())\n"
    )
    (reference_dir / "impl.py").write_text(reference_source, encoding="utf-8")
    (reference_dir / "requirements.lock.txt").write_text("audit-upstream==1\n")
    upstream = root / "upstream-cache" / f"upstream-{'a' * 12}"
    upstream.mkdir(parents=True)
    (upstream / "audit_upstream.py").write_text(
        "def convert(text):\n    return text.upper()\n",
        encoding="utf-8",
    )
    draft = tmp_path / "probe"
    draft.mkdir()
    (draft / "reference_impl.py").write_text(reference_source, encoding="utf-8")
    candidate_object = example_proposer.run_reference_on_candidates(
        example_proposer.ProposalBatch(candidates=[
            example_proposer.CandidateExample(
                input_name="fresh.txt",
                input_text="fresh input",
            )
        ]),
        draft_dir=draft,
        upstream_dir=upstream,
        import_module="audit_upstream",
    ).candidates[0]

    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    monkeypatch.setattr(
        "repoproof.ui.services.product_mode.project_root",
        lambda: root,
    )
    monkeypatch.setattr(
        "repoproof.ui.services.product_mode.list_tools",
        lambda _root: {
            "tools": [{
                "name": "demo-tool",
                "task_id": task_id,
                "path": str(tool_dir),
                "health": "OK",
                "resolved_commit": "a" * 40,
            }],
            "registry_error": None,
            "release_error": None,
        },
    )
    monkeypatch.setattr(product_jobs, "_verify_frozen_reference_identity", lambda **_kw: {})
    monkeypatch.setattr(product_jobs, "_verify_pinned_upstream_tree", lambda *_a: None)
    from repoproof.domain.models import TaskContract

    monkeypatch.setattr(
        TaskContract,
        "load_frozen",
        staticmethod(lambda *_a, **_kw: (
            SimpleNamespace(
                task_id=task_id,
                source_repo=SimpleNamespace(
                    resolved_commit="a" * 40,
                    import_module="audit_upstream",
                ),
            ),
            "contract-sha",
        )),
    )
    context = product_jobs._audit_candidate_context(
        tool_name="demo-tool",
        task_id=task_id,
        dest_root=tools,
    )
    store = product_jobs._managed_candidate_evidence_store(
        namespace="audit",
        context_identity=context,
        create=True,
    )
    product_jobs._persist_managed_candidate_evidence_records(
        store=store,
        context_identity=context,
        candidates=[candidate_object],
    )
    candidate = candidate_object.model_dump(mode="json")

    materialized = product_jobs.materialize_audit_candidate(
        "demo-tool",
        candidate=candidate,
        dest_root=tools,
        expected_task_id=task_id,
    )
    assert materialized["ok"] is True
    assert Path(materialized["input"]).read_text() == "fresh input"
    assert Path(materialized["expected"]).read_text() == "FRESH INPUT"
    assert materialized["candidate_evidence_id"] == (
        candidate_object.truth_evidence.evidence_id
    )
    evidence_record = json.loads(
        (Path(materialized["input"]).parent / "candidate-evidence.json").read_text()
    )
    assert evidence_record["candidate_evidence_id"] == (
        candidate_object.truth_evidence.evidence_id
    )
    assert evidence_record["input_sha256"] == hashlib.sha256(
        b"fresh input"
    ).hexdigest()

    forged = json.loads(json.dumps(candidate))
    forged["input_text"] = "browser-forged"
    rejected = product_jobs.materialize_audit_candidate(
        "demo-tool",
        candidate=forged,
        dest_root=tools,
        expected_task_id=task_id,
    )
    assert rejected["reason_codes"] == [
        "AUDIT_CANDIDATE_MANAGED_EVIDENCE_INVALID"
    ]


def test_review_editor_rejects_non_exact_or_executable_dependency_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    draft = state_root / "drafts" / "draft"
    (draft / "examples").mkdir(parents=True)
    current = _current_editable_draft()
    current["tool"]["summary"] = "Alpha 转换"
    (draft / "draft.yaml").write_text(
        yaml.safe_dump(current),
        encoding="utf-8",
    )
    (draft / "reference_impl.py").write_text("import alpha\n", encoding="utf-8")
    (draft / "examples.yaml").write_text("examples: []\n", encoding="utf-8")

    rejected = product_jobs.save_draft_review(
        draft,
        tool_name="alpha-tool",
        summary="Alpha 转换",
        statement=current["capability"]["statement"],
        input_format="TXT",
        output_format="plain text",
        output_schema="AlphaText",
        reference_impl="import alpha\n",
        reference_lock="alpha>=1\n--extra-index-url https://evil.invalid",
    )

    assert rejected["ok"] is False
    assert "精确版本" in rejected["error"]
    assert not (draft / "reference.lock.txt").exists()


def test_candidate_generation_repairs_to_requested_count_without_resetting_goldens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This test exercises bounded proposal repair, not the platform sandbox.
    # The latter has its own macOS conformance/unsupported-host fail-closed tests.
    monkeypatch.setattr(
        example_proposer,
        "_sandboxed_reference_argv",
        lambda argv, _root: argv,
    )
    state_root = tmp_path / "state"
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    draft = state_root / "drafts" / "draft"
    (draft / "examples" / "inputs").mkdir(parents=True)
    (draft / "examples" / "expected").mkdir()
    document = _current_editable_draft(
        import_module="minishout",
        user_goal="只转换以 good 开头的文本。",
    )
    document["source_repo"].update({
        "url": "https://github.com/acme/minishout",
        "resolved_commit": "a" * 40,
        "distribution": "minishout",
    })
    document["tool"]["summary"] = "转换文本"
    (draft / "draft.yaml").write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (draft / "reference_impl.py").write_text(
        "from pathlib import Path\nimport minishout\n\n"
        "def extract(input_path: Path) -> str:\n"
        "    return minishout.convert(input_path.read_text(encoding='utf-8'))\n",
        encoding="utf-8",
    )
    original_examples = (
        "examples:\n"
        "- input_file: inputs/persisted.txt\n"
        "  expected_file: expected/persisted.expected.txt\n"
    )
    (draft / "examples.yaml").write_text(original_examples, encoding="utf-8")
    (draft / "examples" / "inputs" / "persisted.txt").write_text(
        "good-existing", encoding="utf-8"
    )
    (draft / "examples" / "expected" / "persisted.expected.txt").write_text(
        "GOOD-EXISTING", encoding="utf-8"
    )
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    (upstream / "minishout.py").write_text(
        "def convert(text):\n"
        "    if not text.startswith('good'):\n"
        "        raise ValueError('PRIVATE-REFERENCE-DETAIL /Users/alice/secret.txt')\n"
        "    return text.upper()\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(product_jobs, "_draft_upstream_dir", lambda _draft: (upstream, ""))
    monkeypatch.setattr(
        product_jobs,
        "resolved_dependency_lock",
        lambda *_args, **_kwargs: "minishout==1.0.0\n",
    )
    monkeypatch.setattr(
        example_proposer,
        "prepared_reference_environment",
        lambda _draft, **_kwargs: nullcontext(sys.executable),
    )

    class RepairingDrafter:
        name = "repairing-stub"

        def __init__(self) -> None:
            self.calls = 0
            self.contexts: list[dict] = []

        def propose_example_inputs(self, context: dict) -> dict:
            self.calls += 1
            self.contexts.append(context)
            requested = int(context["how_many"])
            plans = {
                1: ["good-one", "bad-one", "bad-two", "bad-three"],
                2: ["good-two", "good-three", "bad-four"],
                3: ["good-four"],
            }
            values = plans[self.calls]
            assert len(values) == requested
            return {
                "inputs": [
                    {"input_name": "case.txt", "input_text": value, "why": "repair"}
                    for value in values
                ]
            }

    drafter = RepairingDrafter()
    monkeypatch.setattr(tool_drafter, "online_drafter", lambda: drafter)

    result = product_jobs.propose_example_candidates(draft, n=4, offline=False)

    assert result["ok"] is True
    assert result["usable_count"] == 4
    assert result["shortfall"] == 0
    assert result["rejected_count"] == 4
    assert result["rounds"] == 3
    assert result["confirmed_count"] == 1
    assert drafter.calls == 3
    assert "good-existing" not in str(drafter.contexts)
    assert "PRIVATE-REFERENCE-DETAIL" not in str(drafter.contexts)
    assert "/Users/alice/secret.txt" not in str(drafter.contexts)
    assert "bad-one" not in str(drafter.contexts[1:])
    assert all(
        set(failure) == {"reason_code", "failure_fingerprint"}
        for context in drafter.contexts[1:]
        for failure in context["failed_attempts"]
    )
    assert len({row["input_name"] for row in result["candidates"]}) == 8
    assert (draft / "examples.yaml").read_text(encoding="utf-8") == original_examples
    assert (draft / "examples" / "inputs" / "persisted.txt").read_text(
        encoding="utf-8"
    ) == "good-existing"


def test_reference_contract_failure_repairs_draft_controls_not_candidate_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful-but-invalid reference output is an authoring failure.

    The candidate model gets one call. Reference and verifier are repaired in
    isolated contexts, then the same candidate is replayed through both gates.
    """

    monkeypatch.setattr(
        example_proposer,
        "_sandboxed_reference_argv",
        lambda argv, _root: argv,
    )
    monkeypatch.setattr(
        semantic_artifact,
        "offline_sandbox_argv",
        lambda argv, _root: argv,
    )
    state_root = tmp_path / "state"
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    draft = state_root / "drafts" / "draft"
    (draft / "examples").mkdir(parents=True)
    document = _current_editable_draft(
        import_module="minishout",
        user_goal="把这份内容整理一下，给我一份能继续用的文本。",
    )
    document["source_repo"].update({
        "url": "https://github.com/acme/minishout",
        "resolved_commit": "d" * 40,
        "distribution": "minishout",
    })
    document["tool"]["summary"] = "整理本地文本"
    (draft / "draft.yaml").write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (draft / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    (draft / "reference_impl.py").write_text(
        "from pathlib import Path\nimport minishout\n\n"
        "class UserInputError(ValueError):\n    pass\n\n"
        "def extract(input_path: Path) -> str:\n"
        "    return minishout.convert(input_path.read_text(encoding='utf-8')) + '\\x00'\n",
        encoding="utf-8",
    )
    (draft / "semantic_verifier.py").write_text(
        "from pathlib import Path\nimport minishout\n\n"
        "def verify(input_path: Path, artifact_path: Path) -> dict:\n"
        "    expected = minishout.convert(input_path.read_text(encoding='utf-8')) + '\\x00'\n"
        "    ok = artifact_path.read_text(encoding='utf-8') == expected\n"
        "    return {'ok': ok, 'reason_codes': [] if ok else ['TEXT_MISMATCH'], "
        "'checked_commitment_ids': ['transform-input']}\n",
        encoding="utf-8",
    )
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    (upstream / "minishout.py").write_text(
        "def convert(text):\n    return text.upper()\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(product_jobs, "_draft_upstream_dir", lambda _draft: (upstream, ""))
    monkeypatch.setattr(
        product_jobs,
        "resolved_dependency_lock",
        lambda *_args, **_kwargs: "minishout==1.0\n",
    )
    monkeypatch.setattr(
        example_proposer,
        "prepared_reference_environment",
        lambda _draft, **_kwargs: nullcontext(sys.executable),
    )

    class ControlRepairDrafter:
        name = "control-repair-stub"

        def __init__(self) -> None:
            self.propose_calls = 0
            self.reference_context: dict | None = None
            self.verifier_context: dict | None = None

        def propose_example_inputs(self, context: dict) -> dict:
            self.propose_calls += 1
            assert int(context["how_many"]) == 1
            return {
                "inputs": [{
                    "input_name": "case.txt",
                    "input_text": "good-one",
                    "why": "覆盖普通工作输入。",
                }]
            }

        def repair_reference(self, context: dict) -> dict[str, str]:
            self.reference_context = context
            return {
                "reference_impl": (
                    "from pathlib import Path\nimport minishout\n\n"
                    "class UserInputError(ValueError):\n    pass\n\n"
                    "def extract(input_path: Path) -> str:\n"
                    "    return minishout.convert(input_path.read_text(encoding='utf-8'))\n"
                )
            }

        def repair_verifier(self, context: dict) -> dict[str, str]:
            self.verifier_context = context
            return {
                "semantic_verifier": (
                    "from pathlib import Path\nimport minishout\n\n"
                    "def verify(input_path: Path, artifact_path: Path) -> dict:\n"
                    "    expected = minishout.convert(input_path.read_text(encoding='utf-8'))\n"
                    "    ok = artifact_path.read_text(encoding='utf-8') == expected\n"
                    "    return {'ok': ok, 'reason_codes': [] if ok else "
                    "['TEXT_MISMATCH'], 'checked_commitment_ids': ['transform-input']}\n"
                )
            }

    drafter = ControlRepairDrafter()
    monkeypatch.setattr(tool_drafter, "online_drafter", lambda: drafter)

    result = product_jobs.propose_example_candidates(draft, n=1, offline=False)

    assert result["ok"] is True
    assert result["usable_count"] == 1
    assert result["rounds"] == 1
    assert [event["reason_code"] for event in result["control_repairs"]] == [
        "REFERENCE_OUTPUT_CONTRACT_MISMATCH",
        "REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT",
    ]
    assert drafter.propose_calls == 1
    assert drafter.reference_context is not None
    assert drafter.verifier_context is not None
    assert drafter.reference_context["artifact_protocol"]["observations"]
    assert drafter.verifier_context["artifact_protocol"]["observations"]
    assert "current_reference_impl" in drafter.reference_context
    assert "current_semantic_verifier" not in drafter.reference_context
    assert "current_semantic_verifier" in drafter.verifier_context
    assert "current_reference_impl" not in drafter.verifier_context
    assert "good-one" not in str(drafter.reference_context)
    assert "good-one" not in str(drafter.verifier_context)
    assert "\\x00" not in (draft / "reference_impl.py").read_text(encoding="utf-8")
    assert "\\x00" not in (draft / "semantic_verifier.py").read_text(encoding="utf-8")
    assert (draft / "reference.lock.txt").read_text(encoding="utf-8") == (
        "minishout==1.0\n"
    )


def test_output_contract_repair_diagnostics_expose_shape_not_values() -> None:
    diagnostics = product_jobs._public_output_contract_diagnostics(
        ["ris: line=1 invalid_tag"],
        output_text="123.\nTY  - SECRET-CANDIDATE-VALUE\n",
    )

    assert "invalid_line_shape[1]=0." in diagnostics
    assert "SECRET" not in " ".join(diagnostics)
    assert "CANDIDATE" not in " ".join(diagnostics)


def test_uniform_internal_reference_failure_is_not_candidate_repair() -> None:
    batch = example_proposer.ProposalBatch(
        candidates=[
            example_proposer.CandidateExample(
                input_name=f"case-{index}.txt",
                input_text=f"public-{index}",
                why="公开候选",
                upstream_error="TypeError: private details are not projected",
            )
            for index in range(3)
        ]
    )

    failure = product_jobs._reference_batch_control_failure(batch)

    assert failure is not None
    assert failure.owner == "CONTRACT"
    assert failure.reason_codes == ["REFERENCE_IMPLEMENTATION_EXECUTION_FAILED"]
    assert failure.diagnostics == ("all_candidates_exception_type=TypeError",)
    assert "private" not in str(failure.diagnostics)


def test_contract_valid_reference_semantic_rejection_is_control_disagreement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = tmp_path / "semantic_verifier.py"
    verifier.write_text(
        "from pathlib import Path\n"
        "def verify(input_path: Path, artifact_path: Path) -> dict:\n"
        "    return {'ok': False, 'reason_codes': ['SEMANTIC_MISMATCH'], "
        "'checked_commitment_ids': ['transform-input']}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        semantic_artifact,
        "screen_semantic_candidate",
        lambda **_kwargs: SimpleNamespace(
            mechanism_ok=True,
            passed=False,
            reason_codes=("SEMANTIC_MISMATCH",),
        ),
    )
    candidate = example_proposer.CandidateExample(
        input_name="case.txt",
        input_text="private-candidate-body",
        upstream_output="contract-valid text\n",
    )

    with pytest.raises(product_jobs._CandidateAdmissionError) as raised:
        product_jobs._admit_candidate_pair(
            candidate,
            output_contract={
                "media_type": "text/plain",
                "root_type": "text",
                "required": {},
                "validation_profile": "plain_text_v1",
            },
            semantic_verifier=verifier,
            required_commitment_ids=("transform-input",),
            reference_python=sys.executable,
            upstream=tmp_path,
            import_module="alpha",
        )

    assert raised.value.reason_codes == [
        "REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"
    ]
    assert raised.value.diagnostics == ("SEMANTIC_MISMATCH",)
    assert "private-candidate-body" not in str(raised.value.diagnostics)


def test_untyped_pinned_literals_are_hints_never_direct_candidate_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        example_proposer,
        "_sandboxed_reference_argv",
        lambda argv, _root: argv,
    )
    state_root = tmp_path / "state"
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    draft = state_root / "drafts" / "draft"
    (draft / "examples").mkdir(parents=True)
    document = _current_editable_draft(
        import_module="minishout",
        user_goal="只转换 good 输入。",
    )
    document["source_repo"].update({
        "url": "https://github.com/acme/minishout",
        "resolved_commit": "b" * 40,
        "distribution": "minishout",
    })
    (draft / "draft.yaml").write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (draft / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    (draft / "reference_impl.py").write_text(
        "from pathlib import Path\nimport minishout\n\n"
        "def extract(input_path: Path) -> str:\n"
        "    return minishout.convert(input_path.read_text(encoding='utf-8'))\n",
        encoding="utf-8",
    )
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    (upstream / "minishout.py").write_text(
        "def convert(text):\n"
        "    if not text.startswith('good'):\n"
        "        raise ValueError('bad input')\n"
        "    return text.upper()\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(product_jobs, "_draft_upstream_dir", lambda _draft: (upstream, ""))
    monkeypatch.setattr(
        product_jobs,
        "resolved_dependency_lock",
        lambda *_args, **_kwargs: "minishout==1.0.0\n",
    )
    monkeypatch.setattr(
        example_proposer,
        "prepared_reference_environment",
        lambda _draft, **_kwargs: nullcontext(sys.executable),
    )
    monkeypatch.setattr(
        example_proposer,
        "mine_evidence_literals",
        lambda *_args, **_kwargs: ["good-evidence-2", "good-evidence-3"],
    )

    class TwoRoundDrafter:
        name = "two-round-stub"

        def __init__(self) -> None:
            self.calls = 0
            self.contexts: list[dict] = []

        def propose_example_inputs(self, context: dict) -> dict:
            self.calls += 1
            self.contexts.append(context)
            if self.calls == 1:
                values = ["good-model", "bad-one", "bad-two"]
            else:
                values = ["good-modeled-two", "good-modeled-three"]
            assert len(values) == int(context["how_many"])
            return {"inputs": [
                {"input_name": f"case-{index}.txt", "input_text": value, "why": ""}
                for index, value in enumerate(values, start=1)
            ]}

    drafter = TwoRoundDrafter()
    monkeypatch.setattr(tool_drafter, "online_drafter", lambda: drafter)

    result = product_jobs.propose_example_candidates(draft, n=3, offline=False)

    assert result["ok"] is True
    assert result["usable_count"] == 3
    assert result["shortfall"] == 0
    assert result["rounds"] == 2
    assert result["evidence_probes"] == 0
    assert drafter.calls == 2
    assert drafter.contexts[0]["evidence_literals"] == [
        "good-evidence-2",
        "good-evidence-3",
    ]
    returned_inputs = {row["input_text"] for row in result["candidates"]}
    assert "good-evidence-2" not in returned_inputs
    assert "good-evidence-3" not in returned_inputs
    assert (draft / "examples.yaml").read_text(encoding="utf-8") == "examples: []\n"


def test_candidate_reference_environment_failure_is_zero_model_and_owned_by_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    draft = state_root / "drafts" / "draft"
    (draft / "examples").mkdir(parents=True)
    document = _current_editable_draft(
        import_module="feed",
        user_goal="解析一个本地 feed。",
    )
    document["source_repo"].update({
        "url": "https://github.com/acme/feed",
        "resolved_commit": "c" * 40,
        "distribution": "feed",
    })
    document["tool"]["interface"]["input"]["format"] = "RSS"
    document["_intent_contract"]["delivery"]["requirements"]["inputs"][0][
        "format_label"
    ] = "RSS"
    (draft / "draft.yaml").write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (draft / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    (draft / "reference_impl.py").write_text(
        "from pathlib import Path\n\ndef extract(path: Path) -> str:\n    return path.read_text()\n",
        encoding="utf-8",
    )
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    monkeypatch.setattr(product_jobs, "_draft_upstream_dir", lambda _draft: (upstream, ""))
    monkeypatch.setattr(
        product_jobs,
        "resolved_dependency_lock",
        lambda *_args, **_kwargs: "feed==1.0.0\n",
    )

    class BrokenEnvironment:
        def __enter__(self):
            raise example_proposer.ReferenceEnvironmentError("missing transitive wheel")

        def __exit__(self, *_args):
            return False

    environment_kwargs: dict = {}

    def broken_environment(_draft, **kwargs):
        environment_kwargs.update(kwargs)
        return BrokenEnvironment()

    monkeypatch.setattr(
        example_proposer,
        "prepared_reference_environment",
        broken_environment,
    )
    monkeypatch.setattr(
        tool_drafter,
        "online_drafter",
        lambda: pytest.fail("environment failure must stop before an LLM is selected"),
    )

    result = product_jobs.propose_example_candidates(draft, n=4, offline=False)

    assert result["ok"] is False
    assert result["failure_owner"] == "HARNESS"
    assert result["reason_codes"] == ["REFERENCE_ENVIRONMENT_SETUP_FAILED"]
    assert "没有调用模型" in result["recommended_action"]
    assert "missing transitive wheel" not in result["error"]
    assert str(tmp_path) not in result["error"]
    assert environment_kwargs["resolved_lock_text"] == "feed==1.0.0\n"


def test_candidate_missing_dependency_lock_stops_before_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    draft = state_root / "drafts" / "draft"
    (draft / "examples").mkdir(parents=True)
    document = _current_editable_draft(import_module="feed")
    (draft / "draft.yaml").write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (draft / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    (draft / "reference_impl.py").write_text(
        "from pathlib import Path\nimport feed\n\n"
        "def extract(path: Path) -> str:\n    return feed.convert(path.read_text())\n",
        encoding="utf-8",
    )
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    monkeypatch.setattr(product_jobs, "_draft_upstream_dir", lambda _draft: (upstream, ""))
    monkeypatch.setattr(
        product_jobs,
        "resolved_dependency_lock",
        lambda *_args, **_kwargs: "",
    )
    monkeypatch.setattr(
        tool_drafter,
        "online_drafter",
        lambda: pytest.fail("missing dependency lock must stop before model"),
    )

    result = product_jobs.propose_example_candidates(draft, n=4, offline=False)

    assert result["ok"] is False
    assert result["failure_owner"] == "HARNESS"
    assert result["reason_codes"] == ["DEPENDENCY_LOCK_MISSING"]
    assert "没有调用模型" in result["recommended_action"]


def test_binary_candidate_generation_routes_to_real_file_upload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    draft = state_root / "drafts" / "binary"
    (draft / "examples").mkdir(parents=True)
    document = _current_editable_draft(user_goal="整理一个本地输入文件。")
    document["tool"]["interface"]["input"]["format"] = "opaque capture"
    document["_intent_contract"]["delivery"]["requirements"]["inputs"][0][
        "format_label"
    ] = "opaque capture"
    document["_intent_contract"]["delivery"]["requirements"]["inputs"][0][
        "representation"
    ] = "binary"
    (draft / "draft.yaml").write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (draft / "examples.yaml").write_text(
        "# 起草层建议(仅建议;真值文件归人放置):\n"
        "#   - 上传一个带标题和表格的文档。(exact_file)\n"
        "examples: []\n",
        encoding="utf-8",
    )
    (draft / "reference_impl.py").write_text(
        "from pathlib import Path\n\ndef extract(input_path: Path) -> str:\n    return input_path.name\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        product_jobs,
        "_draft_upstream_dir",
        lambda _draft: pytest.fail("binary guidance must not prepare or run upstream"),
    )

    result = product_jobs.propose_example_candidates(draft, n=4, offline=False)

    assert result["ok"] is True
    assert result["manual_upload_required"] is True
    assert result["rounds"] == 0
    assert result["candidates"] == []
    assert result["suggestions"] == ["上传一个带标题和表格的文档。"]
    assert "不会把模型文本伪装成真实文件" in result["note"]


def test_example_input_mode_never_inferrs_representation_from_format_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    draft = state_root / "drafts" / "typed-text"
    (draft / "examples").mkdir(parents=True)
    document = _current_editable_draft(user_goal="处理一个本地输入文件。")
    document["tool"]["interface"]["input"]["format"] = "DOCX"
    document["_intent_contract"]["delivery"]["requirements"]["inputs"][0][
        "format_label"
    ] = "DOCX"
    # The typed contract, not the label, is authoritative.
    document["_intent_contract"]["delivery"]["requirements"]["inputs"][0][
        "representation"
    ] = "utf8_text"
    (draft / "draft.yaml").write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    result = product_jobs.example_input_mode(draft)

    assert result["ok"] is True
    assert result["representation"] == "utf8_text"
    assert result["requires_upload"] is False


def test_example_input_mode_fails_closed_for_untyped_legacy_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    draft = state_root / "drafts" / "legacy"
    draft.mkdir(parents=True)
    (draft / "draft.yaml").write_text(
        "tool:\n  schema_version: 2\n  interface:\n"
        "    input: {kind: file, format: PDF}\n",
        encoding="utf-8",
    )

    result = product_jobs.example_input_mode(draft)

    assert result["ok"] is False
    assert result["failure_owner"] == "CONTRACT"
    assert result["reason_codes"] == ["TYPED_INPUT_REPRESENTATION_UNAVAILABLE"]


def test_activity_log_reader_never_follows_untrusted_state_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    logs = state_root / "logs"
    logs.mkdir(parents=True)
    valid = logs / "tool-build.log"
    valid.write_text("safe log\n", encoding="utf-8")
    assert product_jobs.read_product_job_log({"log": str(valid)}) == {
        "ok": True,
        "text": "safe log\n",
    }

    outside = tmp_path / "secret.txt"
    outside.write_text("must not render\n", encoding="utf-8")
    blocked = product_jobs.read_product_job_log({"log": str(outside)})
    assert blocked["ok"] is False
    assert "受管目录" in blocked["error"]

    linked = logs / "linked.log"
    linked.symlink_to(outside)
    blocked = product_jobs.read_product_job_log({"log": str(linked)})
    assert blocked["ok"] is False


def test_product_paths_and_github_url_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "draft.yaml").write_text("{}\n", encoding="utf-8")

    escaped = product_jobs.start_tool_add(
        repo="https://github.com/acme/demo",
        capability="把公开能力包装为本地离线工具",
        draft_dir=outside / "new-draft",
        fake_drafter=True,
    )
    assert escaped["ok"] is False
    assert "受管目录" in escaped["error"]

    drafts = state_root / "drafts"
    drafts.mkdir(parents=True)
    linked = drafts / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    linked_result = product_jobs.save_draft_review(
        linked,
        tool_name="alpha-tool",
        summary="summary",
        statement="statement",
        input_format="text",
        output_format="text",
        output_schema="text",
        reference_impl="",
    )
    assert linked_result["ok"] is False
    assert "symlink" in linked_result["error"]

    spoofed = product_jobs.start_tool_add(
        repo="https://github.com.evil.example/acme/demo",
        capability="把公开能力包装为本地离线工具",
        draft_dir=drafts / "spoofed",
        fake_drafter=True,
    )
    assert spoofed["ok"] is False
    assert "公开 GitHub" in spoofed["error"]

    broad, broad_error = product_jobs._validated_dest_root(Path.home())
    assert broad is None
    assert "过于宽泛" in str(broad_error)


def test_build_reports_invalid_task_version_lineage_without_starting_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    draft = state_root / "drafts" / "draft"
    (draft / "examples").mkdir(parents=True)
    (draft / "draft.yaml").write_text(
        yaml.safe_dump({"tool": {"name": "alpha-tool"}}),
        encoding="utf-8",
    )
    (draft / "reference_impl.py").write_text("", encoding="utf-8")
    (draft / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    monkeypatch.setattr(
        product_jobs,
        "_core_draft_readiness",
        lambda *_args, **_kwargs: SimpleNamespace(ready=True),
    )
    monkeypatch.setattr(
        product_jobs,
        "next_tool_task_id",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("malformed task version anchor")
        ),
    )
    monkeypatch.setattr(
        product_jobs,
        "_start_product_job",
        lambda *_args, **_kwargs: pytest.fail("worker must not start"),
    )

    result = product_jobs.start_tool_build(
        draft_dir=draft,
        dest_root=tmp_path / "tools",
        rehearsal_only=True,
    )

    assert result["ok"] is False
    assert result["error_code"] == "TASK_VERSION_LINEAGE_INVALID"


def _all_text(at) -> str:
    values: list[str] = []
    for kind in (
        "title", "header", "subheader", "markdown", "caption", "info",
        "success", "warning", "error", "metric", "button", "selectbox",
        "text_input", "text_area",
    ):
        for element in getattr(at, kind, []):
            values.append(str(getattr(element, "value", "")))
            values.append(str(getattr(element, "label", "")))
    return "\n".join(values)


@needs_streamlit
@pytest.mark.parametrize(
    ("page", "marker"),
    [
        ("product_home.py", "GitHub 能力"),
        ("tool_onboarding.py", "从一句需求开始"),
        ("product_activity.py", "每一步都看得见"),
        ("tool_library.py", "AI Tool Library"),
        ("trust_dashboard.py", "成功率不是唯一答案"),
    ],
)
def test_product_pages_render_without_user_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, page: str, marker: str,
) -> None:
    monkeypatch.setenv("REPOPROOF_TOOL_ROOT", str(tmp_path / "tools"))
    monkeypatch.setenv("REPOPROOF_UI_STATE_ROOT", str(tmp_path / "state"))
    at = AppTest.from_file(str(PAGES / page), default_timeout=30)
    at.run()
    assert not at.exception
    assert marker in _all_text(at)


@needs_streamlit
def test_library_shows_historical_and_operational_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _tool_world(tmp_path)
    monkeypatch.setenv("REPOPROOF_TOOL_ROOT", str(tools))
    monkeypatch.setenv("REPOPROOF_UI_STATE_ROOT", str(tmp_path / "state"))
    at = AppTest.from_file(str(PAGES / "tool_library.py"), default_timeout=30)
    at.run()
    assert not at.exception
    text = _all_text(at)
    assert "alpha-tool" in text
    assert "VERIFIED_TOOL_READY" in text
    assert "待审核" in text


def _audit_library(root: Path, *identities: tuple[str, str]) -> dict:
    tools = []
    for index, (name, task_id) in enumerate(identities):
        package = root / name
        package.mkdir(parents=True, exist_ok=True)
        tools.append({
            "name": name,
            "summary": f"{name} summary",
            "operational_status": "REVIEW_REQUIRED",
            "historical_verdict": "VERIFIED_TOOL_READY",
            "health": "OK",
            "reason_codes": [],
            "source_distribution": name,
            "source_url": f"https://github.com/example/{name}",
            "resolved_commit": str(index + 1) * 40,
            "path": str(package),
            "task_id": task_id,
            "run_id": f"run-{name}",
            "contract_sha256": chr(ord("a") + index) * 64,
        })
    return {
        "root": str(root),
        "tools": tools,
        "registry_error": None,
        "release_error": None,
    }


@needs_streamlit
def test_library_fresh_audit_session_state_isolated_by_full_tool_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Switching tools cannot reuse another task/root's candidates or text fields."""

    from repoproof.ui.services import product_mode

    root = tmp_path / "tools"
    library = _audit_library(
        root,
        ("alpha-tool", "tool-alpha-tool-v1"),
        ("beta-tool", "tool-beta-tool-v2"),
    )
    monkeypatch.setattr(product_mode, "list_tools", lambda *_a, **_k: library)
    monkeypatch.setattr(product_jobs, "product_tool_commands", lambda: {"audit"})
    calls: list[tuple[str, str, str]] = []

    def _propose(
        name: str,
        *,
        dest_root: Path,
        expected_task_id: str,
        n: int,
        offline: bool,
    ) -> dict:
        assert n == 5
        assert offline is False
        calls.append((name, expected_task_id, str(dest_root.resolve())))
        return {
            "ok": True,
            "tool_name": name,
            "task_id": expected_task_id,
            "dest_root": str(dest_root.resolve()),
            "candidates": [{
                "input_name": f"{name}.txt",
                "input_text": f"fresh input for {name}",
                "expected": f"expected output for {name}",
            }],
        }

    monkeypatch.setattr(product_jobs, "propose_audit_candidates", _propose)
    monkeypatch.setattr(
        product_jobs,
        "materialize_audit_pair",
        lambda *_args, **_kwargs: {
            "ok": True,
            "input": str(tmp_path / "fresh.txt"),
            "expected": str(tmp_path / "expected.txt"),
        },
    )
    audit_starts: list[tuple[str, str, str]] = []

    def _start_audit(
        name: str,
        _input_path: Path,
        _expected_path: Path,
        dest_root: Path,
        *,
        expected_task_id: str,
        journey_id: str = "",
    ) -> dict:
        assert journey_id == ""
        audit_starts.append((name, expected_task_id, str(dest_root.resolve())))
        return {"ok": False, "error": "captured without launching worker"}

    monkeypatch.setattr(product_jobs, "start_tool_audit", _start_audit)
    at = AppTest.from_file(str(PAGES / "tool_library.py"), default_timeout=30).run()

    next(button for button in at.button if button.label == "给我候选").click().run()
    assert any("fresh input for alpha-tool" in str(code.value) for code in at.code)
    next(button for button in at.button if button.label == "用这一条").click().run()
    alpha_input = next(
        field for field in at.text_area if field.label.startswith("输入内容")
    )
    assert alpha_input.value == "fresh input for alpha-tool"

    next(box for box in at.selectbox if box.label == "查看工具详情").select("beta-tool").run()
    assert not any("fresh input for alpha-tool" in str(code.value) for code in at.code)
    beta_input = next(
        field for field in at.text_area if field.label.startswith("输入内容")
    )
    assert beta_input.value == ""

    next(button for button in at.button if button.label == "给我候选").click().run()
    next(button for button in at.button if button.label == "用这一条").click().run()
    beta_input = next(
        field for field in at.text_area if field.label.startswith("输入内容")
    )
    assert beta_input.value == "fresh input for beta-tool"

    next(box for box in at.selectbox if box.label == "查看工具详情").select("alpha-tool").run()
    alpha_input = next(
        field for field in at.text_area if field.label.startswith("输入内容")
    )
    assert alpha_input.value == "fresh input for alpha-tool"
    assert calls == [
        ("alpha-tool", "tool-alpha-tool-v1", str(root.resolve())),
        ("beta-tool", "tool-beta-tool-v2", str(root.resolve())),
    ]
    next(button for button in at.button if button.label == "运行新输入抽查").click().run()
    assert audit_starts == [
        ("alpha-tool", "tool-alpha-tool-v1", str(root.resolve()))
    ]


@needs_streamlit
def test_library_rejects_fresh_audit_candidates_with_mismatched_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful-looking service response cannot cross task identity boundaries."""

    from repoproof.ui.services import product_mode

    root = tmp_path / "tools"
    library = _audit_library(root, ("alpha-tool", "tool-alpha-tool-v1"))
    monkeypatch.setattr(product_mode, "list_tools", lambda *_a, **_k: library)
    monkeypatch.setattr(product_jobs, "product_tool_commands", lambda: {"audit"})
    monkeypatch.setattr(
        product_jobs,
        "propose_audit_candidates",
        lambda name, **_kwargs: {
            "ok": True,
            "tool_name": name,
            "task_id": "tool-alpha-tool-v999",
            "dest_root": str(root.resolve()),
            "candidates": [{
                "input_name": "wrong.txt",
                "input_text": "must not render",
                "expected": "must not become truth",
            }],
        },
    )
    at = AppTest.from_file(str(PAGES / "tool_library.py"), default_timeout=30).run()

    next(button for button in at.button if button.label == "给我候选").click().run()

    assert any("候选属于另一个工具、任务版本或工具根目录" in str(e.value) for e in at.error)
    assert not any(button.label == "用这一条" for button in at.button)
    assert not any("must not render" in str(code.value) for code in at.code)


def test_navigation_keeps_product_and_benchmark_apps_separate() -> None:
    ui = REPO / "src" / "repoproof" / "ui"
    product_source = (ui / "app.py").read_text(encoding="utf-8")
    lab_source = (ui / "lab_app.py").read_text(encoding="utf-8")
    for title in ("工作台", "新建工具", "运行活动", "工具库", "可信仪表盘"):
        assert title in product_source
        assert title not in lab_source
    for title in ("开始新任务", "宿主任务 T1–T4", "结果报告", "历史记录", "系统设置"):
        assert title in lab_source
        assert title not in product_source
    assert "Benchmark Lab" not in product_source
    assert "product_theme" not in lab_source


def test_runtime_services_have_separate_state_domains() -> None:
    services = REPO / "src" / "repoproof" / "ui" / "services"
    lab_source = (services / "live_run.py").read_text(encoding="utf-8")
    product_source = (services / "product_jobs.py").read_text(encoding="utf-8")
    assert "product_job_state" not in lab_source
    assert "product_mode" not in lab_source
    assert "runs/.ui_live.lock" not in product_source
    assert "benchmarks/" not in product_source
    assert "docs/evidence" not in product_source


def test_public_launchers_use_distinct_apps_and_ports() -> None:
    scripts = REPO / "scripts"
    product = (scripts / "run_ui.sh").read_text(encoding="utf-8")
    product_live = (scripts / "run_ui_live.sh").read_text(encoding="utf-8")
    lab = (scripts / "run_lab_ui.sh").read_text(encoding="utf-8")
    lab_live = (scripts / "run_lab_ui_live.sh").read_text(encoding="utf-8")
    assert "ui/app.py" in product and "--server.port 8501" in product
    assert "ui/app.py" in product_live and "--server.port 8501" in product_live
    assert "REPOPROOF_TEMPERATURE_POLICY" in product
    assert "provider_default" in product
    assert "REPOPROOF_TEMPERATURE_POLICY" in product_live
    assert "ui/lab_app.py" in lab and "--server.port 8502" in lab
    assert "ui/lab_app.py" in lab_live and "--server.port 8502" in lab_live
    assert "lab_app.py" not in product and "ui/app.py" not in lab


@needs_streamlit
def test_navigation_entrypoint_accepts_all_icons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPOPROOF_TOOL_ROOT", str(tmp_path / "tools"))
    monkeypatch.setenv("REPOPROOF_UI_STATE_ROOT", str(tmp_path / "state"))
    at = AppTest.from_file(str(REPO / "src" / "repoproof" / "ui" / "app.py"))
    at.run()
    assert not at.exception


@needs_streamlit
def test_benchmark_lab_entrypoint_renders_independently() -> None:
    at = AppTest.from_file(
        str(REPO / "src" / "repoproof" / "ui" / "lab_app.py"),
        default_timeout=30,
    )
    at.run()
    assert not at.exception
    assert "把一个开源仓库的能力" in _all_text(at)


def test_inline_audit_material_is_written_byte_for_byte(tmp_path, monkeypatch):
    """抽查可以「直接填内容」,且**逐字节原样落盘**。

    2026-08-28 实录:抽查两个字段原来只收**路径**,用户很自然地直接填了
    值(`#000080` / `navy`),只得到一句"文件必须存在" —— 界面要什么、人给
    什么对不上时,该由界面兼容,而不是让人猜。
    判据是逐字节比对,所以这里不许悄悄补尾换行:补一个 \\n 就会让一次
    本该通过的抽查莫名其妙失败。
    """
    from repoproof.ui.services import product_jobs

    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: tmp_path)
    got = product_jobs.materialize_audit_pair("demo-tool", "navy", '{"a":1}')
    assert got["ok"], got
    assert Path(got["input"]).read_text(encoding="utf-8") == "navy"      # 无尾换行
    assert Path(got["expected"]).read_text(encoding="utf-8") == '{"a":1}'


def test_inline_audit_rejects_empty_material(tmp_path, monkeypatch):
    """**负控**:空输入/空期望不成其为抽查 —— 当场拒绝。"""
    from repoproof.ui.services import product_jobs

    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: tmp_path)
    assert not product_jobs.materialize_audit_pair("demo-tool", "  ", "x")["ok"]
    assert not product_jobs.materialize_audit_pair("demo-tool", "x", "")["ok"]


def test_audit_expectation_never_comes_from_the_tool_under_test(monkeypatch, tmp_path):
    """**红线**:抽查的期望值来自**冻结的参考实现**,不是被测工具自己。

    用户提的需求是"我不一定知道期望输出,别让我从零创造"。可以帮 —— 但
    帮法有红线:若期望值取自被测工具的输出,抽查就成了自证,永远通过,
    也就永远抓不出 pyspellchecker 那类 false-success(声明 JSON、实际
    输出纯文本,一路绿到运营态)。

    这里钉的是**取值来源**:实现里必须跑 controls/<task>/reference/impl.py
    (按纪律真 import 钉版上游),而不是 ~/tools 下的交付物。
    """
    import inspect

    from repoproof.ui.services import product_jobs

    src = inspect.getsource(product_jobs.propose_audit_candidates)
    assert "controls" in src and "reference" in src, "期望值必须取自冻结参考实现"
    assert "run_reference_on_candidates" in src
    # 不许出现"跑被测工具"的取值路径
    for forbidden in ("tool_root(", "bin/", "install_verified_tool"):
        assert forbidden not in src, f"抽查期望值不得来自被测工具({forbidden})"


def test_audit_proposal_refuses_without_a_frozen_reference(monkeypatch, tmp_path):
    """**负控**:没有冻结参考实现 = 没有独立真值源 → 如实拒绝,不拿工具凑数。"""
    from repoproof.ui.services import product_jobs

    tool_dir = tmp_path / "tools" / "ghost-tool"
    tool_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "repoproof.ui.services.product_mode.list_tools",
        lambda *a, **k: {"tools": [{"name": "ghost-tool", "task_id": "tool-ghost-v1",
                                    "summary": "x", "resolved_commit": "0" * 40,
                                    "path": str(tool_dir), "health": "OK"}],
                         "root": str(tmp_path / "tools"),
                         "registry_error": None, "release_error": None},
    )
    got = product_jobs.propose_audit_candidates(
        "ghost-tool",
        dest_root=tmp_path / "tools",
        expected_task_id="tool-ghost-v1",
        n=2,
        offline=True,
    )
    assert not got["ok"]
    assert got["reason_codes"] == ["REFERENCE_IDENTITY_MISMATCH"]
    assert "reference" in got["error"]


def _reference_bound_audit_world(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Path, Path, Path, dict[str, str]]:
    """Create only the package/control identity seam needed before any model call."""

    tools = tmp_path / "tools"
    tool_dir = tools / "demo-tool"
    evidence = tool_dir / "evidence"
    evidence.mkdir(parents=True)
    reference = tmp_path / "controls" / "tool-demo-tool-v1" / "reference"
    reference.mkdir(parents=True)
    impl = reference / "impl.py"
    lock = reference / "requirements.lock.txt"
    impl.write_text("def extract(path):\n    return path.read_text()\n", encoding="utf-8")
    lock.write_text("demo==1.0\n", encoding="utf-8")
    identity = {
        "impl_sha256": hashlib.sha256(impl.read_bytes()).hexdigest(),
        "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
    }
    (evidence / "provenance.json").write_text(
        json.dumps(
            {
                "tool": "demo-tool",
                "task_id": "tool-demo-tool-v1",
                "reference_identity": identity,
            }
        ),
        encoding="utf-8",
    )
    entry = {
        "name": "demo-tool",
        "task_id": "tool-demo-tool-v1",
        "path": str(tool_dir),
        "health": "OK",
        "resolved_commit": "a" * 40,
        "reference_identity": identity,
    }
    monkeypatch.setattr(
        "repoproof.ui.services.product_mode.list_tools",
        lambda *a, **k: {
            "tools": [entry],
            "root": str(tools),
            "registry_error": None,
            "release_error": None,
        },
    )
    monkeypatch.setattr(
        "repoproof.ui.services.product_mode.project_root", lambda: tmp_path
    )
    monkeypatch.setattr(
        "repoproof.adoption.intake.tool_drafter.online_drafter",
        lambda: pytest.fail("reference mismatch must stop before model selection"),
    )
    return tools, impl, lock, identity


def test_audit_proposal_rejects_reference_content_mismatch_before_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from repoproof.ui.services import product_jobs

    tools, impl, _lock, _identity = _reference_bound_audit_world(
        monkeypatch, tmp_path
    )
    impl.write_text("def extract(path):\n    return 'changed'\n", encoding="utf-8")

    got = product_jobs.propose_audit_candidates(
        "demo-tool",
        dest_root=tools,
        expected_task_id="tool-demo-tool-v1",
        offline=False,
    )
    assert not got["ok"]
    assert got["reason_codes"] == ["REFERENCE_IDENTITY_MISMATCH"]


def test_audit_proposal_rejects_symlinked_reference_before_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from repoproof.ui.services import product_jobs

    tools, impl, _lock, _identity = _reference_bound_audit_world(
        monkeypatch, tmp_path
    )
    outside = tmp_path / "outside-reference.py"
    outside.write_text("def extract(path):\n    return 'outside'\n", encoding="utf-8")
    impl.unlink()
    impl.symlink_to(outside)

    got = product_jobs.propose_audit_candidates(
        "demo-tool",
        dest_root=tools,
        expected_task_id="tool-demo-tool-v1",
        offline=False,
    )
    assert not got["ok"]
    assert got["reason_codes"] == ["REFERENCE_IDENTITY_MISMATCH"]


def test_audit_proposal_refuses_a_different_current_task(monkeypatch, tmp_path):
    """A Journey cannot borrow truth from another version of the same tool."""
    from repoproof.ui.services import product_jobs

    monkeypatch.setattr(
        "repoproof.ui.services.product_mode.list_tools",
        lambda *a, **k: {
            "tools": [{"name": "demo-tool", "task_id": "tool-demo-tool-v2",
                       "health": "OK"}],
            "root": str(tmp_path / "tools"),
            "registry_error": None,
            "release_error": None,
        },
    )
    got = product_jobs.propose_audit_candidates(
        "demo-tool",
        dest_root=tmp_path / "tools",
        expected_task_id="tool-demo-tool-v1",
        offline=True,
    )
    assert not got["ok"]
    assert got["reason_codes"] == ["TASK_IDENTITY_MISMATCH"]
    assert "另一个版本" in got["error"]


def test_public_example_inputs_are_exactly_the_agent_visible_inputs(tmp_path):
    """Fresh generation sees public inputs, never expected or escaping files."""
    from repoproof.ui.services import product_jobs

    tool_dir = tmp_path / "demo-tool"
    fixtures = tool_dir / "public_examples" / "inputs"
    fixtures.mkdir(parents=True)
    (fixtures / "one.txt").write_text("already seen", encoding="utf-8")
    (fixtures / "one.expected.txt").write_text("secret expected", encoding="utf-8")
    truth = tool_dir / "public_examples" / "truth_table.json"
    truth.parent.mkdir(exist_ok=True)
    truth.write_text(
        json.dumps({
            "examples": [{
                "input_file": "one.txt",
                "expected_file": "one.expected.txt",
            }]
        }),
        encoding="utf-8",
    )

    texts, names = product_jobs._public_example_inputs(tool_dir)
    assert texts == ["already seen"]
    assert names == ["one.txt"]


def test_public_example_inputs_fail_closed_for_legacy_export(tmp_path):
    """Old packages must be re-exported; skeleton fallback would split freshness truth."""
    from repoproof.ui.services import product_jobs

    tool_dir = tmp_path / "demo-tool"
    truth = tool_dir / "public_examples" / "truth_table.json"
    truth.parent.mkdir(parents=True)
    truth.write_text(
        json.dumps({"examples": [{"input_file": "one.txt"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="旧导出格式"):
        product_jobs._public_example_inputs(tool_dir)


def test_verify_pinned_upstream_tree_rejects_head_or_tracked_drift(tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    subprocess.run(["git", "init", "-q", str(upstream)], check=True)
    subprocess.run(
        ["git", "-C", str(upstream), "config", "user.email", "test@example.test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(upstream), "config", "user.name", "RepoProof Test"],
        check=True,
    )
    tracked = upstream / "tracked.txt"
    tracked.write_text("frozen\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(upstream), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(upstream), "commit", "-qm", "fixture"], check=True)
    head = subprocess.run(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    product_jobs._verify_pinned_upstream_tree(upstream, head)
    with pytest.raises(ValueError, match="HEAD"):
        product_jobs._verify_pinned_upstream_tree(upstream, "0" * 40)
    tracked.write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="漂移"):
        product_jobs._verify_pinned_upstream_tree(upstream, head)
    subprocess.run(
        ["git", "-C", str(upstream), "checkout", "--", "tracked.txt"],
        check=True,
    )
    (upstream / "unexpected.py").write_text("raise RuntimeError\n", encoding="utf-8")
    with pytest.raises(ValueError, match="未跟踪内容漂移"):
        product_jobs._verify_pinned_upstream_tree(upstream, head)
