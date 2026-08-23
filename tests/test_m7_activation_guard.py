"""M7 managed-sidecar release stays fail-closed before its trust gates close."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from repoproof.runner.tool_mcp import _runtime_identity_files, write_mcp_server
from repoproof.runner.tool_registry import list_tools, register_tool
from repoproof.runner.tool_release import (
    ACTIVE,
    MANAGED_SIDECAR_TRUST_PENDING,
    RELEASE_LEDGER_NAME,
    REVIEW_REQUIRED,
    append_release_decision,
    audit_tool,
    fold_release_decisions,
    fold_release_statuses,
    load_release_decisions,
    operational_status,
)

_WHEN = "2026-08-24T00:00:00Z"


def _installed_tool(root: Path, name: str, *, schema_version: int) -> Path:
    tool_dir = root / name
    package = name.replace("-", "_")
    package_dir = tool_dir / "src" / package
    (tool_dir / "bin").mkdir(parents=True)
    (tool_dir / "evidence").mkdir()
    package_dir.mkdir(parents=True)
    launcher = tool_dir / "bin" / name
    launcher.write_text("#!/bin/sh\ncat \"$1\"\n", encoding="utf-8")
    launcher.chmod(0o755)
    for filename in (
        "__init__.py",
        "__main__.py",
        "main.py",
        "impl.py",
        "sidecar_server.py",
        "sidecar_supervisor.py",
        "sidecar_contract.py",
    ):
        (package_dir / filename).write_text(
            f"# fixed fixture: {filename}\n", encoding="utf-8"
        )
    (package_dir / "protocol.json").write_text(
        '{"protocol":"repoproof-http-sidecar-v1"}\n', encoding="utf-8"
    )
    (tool_dir / ".venv" / "bin").mkdir(parents=True)
    (tool_dir / ".venv" / "bin" / "python").write_text(
        "opaque generated runtime\n", encoding="utf-8"
    )
    manifest = {
        "manifest_version": 1,
        "contract_schema_version": schema_version,
        "name": name,
        "version": "1.0.0",
        "summary": "managed-sidecar activation guard fixture",
        "source": {
            "url": "https://example.invalid/upstream",
            "resolved_commit": "a" * 40,
            "license": "MIT",
            "distribution": "fixture",
        },
        "interface": {
            "usage": f"{name} <input>",
            "input": {"kind": "file", "format": "text"},
            "output": {
                "kind": "stdout",
                "format": "text",
                "contract": {
                    "media_type": "text/plain",
                    "root_type": "text",
                    "required": {},
                },
            },
            "exit_codes": {"0": "success", "1": "user", "2": "internal"},
        },
        "runtime": {"python": "3.12", "cpu_only": True, "offline": True},
        "verification": {
            "verdict": "VERIFIED_TOOL_READY",
            "run_id": f"run-{name}",
            "contract_sha256": "c" * 64,
        },
    }
    if schema_version == 3:
        manifest["runtime"]["delivery"] = {
            "mode": "http_sidecar",
            "profile_id": "tool-http-sidecar-v1",
            "lifecycle": "per_invocation",
            "credentials": "none",
            "network": "loopback_only",
            "protocol": "repoproof-http-sidecar-v1",
        }
    (tool_dir / "tool.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
    )
    (tool_dir / "evidence" / "provenance.json").write_text(
        json.dumps(
            {
                "tool": name,
                "task_id": f"tool-{name}-v1",
                "run_id": f"run-{name}",
                "tool_contract_sha256": "c" * 64,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    register_tool(root, tool_dir, run_id=f"run-{name}", exported_at=_WHEN)
    return tool_dir


def _active_row(name: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "tool": name,
        "task_id": f"tool-{name}-v1",
        "run_id": f"run-{name}",
        "decision": ACTIVE,
        "reason_code": "FORGED_OR_STALE_ACTIVE",
        "reason": "A syntactically valid stale decision used by the guard test.",
        "evidence_sha256": "d" * 64,
        "decided_at": _WHEN,
        "actor": "operator",
    }


def test_forged_and_stale_active_cannot_promote_managed_sidecar(
    tmp_path: Path,
) -> None:
    name = "sidecar-guard"
    tool_dir = _installed_tool(tmp_path, name, schema_version=3)
    appended = append_release_decision(
        tmp_path,
        tool=name,
        task_id=f"tool-{name}-v1",
        run_id=f"run-{name}",
        decision=ACTIVE,
        reason_code="FORGED_ACTIVE",
        reason="attempted activation",
        evidence_sha256="0" * 64,
        decided_at=_WHEN,
        actor="operator",
    )
    assert appended["decision"] == REVIEW_REQUIRED
    assert appended["reason_code"] == MANAGED_SIDECAR_TRUST_PENDING

    # Simulate an ACTIVE row written by an older build that predates this
    # guard.  Raw history remains append-only; every current consumer projects
    # the managed runtime back to REVIEW_REQUIRED.
    ledger = tmp_path / RELEASE_LEDGER_NAME
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_active_row(name), sort_keys=True) + "\n")
    assert fold_release_decisions(tmp_path)[name]["decision"] == ACTIVE
    assert operational_status(tmp_path, name) == REVIEW_REQUIRED

    listed = list_tools(tmp_path)[0]
    assert listed["historical_verdict"] == "VERIFIED_TOOL_READY"
    assert listed["operational_status"] == REVIEW_REQUIRED
    assert listed["operational_reason_code"] == MANAGED_SIDECAR_TRUST_PENDING
    assert listed["managed_sidecar_trust_pending"] is True
    assert tool_dir.exists()

    # The package cannot escape its append-only trust ceiling by rewriting
    # the mutable manifest to look like v2 after registration.
    manifest_path = tool_dir / "tool.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["contract_schema_version"] = 2
    manifest["runtime"].pop("delivery")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert operational_status(tmp_path, name) == REVIEW_REQUIRED
    assert fold_release_statuses(tmp_path)[name] == REVIEW_REQUIRED
    downgraded = list_tools(tmp_path)[0]
    assert downgraded["operational_status"] == REVIEW_REQUIRED
    assert downgraded["operational_reason_code"] == MANAGED_SIDECAR_TRUST_PENDING
    with pytest.raises(RuntimeError, match="operational_status=REVIEW_REQUIRED"):
        write_mcp_server(tool_dir)

    # Rewriting provenance to a fabricated new task cannot evade the marker:
    # the current registry identity still binds the installed task.
    provenance_path = tool_dir / "evidence" / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["task_id"] = f"tool-{name}-v2"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    forged_task = _active_row(name)
    forged_task["task_id"] = f"tool-{name}-v2"
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(forged_task, sort_keys=True) + "\n")
    assert operational_status(
        tmp_path, name, task_id=f"tool-{name}-v2"
    ) == REVIEW_REQUIRED
    forged = list_tools(tmp_path)[0]
    assert forged["status"] == "INVALID_IDENTITY"
    assert forged["operational_status"] == REVIEW_REQUIRED


def test_managed_trust_marker_is_task_scoped_for_future_real_upgrades(
    tmp_path: Path,
) -> None:
    name = "sidecar-versioned"
    append_release_decision(
        tmp_path,
        tool=name,
        task_id=f"tool-{name}-v1",
        run_id="run-v1",
        decision=REVIEW_REQUIRED,
        reason_code=MANAGED_SIDECAR_TRUST_PENDING,
        reason="v1 managed runtime remains pending",
        evidence_sha256="a" * 64,
        decided_at=_WHEN,
        actor="operator",
    )
    append_release_decision(
        tmp_path,
        tool=name,
        task_id=f"tool-{name}-v2",
        run_id="run-v2",
        decision=ACTIVE,
        reason_code="FRESH_INPUT_PASS",
        reason="a separately installed future task passed its own gates",
        evidence_sha256="b" * 64,
        decided_at="2026-08-24T00:00:01Z",
        actor="operator",
    )
    assert operational_status(
        tmp_path, name, task_id=f"tool-{name}-v2"
    ) == ACTIVE


def test_damaged_managed_manifest_cannot_revive_active_ledger(
    tmp_path: Path,
) -> None:
    name = "sidecar-damaged"
    tool_dir = _installed_tool(tmp_path, name, schema_version=3)
    ledger = tmp_path / RELEASE_LEDGER_NAME
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_active_row(name), sort_keys=True) + "\n")
    assert load_release_decisions(tmp_path)[-1]["decision"] == ACTIVE

    (tool_dir / "tool.json").write_text("{damaged\n", encoding="utf-8")
    assert operational_status(tmp_path, name) == REVIEW_REQUIRED
    assert fold_release_statuses(tmp_path)[name] == REVIEW_REQUIRED
    listed = list_tools(tmp_path)[0]
    assert listed["status"] == "INVALID_IDENTITY"
    assert listed["operational_status"] == REVIEW_REQUIRED

    attempted = append_release_decision(
        tmp_path,
        tool=name,
        task_id=f"tool-{name}-v1",
        run_id=f"run-{name}",
        decision=ACTIVE,
        reason_code="ATTEMPTED_REACTIVATION",
        reason="damaged package must fail closed",
        evidence_sha256="e" * 64,
        decided_at=_WHEN,
        actor="operator",
    )
    assert attempted["decision"] == REVIEW_REQUIRED
    assert attempted["reason_code"] == "INVALID_PACKAGE_IDENTITY"


def test_fresh_audit_pass_stays_review_required_without_rewriting_history(
    tmp_path: Path,
) -> None:
    name = "sidecar-audit"
    _installed_tool(tmp_path, name, schema_version=3)
    audit_input = tmp_path / "fresh-input.txt"
    expected = tmp_path / "fresh-expected.txt"
    audit_input.write_text("fresh\n", encoding="utf-8")
    expected.write_text("fresh\n", encoding="utf-8")

    result = audit_tool(
        tmp_path,
        name,
        input_path=audit_input,
        expected_file=expected,
    )
    assert result["ok"] is False
    assert result["operational_status"] == REVIEW_REQUIRED
    assert result["reason_code"] == MANAGED_SIDECAR_TRUST_PENDING
    assert result["historical_verdict"] == "VERIFIED_TOOL_READY"
    assert operational_status(tmp_path, name) == REVIEW_REQUIRED


def test_managed_sidecar_mcp_generation_is_blocked_even_with_stale_active(
    tmp_path: Path,
) -> None:
    name = "sidecar-mcp"
    tool_dir = _installed_tool(tmp_path, name, schema_version=3)
    ledger = tmp_path / RELEASE_LEDGER_NAME
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_active_row(name), sort_keys=True) + "\n")

    with pytest.raises(RuntimeError, match=MANAGED_SIDECAR_TRUST_PENDING):
        write_mcp_server(tool_dir)
    assert not (tool_dir / "mcp_server.py").exists()


def test_runtime_identity_covers_fixed_chain_and_non_python_source_resources(
    tmp_path: Path,
) -> None:
    name = "sidecar-identity"
    tool_dir = _installed_tool(tmp_path, name, schema_version=3)
    identity = _runtime_identity_files(tool_dir, name)
    package = "sidecar_identity"
    for relative in (
        f"src/{package}/__init__.py",
        f"src/{package}/__main__.py",
        f"src/{package}/main.py",
        f"src/{package}/sidecar_server.py",
        f"src/{package}/sidecar_supervisor.py",
        f"src/{package}/sidecar_contract.py",
        f"src/{package}/protocol.json",
    ):
        assert relative in identity
    assert all(not relative.startswith(".venv/") for relative in identity)

    resource = tool_dir / "src" / package / "protocol.json"
    before = identity[f"src/{package}/protocol.json"]
    resource.write_text('{"protocol":"drifted"}\n', encoding="utf-8")
    after = _runtime_identity_files(tool_dir, name)
    assert after[f"src/{package}/protocol.json"] != before

    (tool_dir / "src" / package / "__main__.py").unlink()
    with pytest.raises(RuntimeError, match="fixed entry chain"):
        _runtime_identity_files(tool_dir, name)

    # A later symlink must be rejected, not silently filtered from the file set.
    (tool_dir / "src" / package / "__main__.py").write_text(
        "# restored fixture\n", encoding="utf-8"
    )
    outside = tmp_path / "outside-resource.json"
    outside.write_text('{"outside":true}\n', encoding="utf-8")
    (tool_dir / "src" / package / "late-resource.json").symlink_to(outside)
    with pytest.raises(RuntimeError, match="unsafe entries"):
        _runtime_identity_files(tool_dir, name)


def test_v2_mcp_runtime_rejects_non_python_source_drift(tmp_path: Path) -> None:
    name = "legacy-identity"
    tool_dir = _installed_tool(tmp_path, name, schema_version=2)
    append_release_decision(
        tmp_path,
        tool=name,
        task_id=f"tool-{name}-v1",
        run_id=f"run-{name}",
        decision=ACTIVE,
        reason_code="FRESH_INPUT_PASS",
        reason="legacy fixture activation",
        evidence_sha256="1" * 64,
        decided_at=_WHEN,
        actor="operator",
    )
    server = write_mcp_server(tool_dir)
    resource = tool_dir / "src" / "legacy_identity" / "protocol.json"
    resource.write_text('{"protocol":"drifted"}\n', encoding="utf-8")
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    completed = subprocess.run(
        [sys.executable, str(server)],
        input=json.dumps(request) + "\n",
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    response = json.loads(completed.stdout)
    assert "managed package identity changed" in response["error"]["message"]

    resource.write_text(
        '{"protocol":"repoproof-http-sidecar-v1"}\n', encoding="utf-8"
    )
    outside = tmp_path / "late-resource.json"
    outside.write_text('{"late":true}\n', encoding="utf-8")
    (tool_dir / "src" / "legacy_identity" / "late-resource.json").symlink_to(
        outside
    )
    completed = subprocess.run(
        [sys.executable, str(server)],
        input=json.dumps(request) + "\n",
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    response = json.loads(completed.stdout)
    assert "managed package identity changed" in response["error"]["message"]
