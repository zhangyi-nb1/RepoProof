"""M6 Product Mode alignment with M5 Core facts and contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from repoproof.runner import tool_registry
from repoproof.runner.tool_release import append_release_decision
from repoproof.ui.services import product_mode


def _register_ready_tool(dest_root: Path) -> Path:
    name = "alpha-tool"
    task_id = "tool-alpha-tool-v1"
    run_id = "tool-alpha-tool-v1-20260824-000000"
    contract_sha256 = "b" * 64
    package = dest_root / name
    (package / "evidence").mkdir(parents=True)
    manifest = {
        "name": name,
        "summary": "Normalize Alpha text",
        "source": {
            "url": "https://github.com/acme/alpha",
            "distribution": "alpha",
            "resolved_commit": "a" * 40,
        },
        "verification": {
            "verdict": "VERIFIED_TOOL_READY",
            "run_id": run_id,
            "contract_sha256": contract_sha256,
        },
    }
    provenance = {
        "tool": name,
        "task_id": task_id,
        "run_id": run_id,
        "tool_contract_sha256": contract_sha256,
    }
    (package / "tool.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (package / "evidence" / "provenance.json").write_text(
        json.dumps(provenance), encoding="utf-8"
    )
    tool_registry.register_tool(
        dest_root,
        package,
        run_id=run_id,
        exported_at="2026-08-24T00:00:00Z",
    )
    return package


def _write_structured_draft(draft_dir: Path, *, golden: str) -> None:
    (draft_dir / "examples" / "inputs").mkdir(parents=True)
    (draft_dir / "examples" / "expected").mkdir(parents=True)
    (draft_dir / "examples" / "inputs" / "alpha.txt").write_text(
        "alpha", encoding="utf-8"
    )
    (draft_dir / "examples" / "expected" / "alpha.json").write_text(
        golden, encoding="utf-8"
    )
    draft = {
        "tool": {
            "schema_version": 2,
            "name": "alpha-tool",
            "summary": "Normalize Alpha text",
            "interface": {
                "usage": "alpha-tool <input> [--out FILE]",
                "input": {"kind": "file", "format": "TXT"},
                "output": {
                    "kind": "stdout",
                    "format": "JSON object",
                    "contract": {
                        "media_type": "application/json",
                        "root_type": "object",
                        "required": {"normalized": "string"},
                    },
                },
                "exit_codes": {
                    "0": "success",
                    "1": "user input error",
                    "2": "internal error",
                },
            },
        }
    }
    examples = {
        "examples": [
            {
                "input_file": "inputs/alpha.txt",
                "expected_file": "expected/alpha.json",
            }
        ]
    }
    (draft_dir / "draft.yaml").write_text(
        yaml.safe_dump(draft, sort_keys=False), encoding="utf-8"
    )
    (draft_dir / "examples.yaml").write_text(
        yaml.safe_dump(examples, sort_keys=False), encoding="utf-8"
    )


def test_tool_projection_delegates_to_core_without_scan(
    tmp_path: Path, monkeypatch,
) -> None:
    calls: list[tuple[Path, bool]] = []

    def fake_list_tools(root: Path, *, scan: bool) -> list[dict]:
        calls.append((root, scan))
        return []

    monkeypatch.setattr(product_mode.tool_registry, "list_tools", fake_list_tools)
    assert product_mode.list_tools(tmp_path)["tools"] == []
    assert calls == [(tmp_path, False)]


def test_unregistered_package_directory_is_not_discovered(tmp_path: Path) -> None:
    package = tmp_path / "unregistered"
    package.mkdir()
    (package / "tool.json").write_text(
        json.dumps({"name": "unregistered"}), encoding="utf-8"
    )
    assert product_mode.list_tools(tmp_path)["tools"] == []
    assert not (tmp_path / product_mode.REGISTRY_NAME).exists()


def test_invalid_release_ledger_fails_closed_with_reason_code(tmp_path: Path) -> None:
    _register_ready_tool(tmp_path)
    ledger = tmp_path / product_mode.RELEASE_LEDGER_NAME
    with ledger.open("a", encoding="utf-8") as stream:
        stream.write('{"decision":"ACTIVE"}\n')

    result = product_mode.list_tools(tmp_path)
    assert result["tools"] == []
    assert result["release_error"]
    assert result["projection_errors"][0]["reason_code"] == "RELEASE_LEDGER_INVALID"


def test_package_identity_damage_keeps_history_but_fails_closed(tmp_path: Path) -> None:
    package = _register_ready_tool(tmp_path)
    provenance_path = package / "evidence" / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["run_id"] = "tampered"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")

    row = product_mode.list_tools(tmp_path)["tools"][0]
    assert row["historical_verdict"] == "VERIFIED_TOOL_READY"
    assert row["health"] == "INVALID_IDENTITY"
    assert row["operational_status"] == "REVIEW_REQUIRED"
    assert row["operational_reason_code"] == "INVALID_PACKAGE_IDENTITY"


def test_missing_manifest_overrides_a_stale_active_decision(tmp_path: Path) -> None:
    package = _register_ready_tool(tmp_path)
    append_release_decision(
        tmp_path,
        tool="alpha-tool",
        task_id="tool-alpha-tool-v1",
        run_id="tool-alpha-tool-v1-20260824-000000",
        decision="ACTIVE",
        reason_code="FRESH_INPUT_PASS",
        reason="Independent fresh-input audit passed.",
        evidence_sha256="c" * 64,
        actor="operator",
    )
    (package / "tool.json").unlink()

    row = product_mode.list_tools(tmp_path)["tools"][0]
    assert row["health"] == "MISSING"
    assert row["operational_status"] == "REVIEW_REQUIRED"
    assert row["operational_reason_code"] == "PACKAGE_MISSING"


def test_core_unverified_package_overrides_stale_active_decision(
    tmp_path: Path,
) -> None:
    package = _register_ready_tool(tmp_path)
    append_release_decision(
        tmp_path,
        tool="alpha-tool",
        task_id="tool-alpha-tool-v1",
        run_id="tool-alpha-tool-v1-20260824-000000",
        decision="ACTIVE",
        reason_code="FRESH_INPUT_PASS",
        reason="Independent fresh-input audit passed.",
        evidence_sha256="c" * 64,
        actor="operator",
    )
    manifest_path = package / "tool.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["verification"]["verdict"] = "FAIL"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    core_row = tool_registry.list_tools(tmp_path, scan=False)[0]
    assert core_row["status"] == "UNVERIFIED"
    assert core_row["operational_status"] == "REVIEW_REQUIRED"
    assert (
        core_row["operational_reason_code"]
        == "HISTORICAL_VERIFICATION_NOT_READY"
    )
    assert product_mode.list_tools(tmp_path)["tools"][0][
        "operational_reason_code"
    ] == "HISTORICAL_VERIFICATION_NOT_READY"


def test_core_reason_code_is_shown_without_rewriting_history(tmp_path: Path) -> None:
    _register_ready_tool(tmp_path)
    append_release_decision(
        tmp_path,
        tool="alpha-tool",
        task_id="tool-alpha-tool-v1",
        run_id="tool-alpha-tool-v1-20260824-000000",
        decision="ACTIVE",
        reason_code="FRESH_INPUT_PASS",
        reason="Independent fresh-input audit passed.",
        evidence_sha256="c" * 64,
        actor="operator",
    )

    row = product_mode.list_tools(tmp_path)["tools"][0]
    assert row["historical_verdict"] == "VERIFIED_TOOL_READY"
    assert row["operational_status"] == "ACTIVE"
    assert row["operational_reason_code"] == "FRESH_INPUT_PASS"


def test_task_version_and_legacy_mcp_reason_codes_remain_visible(
    tmp_path: Path,
) -> None:
    package = _register_ready_tool(tmp_path)
    append_release_decision(
        tmp_path,
        tool="alpha-tool",
        task_id="tool-alpha-tool-v2",
        run_id="tool-alpha-tool-v2-20260823-000000",
        decision="ACTIVE",
        reason_code="FRESH_INPUT_PASS",
        reason="Previous task version passed an audit.",
        evidence_sha256="c" * 64,
        actor="operator",
    )
    (package / "mcp_server.py").write_text(
        "# legacy server without runtime release enforcement\n",
        encoding="utf-8",
    )

    row = product_mode.list_tools(tmp_path)["tools"][0]
    assert row["historical_verdict"] == "VERIFIED_TOOL_READY"
    assert row["operational_status"] == "REVIEW_REQUIRED"
    assert row["operational_reason_code"] == "TASK_VERSION_UNAUDITED"
    assert row["reason_codes"] == [
        "TASK_VERSION_UNAUDITED",
        "LEGACY_SERVER_MUST_BE_DETACHED",
    ]
    dashboard = product_mode.dashboard_snapshot(tmp_path, tmp_path)
    assert dashboard["operational_reason_codes"] == {
        "LEGACY_SERVER_MUST_BE_DETACHED": 1,
        "TASK_VERSION_UNAUDITED": 1,
    }


def test_text_default_is_a_complete_tool_output_contract() -> None:
    default = product_mode.default_output_contract("plain text")
    assert default == {
        "media_type": "text/plain",
        "root_type": "text",
        "required": {},
    }
    parsed, errors = product_mode.parse_output_contract(
        default, output_format="TXT"
    )
    assert errors == []
    assert parsed is not None and parsed.root_type == "text"


def test_output_contract_rejects_human_and_machine_format_split() -> None:
    parsed, errors = product_mode.parse_output_contract(
        {"media_type": "text/plain", "root_type": "text", "required": {}},
        output_format="JSON object",
    )
    assert parsed is None
    assert errors[0].startswith("OUTPUT_CONTRACT_FORMAT_MISMATCH")


def test_structured_golden_uses_core_validator_before_build(tmp_path: Path) -> None:
    valid = tmp_path / "valid"
    _write_structured_draft(valid, golden='{"normalized":"ALPHA"}\n')
    assert product_mode.validate_draft_output_examples(valid)["ok"] is True

    invalid = tmp_path / "invalid"
    _write_structured_draft(invalid, golden="ALPHA\n")
    result = product_mode.validate_draft_output_examples(invalid)
    assert result["ok"] is False
    assert any(
        error.startswith("GOLDEN_OUTPUT_INVALID: example=1 document: invalid_json")
        for error in result["errors"]
    )


def test_structured_contains_only_example_is_not_an_exact_golden(tmp_path: Path) -> None:
    _write_structured_draft(tmp_path, golden='{"normalized":"ALPHA"}')
    (tmp_path / "examples.yaml").write_text(
        yaml.safe_dump(
            {
                "examples": [
                    {"input": "alpha.txt", "expected": 'contains:"normalized"'}
                ]
            }
        ),
        encoding="utf-8",
    )
    result = product_mode.validate_draft_output_examples(tmp_path)
    assert result["ok"] is False
    assert "EXACT_STRUCTURED_GOLDEN_MISSING" in "\n".join(result["errors"])


def test_task_version_preview_is_read_only_and_assembler_owned(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    frozen = contracts / "tool-alpha-tool-v1.yaml"
    frozen.write_text("historical: frozen\n", encoding="utf-8")

    preview = product_mode.next_task_version_preview("alpha-tool", tmp_path)
    assert preview == {
        "task_id": "tool-alpha-tool-v2",
        "authority": "assemble_tool_task",
        "note": "只读预览；最终版本由装配器在冻结时重新分配。",
    }
    assert frozen.read_text(encoding="utf-8") == "historical: frozen\n"
    assert sorted(path.name for path in contracts.iterdir()) == [frozen.name]


def test_task_version_preview_never_reuses_sparse_or_orphaned_history(
    tmp_path: Path,
) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "tool-alpha-tool-v2.yaml").write_text("historical: sparse\n")
    assert product_mode.next_task_version_preview("alpha-tool", tmp_path)[
        "task_id"
    ] == "tool-alpha-tool-v3"

    (contracts / "tool-alpha-tool-v5.package.json").write_text("{}\n")
    assert product_mode.next_task_version_preview("alpha-tool", tmp_path)[
        "task_id"
    ] == "tool-alpha-tool-v6"

    (contracts / "tool-alpha-tool-vX.yaml").write_text("malformed: true\n")
    with pytest.raises(ValueError, match="malformed task version anchor"):
        product_mode.next_task_version_preview("alpha-tool", tmp_path)
