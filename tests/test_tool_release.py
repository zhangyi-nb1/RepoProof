"""RFC-011 M5-c/d: release ledger, audit, migration, and consumers."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from repoproof.cli import main
from repoproof.runner.tool_mcp import write_mcp_server
from repoproof.runner.tool_registry import list_tools, register_tool
from repoproof.runner.tool_release import (
    ACTIVE,
    RELEASE_LEDGER_NAME,
    REVIEW_REQUIRED,
    REVOKED,
    ReleaseLedgerError,
    ToolAuditError,
    append_release_decision,
    audit_tool,
    fold_release_statuses,
    import_audit_decisions,
    load_release_decisions,
    operational_status,
    withdraw_tool,
)

_ZERO_HASH = "0" * 64
_WHEN = "2026-08-23T00:00:00Z"


def _fake_tool(dest: Path, name: str, *, verified: bool = True, contract: dict | None = None) -> Path:
    tool_dir = dest / name
    (tool_dir / "bin").mkdir(parents=True)
    (tool_dir / "evidence").mkdir()
    executable = tool_dir / "bin" / name
    executable.write_text("#!/bin/sh\ncat \"$1\"\n", encoding="utf-8")
    executable.chmod(0o755)
    output = {"kind": "stdout", "format": "TXT"}
    if contract is not None:
        output["contract"] = contract
    manifest = {
        "manifest_version": 1,
        "name": name,
        "version": "1.0.0",
        "summary": "test tool",
        "source": {"url": "u", "resolved_commit": "c", "license": "MIT", "distribution": "d"},
        "interface": {
            "usage": f"{name} <input>",
            "input": {"kind": "file", "format": "TXT"},
            "output": output,
            "exit_codes": {"0": "success", "1": "user", "2": "internal"},
        },
        "verification": (
            {"verdict": "VERIFIED_TOOL_READY", "run_id": f"run-{name}", "contract_sha256": "abc"}
            if verified
            else None
        ),
    }
    (tool_dir / "tool.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tool_dir / "evidence" / "provenance.json").write_text(
        json.dumps(
            {
                "tool": name,
                "task_id": f"tool-{name}-v1",
                "run_id": f"run-{name}",
                "tool_contract_sha256": "abc",
            }
        ),
        encoding="utf-8",
    )
    return tool_dir


def _append(dest: Path, name: str, decision: str, *, reason_code: str = "TEST") -> dict:
    return append_release_decision(
        dest,
        tool=name,
        task_id=f"tool-{name}-v1",
        run_id=f"run-{name}",
        decision=decision,
        reason_code=reason_code,
        reason="test decision",
        evidence_sha256=_ZERO_HASH,
        decided_at=_WHEN,
        actor="operator",
    )


def test_append_only_fold_and_absence_is_never_active(tmp_path: Path) -> None:
    assert operational_status(tmp_path, "alpha") == REVIEW_REQUIRED
    _append(tmp_path, "alpha", REVIEW_REQUIRED)
    first_bytes = (tmp_path / RELEASE_LEDGER_NAME).read_bytes()
    _append(tmp_path, "alpha", ACTIVE)
    final_bytes = (tmp_path / RELEASE_LEDGER_NAME).read_bytes()

    assert final_bytes.startswith(first_bytes)
    assert len(load_release_decisions(tmp_path)) == 2
    assert fold_release_statuses(tmp_path) == {"alpha": ACTIVE}


def test_damaged_ledger_fails_closed_for_read_and_append(tmp_path: Path) -> None:
    _append(tmp_path, "alpha", ACTIVE)
    ledger = tmp_path / RELEASE_LEDGER_NAME
    ledger.write_bytes(ledger.read_bytes() + b"{damaged\n")

    with pytest.raises(ReleaseLedgerError, match="损坏 JSON"):
        load_release_decisions(tmp_path)
    before = ledger.read_bytes()
    with pytest.raises(ReleaseLedgerError):
        _append(tmp_path, "beta", ACTIVE)
    assert ledger.read_bytes() == before


@pytest.mark.parametrize("number", ["NaN", "1e400"])
def test_nonfinite_json_number_makes_release_ledger_untrusted(
    tmp_path: Path, number: str
) -> None:
    row = _append(tmp_path, "alpha", ACTIVE)
    ledger = tmp_path / RELEASE_LEDGER_NAME
    encoded = json.dumps(row, separators=(",", ":"))
    ledger.write_text(
        encoded[:-1] + f',"extra":{number}}}\n', encoding="utf-8"
    )

    with pytest.raises(ReleaseLedgerError, match="损坏 JSON"):
        load_release_decisions(tmp_path)
    with pytest.raises(ReleaseLedgerError, match="损坏 JSON"):
        _append(tmp_path, "beta", ACTIVE)


def test_register_adds_review_once_and_never_overrides_active(tmp_path: Path) -> None:
    tool_dir = _fake_tool(tmp_path, "alpha")
    register_tool(tmp_path, tool_dir, run_id="run-alpha", exported_at=_WHEN)
    assert operational_status(tmp_path, "alpha") == REVIEW_REQUIRED
    assert len(load_release_decisions(tmp_path)) == 1

    _append(tmp_path, "alpha", ACTIVE)
    register_tool(tmp_path, tool_dir, run_id="run-alpha", exported_at=_WHEN)
    assert operational_status(tmp_path, "alpha") == ACTIVE
    assert len(load_release_decisions(tmp_path)) == 2

    row = list_tools(tmp_path)[0]
    assert row["historical_verdict"] == "VERIFIED_TOOL_READY"
    assert row["operational_status"] == ACTIVE


def test_register_rejects_nonready_manifest_before_writing_state(tmp_path: Path) -> None:
    tool_dir = _fake_tool(tmp_path, "failed", verified=False)
    with pytest.raises(ValueError, match="VERIFIED_TOOL_READY"):
        register_tool(tmp_path, tool_dir, run_id="run-failed", exported_at=_WHEN)
    assert not (tmp_path / RELEASE_LEDGER_NAME).exists()
    assert not (tmp_path / ".repoproof-registry.json").exists()


def test_register_rejects_unsafe_in_place_task_version_rewrite(tmp_path: Path) -> None:
    tool_dir = _fake_tool(tmp_path, "alpha")
    register_tool(tmp_path, tool_dir, run_id="run-alpha", exported_at=_WHEN)
    _append(tmp_path, "alpha", ACTIVE)
    assert operational_status(
        tmp_path, "alpha", task_id="tool-alpha-v1") == ACTIVE

    # A new task version must pass through the staging/archive installer.  A
    # caller cannot manufacture an upgrade by editing provenance in place.
    (tool_dir / "evidence" / "provenance.json").write_text(
        json.dumps({"task_id": "tool-alpha-v2"}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="provenance|identity|installer"):
        register_tool(tmp_path, tool_dir, run_id="run-alpha-v2", exported_at=_WHEN)

    assert [row["decision"] for row in load_release_decisions(tmp_path)] == [
        REVIEW_REQUIRED,
        ACTIVE,
    ]
    registry = json.loads(
        (tmp_path / ".repoproof-registry.json").read_text(encoding="utf-8")
    )["tools"]["alpha"]
    assert registry["task_id"] == "tool-alpha-v1"


def test_register_rejects_fully_consistent_forged_upgrade_without_installer(
    tmp_path: Path,
) -> None:
    tool_dir = _fake_tool(tmp_path, "alpha")
    register_tool(tmp_path, tool_dir, run_id="run-alpha", exported_at=_WHEN)
    registry_before = (tmp_path / ".repoproof-registry.json").read_bytes()
    manifest_path = tool_dir / "tool.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["verification"]["run_id"] = "run-alpha-v2"
    manifest["verification"]["contract_sha256"] = "def"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (tool_dir / "evidence" / "provenance.json").write_text(
        json.dumps(
            {
                "tool": "alpha",
                "task_id": "tool-alpha-v2",
                "run_id": "run-alpha-v2",
                "tool_contract_sha256": "def",
                "replaces": {
                    "task_id": "tool-alpha-v1",
                    "run_id": "run-alpha",
                    "contract_sha256": "abc",
                    "archive_path": ".repoproof-versions/alpha/forged",
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="受管 installer"):
        register_tool(
            tmp_path,
            tool_dir,
            run_id="run-alpha-v2",
            exported_at=_WHEN,
        )

    assert (tmp_path / ".repoproof-registry.json").read_bytes() == registry_before


def test_scan_backfills_index_but_does_not_forge_active_decision(tmp_path: Path) -> None:
    _fake_tool(tmp_path, "scanned")
    rows = list_tools(tmp_path, scan=True)

    assert rows[0]["status"] == "OK"
    assert rows[0]["historical_verdict"] == "VERIFIED_TOOL_READY"
    assert rows[0]["operational_status"] == REVIEW_REQUIRED
    assert not (tmp_path / RELEASE_LEDGER_NAME).exists()


def test_scan_does_not_index_path_like_manifest_name(tmp_path: Path) -> None:
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "tool.json").write_text(
        json.dumps({
            "name": "../escape",
            "verification": {"verdict": "VERIFIED_TOOL_READY"},
        }),
        encoding="utf-8",
    )

    assert list_tools(tmp_path, scan=True) == []
    registry = json.loads(
        (tmp_path / ".repoproof-registry.json").read_text(encoding="utf-8")
    )
    assert registry["tools"] == {}


def test_old_registry_entry_remains_readable_with_dual_status(tmp_path: Path) -> None:
    tool_dir = _fake_tool(tmp_path, "legacy")
    (tmp_path / ".repoproof-registry.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tools": {
                    "legacy": {
                        "path": str(tool_dir),
                        "run_id": "run-legacy",
                        "verdict": "VERIFIED_TOOL_READY",
                        "exported_at": None,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    row = list_tools(tmp_path)[0]
    assert row["status"] == "OK"
    assert row["historical_verdict"] == "VERIFIED_TOOL_READY"
    assert row["operational_status"] == REVIEW_REQUIRED


def test_list_never_reads_registry_path_outside_managed_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    managed = tmp_path / "managed"
    managed.mkdir()
    outside = _fake_tool(tmp_path, "outside")
    (managed / ".repoproof-registry.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tools": {
                    "alpha": {
                        "path": str(outside),
                        "task_id": "tool-alpha-v1",
                        "run_id": "run-alpha",
                        "verdict": "VERIFIED_TOOL_READY",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    protected = {
        outside / "tool.json",
        outside / "evidence" / "provenance.json",
        outside / "mcp_server.py",
    }
    original_read_text = Path.read_text

    def reject_external_read(path: Path, *args: object, **kwargs: object) -> str:
        if path in protected:
            raise AssertionError(f"list attempted external read: {path}")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", reject_external_read)
    row = list_tools(managed)[0]

    assert row["status"] == "INVALID_PATH"
    assert row["historical_verdict"] == "VERIFIED_TOOL_READY"
    assert row["operational_status"] == REVIEW_REQUIRED
    assert row["operational_reason_code"] == "INVALID_REGISTRY_PATH"


def test_mcp_requires_active_and_does_not_delete_existing_server_on_revoke(tmp_path: Path) -> None:
    tool_dir = _fake_tool(tmp_path, "echoer")
    with pytest.raises(RuntimeError, match="REVIEW_REQUIRED"):
        write_mcp_server(tool_dir)

    _append(tmp_path, "echoer", ACTIVE)
    server = write_mcp_server(tool_dir)
    assert server.is_file()
    listed_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }
    listed_proc = subprocess.run(
        [sys.executable, str(server)],
        input=json.dumps(listed_request) + "\n",
        capture_output=True,
        text=True,
        check=True,
    )
    tool_definition = json.loads(listed_proc.stdout)["result"]["tools"][0]
    assert "outputSchema" not in tool_definition, "v1 manifest 不伪造结构化输出合同"

    _append(tmp_path, "echoer", REVOKED)
    with pytest.raises(RuntimeError, match="REVOKED"):
        write_mcp_server(tool_dir)
    assert server.is_file()
    listed = list_tools(tmp_path, scan=True)[0]
    assert listed["mcp_runtime_release_enforced"] is True
    assert "mcp_exposure_warning" not in listed


def test_generated_mcp_fails_closed_on_runtime_damaged_ledger(tmp_path: Path) -> None:
    tool_dir = _fake_tool(tmp_path, "echoer")
    _append(tmp_path, "echoer", ACTIVE)
    server = write_mcp_server(tool_dir)
    ledger = tmp_path / RELEASE_LEDGER_NAME
    ledger.write_bytes(ledger.read_bytes() + b'{"extra":NaN}\n')

    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }
    proc = subprocess.run(
        [sys.executable, str(server)],
        input=json.dumps(request) + "\n",
        capture_output=True,
        text=True,
        check=True,
    )
    reply = json.loads(proc.stdout)
    assert reply["error"] == {
        "code": -32001,
        "message": "release ledger schema invalid",
    }


def test_generated_mcp_rejects_path_like_tool_in_later_release_row(
    tmp_path: Path,
) -> None:
    tool_dir = _fake_tool(tmp_path, "echoer")
    active = _append(tmp_path, "echoer", ACTIVE)
    server = write_mcp_server(tool_dir)
    damaged = {**active, "tool": "../outside"}
    ledger = tmp_path / RELEASE_LEDGER_NAME
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(damaged, separators=(",", ":")) + "\n")

    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }
    proc = subprocess.run(
        [sys.executable, str(server)],
        input=json.dumps(request) + "\n",
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(proc.stdout)["error"] == {
        "code": -32001,
        "message": "release ledger schema invalid",
    }


def test_release_and_mcp_paths_reject_dest_root_traversal(tmp_path: Path) -> None:
    managed = tmp_path / "managed"
    outside_tool = _fake_tool(tmp_path, "outside")
    outside_manifest_before = (outside_tool / "tool.json").read_bytes()

    with pytest.raises(ToolAuditError, match="非法 tool.name"):
        withdraw_tool(managed, "../outside", reason="must not escape")
    with pytest.raises(ToolAuditError, match="非法 tool.name"):
        audit_tool(
            managed,
            "../outside",
            input_path=tmp_path / "missing-input",
            expected_file=tmp_path / "missing-expected",
        )
    with pytest.raises(RuntimeError, match="不在受管 dest_root"):
        write_mcp_server(outside_tool, dest_root=managed)

    assert not (outside_tool / "mcp_server.py").exists()
    assert (outside_tool / "tool.json").read_bytes() == outside_manifest_before


def test_list_flags_revoked_legacy_mcp_server_for_manual_detach(tmp_path: Path) -> None:
    tool_dir = _fake_tool(tmp_path, "legacy")
    (tool_dir / "mcp_server.py").write_text("# pre-M5 adapter\n", encoding="utf-8")
    _append(tmp_path, "legacy", REVOKED)

    listed = list_tools(tmp_path, scan=True)[0]
    assert listed["operational_status"] == REVOKED
    assert listed["mcp_server_present"] is True
    assert listed["mcp_runtime_release_enforced"] is False
    assert listed["mcp_exposure_warning"] == "LEGACY_SERVER_MUST_BE_DETACHED"


def test_mcp_projects_contract_and_returns_structured_content(tmp_path: Path) -> None:
    contract = {
        "media_type": "application/json",
        "root_type": "object",
        "required": {"language": "string", "suspicious": "array"},
    }
    tool_dir = _fake_tool(tmp_path, "reporter", contract=contract)
    (tool_dir / "bin" / "reporter").write_text(
        '#!/bin/sh\nif [ "$2" = "--out" ]; then cat "$1" > "$3"; else cat "$1"; fi\n',
        encoding="utf-8",
    )
    _append(tmp_path, "reporter", ACTIVE)
    server = write_mcp_server(tool_dir)
    input_path = tmp_path / "fresh.json"
    body = '{"language":"en","suspicious":["helo"]}\n'
    input_path.write_text(body, encoding="utf-8")
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"arguments": {"input_path": str(input_path)}},
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"arguments": {
                "input_path": str(input_path),
                "out": str(tmp_path / "mcp-output.json"),
            }},
        },
    ]
    proc = subprocess.run(
        [sys.executable, str(server)],
        input="".join(json.dumps(request) + "\n" for request in requests),
        capture_output=True,
        text=True,
        check=True,
    )
    replies = [json.loads(line) for line in proc.stdout.splitlines()]

    assert replies[0]["result"]["protocolVersion"] == "2025-06-18"
    output_schema = replies[1]["result"]["tools"][0]["outputSchema"]
    assert output_schema["required"] == ["language", "suspicious"]
    assert output_schema["properties"]["language"] == {"type": "string"}
    assert replies[2]["result"]["structuredContent"] == {
        "language": "en",
        "suspicious": ["helo"],
    }
    assert replies[2]["result"]["content"][0]["text"] == body
    assert replies[3]["result"]["structuredContent"] == {
        "language": "en",
        "suspicious": ["helo"],
    }

    # A generated and potentially already-attached server remains on disk,
    # but a later revoke is enforced on every tools/list and tools/call.
    _append(tmp_path, "reporter", REVOKED)
    revoked_requests = requests[1:3]
    revoked = subprocess.run(
        [sys.executable, str(server)],
        input="".join(json.dumps(request) + "\n" for request in revoked_requests),
        capture_output=True,
        text=True,
        check=True,
    )
    revoked_replies = [json.loads(line) for line in revoked.stdout.splitlines()]
    assert all("REVOKED" in reply["error"]["message"] for reply in revoked_replies)
    assert server.is_file()


def test_mcp_json_lines_required_contract_projects_and_runs(tmp_path: Path) -> None:
    contract = {
        "media_type": "application/x-ndjson",
        "root_type": "json_lines",
        "required": {"id": "integer"},
    }
    tool_dir = _fake_tool(tmp_path, "events", contract=contract)
    _append(tmp_path, "events", ACTIVE)
    server = write_mcp_server(tool_dir)
    input_path = tmp_path / "events.jsonl"
    input_path.write_text('{"id":1}\n{"id":2}\n', encoding="utf-8")
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"arguments": {"input_path": str(input_path)}},
        },
    ]
    proc = subprocess.run(
        [sys.executable, str(server)],
        input="".join(json.dumps(request) + "\n" for request in requests),
        capture_output=True,
        text=True,
        check=True,
    )
    replies = [json.loads(line) for line in proc.stdout.splitlines()]

    schema = replies[0]["result"]["tools"][0]["outputSchema"]
    assert schema["properties"]["lines"]["items"]["required"] == ["id"]
    assert replies[1]["result"]["structuredContent"] == {
        "lines": [{"id": 1}, {"id": 2}],
    }


@pytest.mark.parametrize(
    "constant", ["NaN", "Infinity", "-Infinity", "1e400", "-1e400"]
)
@pytest.mark.parametrize(("root_type", "body"), [
    ("object", '{{"score":{constant}}}'),
    ("json", "{constant}"),
    ("json_lines", '{{"score":{constant}}}\n'),
])
def test_mcp_rejects_nonstandard_json_constants_without_serializing_them(
        tmp_path: Path, constant: str, root_type: str, body: str) -> None:
    required = {"score": "number"} if root_type != "json" else {}
    contract = {
        "media_type": ("application/x-ndjson"
                       if root_type == "json_lines" else "application/json"),
        "root_type": root_type,
        "required": required,
    }
    tool_dir = _fake_tool(tmp_path, "strict-output", contract=contract)
    _append(tmp_path, "strict-output", ACTIVE)
    server = write_mcp_server(tool_dir)
    assert "allow_nan=False" in server.read_text(encoding="utf-8")
    input_path = tmp_path / "nonstandard.json"
    input_path.write_text(body.format(constant=constant), encoding="utf-8")
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"arguments": {"input_path": str(input_path)}},
    }

    proc = subprocess.run(
        [sys.executable, str(server)],
        input=json.dumps(request) + "\n",
        capture_output=True,
        text=True,
        check=True,
    )
    reply = json.loads(proc.stdout)

    assert reply["result"] == {
        "content": [{
            "type": "text",
            "text": "[tool-output-contract] runtime output invalid",
        }],
        "isError": True,
    }
    assert constant not in proc.stdout


def test_fail_verdict_cannot_be_audited_or_exposed_even_if_ledger_says_active(
    tmp_path: Path,
) -> None:
    tool_dir = _fake_tool(tmp_path, "failed")
    manifest_path = tool_dir / "tool.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["verification"]["verdict"] = "FAIL"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _append(tmp_path, "failed", ACTIVE)
    fresh = tmp_path / "fresh.txt"
    expected = tmp_path / "expected.txt"
    fresh.write_text("x\n", encoding="utf-8")
    expected.write_text("x\n", encoding="utf-8")

    with pytest.raises(ToolAuditError, match="不是已验证工具"):
        audit_tool(tmp_path, "failed", input_path=fresh, expected_file=expected)
    with pytest.raises(RuntimeError, match="VERIFIED_TOOL_READY"):
        write_mcp_server(tool_dir)

def test_fresh_input_audit_activates_without_persisting_sensitive_bodies(tmp_path: Path) -> None:
    tool_dir = _fake_tool(tmp_path, "echoer")
    register_tool(tmp_path, tool_dir, run_id="run-echoer", exported_at=_WHEN)
    fresh = tmp_path / "fresh.txt"
    expected = tmp_path / "expected.txt"
    secret = "SENSITIVE-FRESH-CONTENT\n"
    fresh.write_text(secret, encoding="utf-8")
    expected.write_text(secret, encoding="utf-8")

    result = audit_tool(tmp_path, "echoer", input_path=fresh, expected_file=expected)
    assert result["ok"] is True
    assert result["operational_status"] == ACTIVE
    assert secret.strip() not in (tmp_path / RELEASE_LEDGER_NAME).read_text(encoding="utf-8")

    expected.write_text("different\n", encoding="utf-8")
    result = audit_tool(tmp_path, "echoer", input_path=fresh, expected_file=expected)
    assert result["ok"] is False
    assert result["reason_code"] == "FRESH_INPUT_MISMATCH"
    assert operational_status(tmp_path, "echoer") == REVOKED


def test_concurrent_withdrawal_cannot_be_overwritten_by_slow_audit(
    tmp_path: Path,
) -> None:
    tool_dir = _fake_tool(tmp_path, "slow")
    marker = tool_dir / "audit-started"
    executable = tool_dir / "bin" / "slow"
    executable.write_text(
        f'#!/bin/sh\ntouch "{marker}"\nsleep 0.3\ncat "$1"\n',
        encoding="utf-8",
    )
    executable.chmod(0o755)
    fresh = tmp_path / "fresh.txt"
    expected = tmp_path / "expected.txt"
    fresh.write_text("fresh\n", encoding="utf-8")
    expected.write_text("fresh\n", encoding="utf-8")
    audit_results: list[dict] = []
    audit_errors: list[BaseException] = []

    def run_audit() -> None:
        try:
            audit_results.append(
                audit_tool(
                    tmp_path,
                    "slow",
                    input_path=fresh,
                    expected_file=expected,
                )
            )
        except BaseException as exc:  # surfaced in the main thread below
            audit_errors.append(exc)

    worker = threading.Thread(target=run_audit)
    worker.start()
    deadline = time.monotonic() + 10
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.exists(), "slow audit did not reach its serialized execution window"

    withdrawn = withdraw_tool(tmp_path, "slow", reason="user wins the race")
    worker.join(timeout=10)

    assert not worker.is_alive()
    assert audit_errors == []
    assert audit_results[0]["operational_status"] == ACTIVE
    assert withdrawn["reason_code"] == "USER_WITHDRAWAL"
    rows = load_release_decisions(tmp_path)
    assert [row["reason_code"] for row in rows[-2:]] == [
        "FRESH_INPUT_PASS",
        "USER_WITHDRAWAL",
    ]
    assert operational_status(
        tmp_path, "slow", task_id="tool-slow-v1"
    ) == REVOKED


def test_audit_independently_rejects_false_success_output_contract(tmp_path: Path) -> None:
    contract = {
        "media_type": "application/json",
        "root_type": "json_object",
        "required": {"language": "string", "suspicious": "array"},
    }
    tool_dir = _fake_tool(tmp_path, "spell", contract=contract)
    register_tool(tmp_path, tool_dir, run_id="run-spell", exported_at=_WHEN)
    fresh = tmp_path / "fresh.txt"
    expected = tmp_path / "expected.txt"
    # This deliberately recreates the M4 false-success shape: actual == golden,
    # while both violate the declared JSON-object contract.
    fresh.write_text("helo\nwrld\n", encoding="utf-8")
    expected.write_text("helo\nwrld\n", encoding="utf-8")

    result = audit_tool(tmp_path, "spell", input_path=fresh, expected_file=expected)
    assert result["ok"] is False
    assert result["reason_code"] == "OUTPUT_CONTRACT_MISMATCH"
    assert operational_status(tmp_path, "spell") == REVOKED

    # A contract-defect revoke cannot be washed away by another v1 audit, even
    # if an unrelated withdrawal was appended after it.
    withdraw_tool(tmp_path, "spell", reason="keep unavailable")
    with pytest.raises(ToolAuditError, match="新 task version"):
        audit_tool(tmp_path, "spell", input_path=fresh, expected_file=expected)


def test_audit_accepts_valid_declared_json_object(tmp_path: Path) -> None:
    contract = {
        "media_type": "application/json",
        "root_type": "object",
        "required": {"language": "string", "suspicious": "array"},
    }
    tool_dir = _fake_tool(tmp_path, "reporter", contract=contract)
    register_tool(tmp_path, tool_dir, run_id="run-reporter", exported_at=_WHEN)
    fresh = tmp_path / "fresh.json"
    expected = tmp_path / "expected.json"
    body = '{"language":"en","suspicious":["helo"]}\n'
    fresh.write_text(body, encoding="utf-8")
    expected.write_text(body, encoding="utf-8")

    result = audit_tool(tmp_path, "reporter", input_path=fresh, expected_file=expected)
    assert result["ok"] is True
    assert result["reason_code"] == "FRESH_INPUT_PASS"


def test_audit_rejects_packaged_input_before_execution(tmp_path: Path) -> None:
    tool_dir = _fake_tool(tmp_path, "echoer")
    packaged = tool_dir / "public-example.txt"
    packaged.write_text("x", encoding="utf-8")
    expected = tmp_path / "expected.txt"
    expected.write_text("x", encoding="utf-8")
    with pytest.raises(ToolAuditError, match="fresh non-example"):
        audit_tool(tmp_path, "echoer", input_path=packaged, expected_file=expected)
    assert not (tmp_path / RELEASE_LEDGER_NAME).exists()


def test_audit_rejects_external_copy_of_public_fixture(tmp_path: Path) -> None:
    tool_dir = _fake_tool(tmp_path, "echoer")
    fixtures = tool_dir / "public_examples" / "inputs"
    fixtures.mkdir(parents=True)
    (fixtures / "sample.txt").write_text("known fixture\n", encoding="utf-8")
    copied = tmp_path / "copied.txt"
    copied.write_text("known fixture\n", encoding="utf-8")
    expected = tmp_path / "expected.txt"
    expected.write_text("known fixture\n", encoding="utf-8")

    with pytest.raises(ToolAuditError, match="公开 fixture"):
        audit_tool(tmp_path, "echoer", input_path=copied, expected_file=expected)
    assert not (tmp_path / RELEASE_LEDGER_NAME).exists()


def test_withdraw_is_non_destructive_append_only(tmp_path: Path) -> None:
    tool_dir = _fake_tool(tmp_path, "alpha")
    _append(tmp_path, "alpha", ACTIVE)
    before_manifest = (tool_dir / "tool.json").read_bytes()

    row = withdraw_tool(tmp_path, "alpha", reason="operator requested withdrawal")
    assert row["decision"] == REVOKED
    assert row["reason_code"] == "USER_WITHDRAWAL"
    assert tool_dir.is_dir()
    assert (tool_dir / "tool.json").read_bytes() == before_manifest


def test_import_operator_audits_is_compatible_hashed_and_idempotent(tmp_path: Path) -> None:
    _fake_tool(tmp_path, "good")
    _fake_tool(tmp_path, "bad")
    pass_row = {
        "task_id": "tool-good-v1",
        "tool": "good",
        "audited_at": "2026-08-23",
        "verdict": "PASS",
        "mode": "fresh-input-cli",
        "input_is_example": False,
    }
    fail_row = {
        "task_id": "tool-bad-v1",
        "tool": "bad",
        "audited_at": "2026-08-23",
        "ok": False,
        "verdict": "FAIL",
        "mode": "fresh-input-cli",
        "input_is_example": False,
        "note": "output contract and oracle mismatch; private observation omitted",
    }
    pass_raw = json.dumps(pass_row, ensure_ascii=False, separators=(",", ":")).encode()
    fail_raw = json.dumps(fail_row, ensure_ascii=False, separators=(",", ":")).encode()
    audits = tmp_path / "audits.jsonl"
    audits.write_bytes(pass_raw + b"\n" + fail_raw + b"\n")

    counts = import_audit_decisions(audits, tmp_path)
    assert counts == {"imported": 2, "skipped": 0, "active": 1, "revoked": 1}
    assert fold_release_statuses(tmp_path) == {"good": ACTIVE, "bad": REVOKED}
    rows = load_release_decisions(tmp_path)
    assert rows[0]["evidence_sha256"] == hashlib.sha256(pass_raw).hexdigest()
    assert rows[1]["reason_code"] == "OUTPUT_CONTRACT_MISMATCH"
    assert "private observation" not in (tmp_path / RELEASE_LEDGER_NAME).read_text(encoding="utf-8")

    counts = import_audit_decisions(audits, tmp_path)
    assert counts == {"imported": 0, "skipped": 2, "active": 0, "revoked": 0}
    assert len(load_release_decisions(tmp_path)) == 2


def test_import_contract_defect_cannot_be_overridden_by_later_pass(tmp_path: Path) -> None:
    _fake_tool(tmp_path, "alpha")
    audits = tmp_path / "audits.jsonl"
    rows = [
        {
            "task_id": "tool-alpha-v1",
            "tool": "alpha",
            "audited_at": "2026-08-22",
            "verdict": "FAIL",
            "mode": "fresh-input-cli",
            "input_is_example": False,
            "note": "output contract mismatch",
        },
        {
            "task_id": "tool-alpha-v1",
            "tool": "alpha",
            "audited_at": "2026-08-23",
            "verdict": "PASS",
            "mode": "fresh-input-cli",
            "input_is_example": False,
        },
    ]
    audits.write_text(
        "".join(f"{json.dumps(row, separators=(',', ':'))}\n" for row in rows),
        encoding="utf-8",
    )

    assert import_audit_decisions(audits, tmp_path) == {
        "imported": 1,
        "skipped": 1,
        "active": 0,
        "revoked": 1,
    }
    assert operational_status(
        tmp_path, "alpha", task_id="tool-alpha-v1"
    ) == REVOKED
    assert [row["reason_code"] for row in load_release_decisions(tmp_path)] == [
        "OUTPUT_CONTRACT_MISMATCH"
    ]


def test_import_validates_entire_source_before_any_append(tmp_path: Path) -> None:
    _fake_tool(tmp_path, "a")
    audits = tmp_path / "audits.jsonl"
    audits.write_text(
        '{"task_id":"tool-a-v1","tool":"a","audited_at":"2026-08-23",'
        '"mode":"fresh-input-cli","input_is_example":false,"verdict":"PASS"}\n'
        "{damaged\n",
        encoding="utf-8",
    )
    with pytest.raises(ReleaseLedgerError, match="损坏 JSON"):
        import_audit_decisions(audits, tmp_path)
    assert not (tmp_path / RELEASE_LEDGER_NAME).exists()


def test_import_rejects_tool_path_traversal_before_reading_outside_package(
    tmp_path: Path,
) -> None:
    managed = tmp_path / "managed"
    managed.mkdir()
    outside = _fake_tool(tmp_path, "outside")
    manifest_before = (outside / "tool.json").read_bytes()
    audits = tmp_path / "audits.jsonl"
    audits.write_text(
        json.dumps(
            {
                "task_id": "tool-outside-v1",
                "tool": "../outside",
                "audited_at": "2026-08-23",
                "mode": "fresh-input-cli",
                "input_is_example": False,
                "verdict": "PASS",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ReleaseLedgerError, match="非法 tool.name"):
        import_audit_decisions(audits, managed)

    assert (outside / "tool.json").read_bytes() == manifest_before
    assert not (managed / RELEASE_LEDGER_NAME).exists()


def test_import_never_overrides_newer_user_withdrawal(tmp_path: Path) -> None:
    _fake_tool(tmp_path, "alpha")
    withdrawn = withdraw_tool(tmp_path, "alpha", reason="keep disabled")
    audits = tmp_path / "audits.jsonl"
    audits.write_text(json.dumps({
        "task_id": "tool-alpha-v1",
        "tool": "alpha",
        "audited_at": "2026-08-22",
        "mode": "fresh-input-cli",
        "input_is_example": False,
        "verdict": "PASS",
    }) + "\n", encoding="utf-8")

    assert import_audit_decisions(audits, tmp_path) == {
        "imported": 0, "skipped": 1, "active": 0, "revoked": 0,
    }
    assert operational_status(
        tmp_path, "alpha", task_id="tool-alpha-v1") == REVOKED
    assert load_release_decisions(tmp_path) == [withdrawn]

    fresh = tmp_path / "fresh.txt"
    expected = tmp_path / "expected.txt"
    fresh.write_text("x\n", encoding="utf-8")
    expected.write_text("x\n", encoding="utf-8")
    with pytest.raises(ToolAuditError, match="用户撤回"):
        audit_tool(tmp_path, "alpha", input_path=fresh, expected_file=expected)


def test_cli_audit_list_withdraw_and_mcp_enforce_release_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_tool(tmp_path, "echoer")
    fresh = tmp_path / "fresh.txt"
    expected = tmp_path / "expected.txt"
    fresh.write_text("new input\n", encoding="utf-8")
    expected.write_text("new input\n", encoding="utf-8")

    assert main([
        "tool", "audit", "echoer", "--dest-root", str(tmp_path),
        "--input", str(fresh), "--expected-file", str(expected),
    ]) == 0
    assert json.loads(capsys.readouterr().out)["operational_status"] == ACTIVE

    assert main(["tool", "list", "--dest-root", str(tmp_path), "--scan"]) == 0
    listed = json.loads(capsys.readouterr().out)["tools"][0]
    assert listed["historical_verdict"] == "VERIFIED_TOOL_READY"
    assert listed["operational_status"] == ACTIVE

    assert main([
        "tool", "withdraw", "echoer", "--dest-root", str(tmp_path),
        "--reason", "manual stop",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["decision"]["decision"] == REVOKED

    assert main(["tool", "mcp", "echoer", "--dest-root", str(tmp_path)]) == 3
    assert "REVOKED" in json.loads(capsys.readouterr().out)["error"]
