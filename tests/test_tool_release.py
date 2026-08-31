"""RFC-011 M5-c/d: release ledger, audit, migration, and consumers."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import threading
import time
from contextlib import nullcontext
from pathlib import Path

import pytest

from repoproof.cli import main
from repoproof.harness import task_package
from repoproof.runner.tool_mcp import write_mcp_server
from repoproof.runner.tool_paths import append_control_file
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
_REFERENCE_IDENTITY = {
    "impl_sha256": "1" * 64,
    "lock_sha256": "2" * 64,
}


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


def _set_reference_identity(tool_dir: Path, value: object) -> None:
    provenance_path = tool_dir / "evidence" / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["reference_identity"] = value
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")


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


def _registered_v3_tool(
    tmp_path: Path,
    *,
    name: str = "transformer",
    executable_body: str | None = None,
) -> tuple[Path, Path, Path, Path]:
    """Build the smallest frozen v3 release world without domain semantics."""

    project_root = tmp_path / "project"
    upstream_cache = project_root / "upstream-cache"
    upstream_cache.mkdir(parents=True)
    pending_upstream = upstream_cache / "pending"
    pending_upstream.mkdir()
    (pending_upstream / "fixture_upstream.py").write_text(
        "def transform(text):\n    return text.upper()\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "init", "-q", "-b", "main"],
        cwd=pending_upstream,
        check=True,
    )
    subprocess.run(["git", "add", "-A"], cwd=pending_upstream, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=release-test",
            "-c",
            "user.email=release-test@example.test",
            "commit",
            "-q",
            "-m",
            "fixture",
        ],
        cwd=pending_upstream,
        check=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=pending_upstream,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    upstream = upstream_cache / f"upstream-{commit[:12]}"
    pending_upstream.rename(upstream)

    task_id = f"tool-{name}-v1"
    verifier = project_root / "oracle" / task_id / "semantic_verifier.py"
    verifier.parent.mkdir(parents=True)
    verifier.write_text(
        "from pathlib import Path\n\n"
        "import fixture_upstream\n\n\n"
        "def verify(input_path: Path, artifact_path: Path) -> dict:\n"
        "    expected = fixture_upstream.transform(\n"
        "        input_path.read_text(encoding='utf-8')\n"
        "    )\n"
        "    ok = artifact_path.read_text(encoding='utf-8') == expected\n"
        "    return {\n"
        "        'ok': ok,\n"
        "        'reason_codes': [] if ok else ['VALUE_MISMATCH'],\n"
        "        'checked_commitment_ids': ['frozen-transform'],\n"
        "    }\n",
        encoding="utf-8",
    )
    verifier_identity = {
        "protocol": "repoproof-semantic-verifier-v1",
        "verifier_id": "fixture-semantics-v1",
        "source_file": verifier.relative_to(project_root).as_posix(),
        "source_sha256": hashlib.sha256(verifier.read_bytes()).hexdigest(),
        "required_for_operational_active": True,
    }
    output_contract = {
        "media_type": "text/plain",
        "root_type": "text",
        "required": {},
        "validation_profile": "plain_text_v1",
    }
    release_audit_identity = {
        "schema_version": 1,
        "semantic_verifier": verifier_identity,
        "output_contract_sha256": hashlib.sha256(
            json.dumps(
                output_contract,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "intent_confirmation_sha256": "3" * 64,
        "upstream_commit": commit,
        "import_module": "fixture_upstream",
        "required_commitment_ids": ["frozen-transform"],
    }
    user_goal = "Transform the supplied text with the frozen dependency."
    contract_document = {
        "task_id": task_id,
        "source_repo": {
            "url": "file:///fixture-upstream",
            "revision": "main",
            "resolved_commit": commit,
            "license": "MIT",
            "distribution": "fixture-upstream",
            "import_module": "fixture_upstream",
        },
        "target_project": {
            "kind": "consumer_fixture",
            "path": "consumer",
            "package": "fixture_consumer",
            "entry_point": name,
        },
        "capability": {
            "statement": user_goal,
            "output_schema": "TextArtifact",
            "intent_contract": {
                "schema_version": 1,
                "user_goal": user_goal,
                "user_goal_sha256": hashlib.sha256(user_goal.encode()).hexdigest(),
                "commitments": [
                    {
                        "commitment_id": "frozen-transform",
                        "public_text": user_goal,
                        "rationale": "Exercise the generic semantic trust boundary.",
                        "origin": "USER_EDITED",
                    }
                ],
                "confirmation": {
                    "confirmed_by": "USER",
                    "confirmed_at": _WHEN,
                    "semantics_sha256": "3" * 64,
                },
            },
        },
        "environment": {},
        "task_family": "LOCAL-TOOL",
        "tool": {
            "schema_version": 3,
            "name": name,
            "summary": "generic semantic release fixture",
            "interface": {
                "usage": f"{name} <input>",
                "input": {"kind": "file", "format": "text"},
                "output": {
                    "kind": "stdout",
                    "format": "text",
                    "contract": output_contract,
                },
                "exit_codes": {"0": "success", "1": "user", "2": "internal"},
            },
        },
        "constraints": {},
        "budgets": {},
        "acceptance": {
            "capability_command": ["pytest", "-q", "oracle"],
            "regression_command": ["pytest", "-q", "consumer"],
            "semantic_verifier": verifier_identity,
        },
    }
    contract_path = project_root / "contracts" / f"{task_id}.yaml"
    contract_path.parent.mkdir(parents=True)
    contract_raw = (
        json.dumps(contract_document, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    contract_path.write_bytes(contract_raw)
    Path(str(contract_path) + ".sha256").write_text(
        hashlib.sha256(contract_raw).hexdigest() + f"  {contract_path.name}\n",
        encoding="utf-8",
    )
    oracle_fixtures = project_root / "oracle" / task_id / "fixtures"
    oracle_fixtures.mkdir(parents=True)
    (oracle_fixtures / "public_documents.json").write_text(
        '{"documents": []}\n', encoding="utf-8"
    )
    consumer = project_root / "consumer"
    consumer.mkdir()
    (consumer / "README.txt").write_text("fixture\n", encoding="utf-8")
    host_contract = project_root / "tool_tasks" / task_id / "contract.yaml"
    host_contract.parent.mkdir(parents=True)
    host_contract.write_text(
        "host:\n  wheelhouse_path: unused-by-release-test\n",
        encoding="utf-8",
    )
    task_package.freeze(project_root, contract_path, upstream_dir=upstream)

    dest_root = tmp_path / "tools"
    tool_dir = _fake_tool(dest_root, name, contract=output_contract)
    if executable_body is not None:
        executable = tool_dir / "bin" / name
        executable.write_text(executable_body, encoding="utf-8")
        executable.chmod(0o755)
    manifest_path = tool_dir / "tool.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    contract_sha256 = hashlib.sha256(contract_raw).hexdigest()
    manifest["contract_schema_version"] = 3
    manifest["source"]["resolved_commit"] = commit
    manifest["verification"]["contract_sha256"] = contract_sha256
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    provenance_path = tool_dir / "evidence" / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["tool_contract_sha256"] = contract_sha256
    provenance["semantic_verifier_identity"] = verifier_identity
    provenance["release_audit_trust_identity"] = release_audit_identity
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    (tool_dir / "src").mkdir()
    (tool_dir / "src" / "implementation.py").write_text(
        "def transform(value):\n    return value\n", encoding="utf-8"
    )
    (tool_dir / "build.sh").write_text(
        "#!/bin/sh\nexit 0\n", encoding="utf-8"
    )
    (tool_dir / "build.sh").chmod(0o755)
    (tool_dir / "requirements.lock.txt").write_text(
        "fixture-upstream==1.0\n", encoding="utf-8"
    )
    register_tool(dest_root, tool_dir, run_id=f"run-{name}", exported_at=_WHEN)
    return dest_root, tool_dir, project_root, upstream


def _mock_installed_semantic_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    semantic_artifact: object,
    upstream: Path,
) -> None:
    """Model an exact installed wheel while tests reuse the host interpreter."""

    installed = tmp_path / "installed-fixture-upstream"
    installed.mkdir()
    shutil.copy2(upstream / "fixture_upstream.py", installed / "fixture_upstream.py")
    original = semantic_artifact.sanitised_subprocess_env  # type: ignore[attr-defined]

    def _environment(root: Path, paths: list[str]) -> dict[str, str]:
        return original(root, [*paths, str(installed)])

    monkeypatch.setattr(
        semantic_artifact,
        "sanitised_subprocess_env",
        _environment,
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


def test_append_control_file_completes_short_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from repoproof.runner import tool_paths

    target = tmp_path / "ledger.jsonl"
    real_write = tool_paths.os.write
    calls = 0

    def short_write(fd: int, data) -> int:
        nonlocal calls
        calls += 1
        limit = max(1, len(data) // 2)
        return real_write(fd, data[:limit])

    monkeypatch.setattr(tool_paths.os, "write", short_write)

    append_control_file(target, b'{"record":1}\n')

    assert calls > 1
    assert target.read_bytes() == b'{"record":1}\n'


def test_append_control_file_rolls_back_a_failed_partial_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from repoproof.runner import tool_paths

    target = tmp_path / "ledger.jsonl"
    target.write_bytes(b'{"record":0}\n')
    real_write = tool_paths.os.write
    calls = 0

    def partial_then_fail(fd: int, data) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(fd, data[:3])
        raise OSError("injected append failure")

    monkeypatch.setattr(tool_paths.os, "write", partial_then_fail)

    with pytest.raises(OSError, match="injected append failure"):
        append_control_file(target, b'{"record":1}\n')

    assert target.read_bytes() == b'{"record":0}\n'


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


def test_register_freezes_exact_reference_identity_for_same_task(tmp_path: Path) -> None:
    tool_dir = _fake_tool(tmp_path, "alpha")
    _set_reference_identity(tool_dir, _REFERENCE_IDENTITY)

    entry = register_tool(
        tmp_path, tool_dir, run_id="run-alpha", exported_at=_WHEN
    )
    assert entry["reference_identity"] == _REFERENCE_IDENTITY
    registry_before = (tmp_path / ".repoproof-registry.json").read_bytes()

    changed = {**_REFERENCE_IDENTITY, "impl_sha256": "3" * 64}
    _set_reference_identity(tool_dir, changed)
    with pytest.raises(ValueError, match="reference_identity"):
        register_tool(tmp_path, tool_dir, run_id="run-alpha", exported_at=_WHEN)
    assert (tmp_path / ".repoproof-registry.json").read_bytes() == registry_before


@pytest.mark.parametrize(
    "identity",
    [
        {"impl_sha256": "1" * 64},
        {"impl_sha256": "A" * 64, "lock_sha256": "2" * 64},
        {**_REFERENCE_IDENTITY, "extra": "3" * 64},
        None,
    ],
)
def test_register_rejects_malformed_claimed_reference_identity(
    tmp_path: Path, identity: object
) -> None:
    tool_dir = _fake_tool(tmp_path, "alpha")
    _set_reference_identity(tool_dir, identity)

    with pytest.raises(ValueError, match="reference_identity"):
        register_tool(tmp_path, tool_dir, run_id="run-alpha", exported_at=_WHEN)
    assert not (tmp_path / ".repoproof-registry.json").exists()
    assert not (tmp_path / RELEASE_LEDGER_NAME).exists()


def test_scan_records_new_reference_identity_but_never_attests_legacy_entry(
    tmp_path: Path,
) -> None:
    tool_dir = _fake_tool(tmp_path, "alpha")
    _set_reference_identity(tool_dir, _REFERENCE_IDENTITY)
    registry_path = tmp_path / ".repoproof-registry.json"

    listed = list_tools(tmp_path, scan=True)[0]
    assert listed["reference_identity"] == _REFERENCE_IDENTITY
    assert listed["status"] == "OK"

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    del registry["tools"]["alpha"]["reference_identity"]
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    listed = list_tools(tmp_path, scan=True)[0]
    persisted = json.loads(registry_path.read_text(encoding="utf-8"))["tools"]["alpha"]
    assert "reference_identity" not in persisted
    assert listed["status"] == "INVALID_IDENTITY"

    with pytest.raises(ValueError, match="reference_identity"):
        register_tool(tmp_path, tool_dir, run_id="run-alpha", exported_at=_WHEN)


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


@pytest.mark.parametrize(
    ("body", "expected_ok", "reason_code"),
    [
        ("ALREADY NORMALIZED\n", True, "FRESH_INPUT_PASS"),
        ("not normalized\n", False, "SEMANTIC_VERIFIER_MISMATCH"),
    ],
)
def test_v3_release_decision_requires_real_semantic_verifier_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: str,
    expected_ok: bool,
    reason_code: str,
) -> None:
    from repoproof.runner import tool_release as tool_release_module
    from repoproof.verification import semantic_artifact

    dest_root, _tool_dir, project_root, upstream = _registered_v3_tool(tmp_path)
    monkeypatch.setattr(
        tool_release_module,
        "frozen_python_environment",
        lambda **_kwargs: nullcontext(sys.executable),
    )
    monkeypatch.setattr(
        semantic_artifact,
        "offline_sandbox_argv",
        lambda argv, _writable_root: argv,
    )
    _mock_installed_semantic_runtime(
        tmp_path, monkeypatch, semantic_artifact, upstream
    )
    fresh = tmp_path / "fresh.txt"
    expected = tmp_path / "expected.txt"
    fresh.write_text(body, encoding="utf-8")
    expected.write_text(body, encoding="utf-8")

    result = audit_tool(
        dest_root,
        "transformer",
        input_path=fresh,
        expected_file=expected,
        project_root=project_root,
    )

    assert result["ok"] is expected_ok
    assert result["reason_code"] == reason_code
    assert result["semantic_verifier_passed"] is expected_ok
    if expected_ok:
        assert "failure_class" not in result
    else:
        assert result["failure_owner"] == "CONTRACT"
        assert result["failure_stage"] == "SEMANTIC_VERIFICATION"
        assert result["failure_class"] == "CONTRACT_ORACLE_CONFLICT"
        assert result["retry_policy"] == "NEW_TASK_VERSION_REQUIRED"
        assert result["requires_new_task_version"] is True
        assert (
            result["recommended_action_code"]
            == "REVIEW_CONTRACT_ORACLE_AND_CREATE_NEW_TASK_VERSION"
        )
        assert "不要盲修 adapter" in result["recommended_action"]
    evidence = json.loads(
        Path(result["semantic_verifier_evidence_path"]).read_text(encoding="utf-8")
    )
    assert evidence["required_commitment_ids"] == ["frozen-transform"]
    assert evidence["checked_commitment_ids"] == ["frozen-transform"]
    assert evidence["upstream_imports"] >= 1
    assert evidence["upstream_calls"] >= 1
    assert operational_status(dest_root, "transformer") == (
        ACTIVE if expected_ok else REVOKED
    )


@pytest.mark.parametrize("evidence_layer", ["outer", "semantic"])
def test_v3_active_fails_closed_when_persisted_audit_evidence_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    evidence_layer: str,
) -> None:
    from repoproof.runner import tool_release as tool_release_module
    from repoproof.verification import semantic_artifact

    dest_root, _tool_dir, project_root, upstream = _registered_v3_tool(tmp_path)
    monkeypatch.setattr(
        tool_release_module,
        "frozen_python_environment",
        lambda **_kwargs: nullcontext(sys.executable),
    )
    monkeypatch.setattr(
        semantic_artifact,
        "offline_sandbox_argv",
        lambda argv, _writable_root: argv,
    )
    _mock_installed_semantic_runtime(
        tmp_path, monkeypatch, semantic_artifact, upstream
    )
    fresh = tmp_path / "fresh-evidence.txt"
    expected = tmp_path / "expected-evidence.txt"
    fresh.write_text("ALREADY NORMALIZED\n", encoding="utf-8")
    expected.write_text("ALREADY NORMALIZED\n", encoding="utf-8")
    result = audit_tool(
        dest_root,
        "transformer",
        input_path=fresh,
        expected_file=expected,
        project_root=project_root,
    )
    assert result["operational_status"] == ACTIVE
    server = write_mcp_server(_tool_dir, dest_root=dest_root)

    path_key = (
        "evidence_path"
        if evidence_layer == "outer"
        else "semantic_verifier_evidence_path"
    )
    Path(result[path_key]).unlink()

    listed = next(row for row in list_tools(dest_root) if row["name"] == "transformer")
    assert listed["status"] == "OK"
    assert listed["operational_status"] == REVIEW_REQUIRED
    assert listed["operational_reason_code"] == "RELEASE_EVIDENCE_INVALID"
    assert operational_status(dest_root, "transformer") == REVIEW_REQUIRED
    with pytest.raises(RuntimeError, match="REVIEW_REQUIRED"):
        write_mcp_server(_tool_dir, dest_root=dest_root)

    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }
    process = subprocess.run(
        [sys.executable, str(server)],
        input=json.dumps(request) + "\n",
        capture_output=True,
        text=True,
        check=True,
    )
    reply = json.loads(process.stdout)
    assert reply["error"]["code"] == -32001
    assert "REVIEW_REQUIRED" in reply["error"]["message"]


@pytest.mark.parametrize(
    "identity_field",
    [
        "verifier_id",
        "verifier_source_sha256",
        "output_contract_sha256",
        "intent_confirmation_sha256",
        "upstream_commit",
        "import_module",
        "required_commitment_ids",
    ],
)
def test_v3_release_evidence_reconciles_every_frozen_trust_identity(
    tmp_path: Path,
    identity_field: str,
) -> None:
    from repoproof.runner.tool_package_identity import runtime_environment_sha256
    from repoproof.runner.tool_registry import ReleaseAuditTrustIdentityV1
    from repoproof.runner.tool_release import validate_release_audit_evidence
    from repoproof.verification.semantic_artifact import (
        SemanticVerifierEvidenceV1,
        semantic_verifier_evidence_sha256,
    )

    tool_dir = tmp_path / "tool"
    release_dir = tool_dir / "evidence" / "release-audits"
    semantic_dir = tool_dir / "evidence" / "semantic-audits"
    release_dir.mkdir(parents=True)
    semantic_dir.mkdir()
    verifier = {
        "protocol": "repoproof-semantic-verifier-v1",
        "verifier_id": "generic-verifier-v1",
        "source_file": "oracle/tool-generic-v1/semantic_verifier.py",
        "source_sha256": "1" * 64,
        "required_for_operational_active": True,
    }
    trust = ReleaseAuditTrustIdentityV1(
        semantic_verifier=verifier,
        output_contract_sha256="2" * 64,
        intent_confirmation_sha256="3" * 64,
        upstream_commit="4" * 40,
        import_module="generic_upstream",
        required_commitment_ids=("input-layout", "public-behaviour"),
    )
    nested = SemanticVerifierEvidenceV1(
        verifier_id="generic-verifier-v1",
        verifier_source_sha256="1" * 64,
        input_sha256="5" * 64,
        artifact_sha256="6" * 64,
        output_contract_sha256="2" * 64,
        intent_confirmation_sha256="3" * 64,
        upstream_commit="4" * 40,
        import_module="generic_upstream",
        upstream_imports=1,
        upstream_calls=1,
        input_negative_control_sha256="8" * 64,
        input_negative_control_result="REJECTED",
        input_negative_control_upstream_imports=0,
        input_negative_control_upstream_calls=0,
        artifact_negative_control_sha256="7" * 64,
        artifact_negative_control_result="REJECTED",
        artifact_negative_control_upstream_imports=1,
        artifact_negative_control_upstream_calls=1,
        upstream_result_counterfactual_result="REJECTED",
        upstream_result_counterfactual_upstream_imports=1,
        upstream_result_counterfactual_upstream_calls=1,
        required_commitment_ids=("input-layout", "public-behaviour"),
        # Coverage is a set.  A verifier may visit the frozen commitments in
        # a different deterministic order without weakening the evidence.
        checked_commitment_ids=("public-behaviour", "input-layout"),
        passed=True,
        reason_codes=(),
    )
    nested_path = semantic_dir / "evidence.json"
    nested_path.write_text(
        json.dumps(nested.model_dump(mode="json"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    nested_hash = semantic_verifier_evidence_sha256(nested)
    outer = {
        "schema_version": 1,
        "input_sha256": "5" * 64,
        "runtime_environment_sha256": runtime_environment_sha256(tool_dir),
        "execution": {"stdout_sha256": "6" * 64},
        "semantic_verifier": {
            "verifier_id": "generic-verifier-v1",
            "artifact_sha256": "6" * 64,
            "evidence_sha256": nested_hash,
            "evidence_path": str(nested_path),
            "passed": True,
            "reason_codes": [],
            "required_commitment_ids": ["input-layout", "public-behaviour"],
            "checked_commitment_ids": ["public-behaviour", "input-layout"],
        },
    }
    outer_path = release_dir / "evidence.json"
    outer_path.write_text(
        json.dumps(outer, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    outer_hash = hashlib.sha256(
        json.dumps(outer, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert validate_release_audit_evidence(
        tool_dir,
        evidence_sha256=outer_hash,
        require_semantic_pass=True,
        trust_identity=trust,
    )

    changed = trust.model_dump(mode="json")
    if identity_field == "verifier_id":
        changed["semantic_verifier"]["verifier_id"] = "different-verifier-v1"
    elif identity_field == "verifier_source_sha256":
        changed["semantic_verifier"]["source_sha256"] = "8" * 64
    elif identity_field == "required_commitment_ids":
        changed[identity_field] = ["different-public-behaviour"]
    elif identity_field == "upstream_commit":
        changed[identity_field] = "9" * 40
    elif identity_field == "import_module":
        changed[identity_field] = "different_upstream"
    else:
        changed[identity_field] = "8" * 64
    mismatched = ReleaseAuditTrustIdentityV1.model_validate(changed)

    assert not validate_release_audit_evidence(
        tool_dir,
        evidence_sha256=outer_hash,
        require_semantic_pass=True,
        trust_identity=mismatched,
    )


def test_v3_runtime_environment_drift_blocks_every_operational_consumer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from repoproof.runner import tool_release as tool_release_module
    from repoproof.verification import semantic_artifact

    dest_root, tool_dir, project_root, upstream = _registered_v3_tool(tmp_path)
    runtime_file = tool_dir / ".venv" / "runtime-state.txt"
    runtime_file.parent.mkdir()
    runtime_file.write_text("audited\n", encoding="utf-8")
    monkeypatch.setattr(
        tool_release_module,
        "frozen_python_environment",
        lambda **_kwargs: nullcontext(sys.executable),
    )
    monkeypatch.setattr(
        semantic_artifact,
        "offline_sandbox_argv",
        lambda argv, _writable_root: argv,
    )
    _mock_installed_semantic_runtime(
        tmp_path, monkeypatch, semantic_artifact, upstream
    )
    fresh = tmp_path / "fresh-runtime.txt"
    expected = tmp_path / "expected-runtime.txt"
    fresh.write_text("ALREADY NORMALIZED\n", encoding="utf-8")
    expected.write_text("ALREADY NORMALIZED\n", encoding="utf-8")
    result = audit_tool(
        dest_root,
        "transformer",
        input_path=fresh,
        expected_file=expected,
        project_root=project_root,
    )
    assert result["operational_status"] == ACTIVE
    server = write_mcp_server(tool_dir, dest_root=dest_root)

    runtime_file.write_text("changed after audit\n", encoding="utf-8")

    listed = next(row for row in list_tools(dest_root) if row["name"] == "transformer")
    assert listed["operational_status"] == REVIEW_REQUIRED
    assert listed["operational_reason_code"] == "RELEASE_EVIDENCE_INVALID"
    assert operational_status(dest_root, "transformer") == REVIEW_REQUIRED
    with pytest.raises(RuntimeError, match="REVIEW_REQUIRED"):
        write_mcp_server(tool_dir, dest_root=dest_root)
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }
    process = subprocess.run(
        [sys.executable, str(server)],
        input=json.dumps(request) + "\n",
        capture_output=True,
        text=True,
        check=True,
    )
    reply = json.loads(process.stdout)
    assert reply["error"]["code"] == -32001
    assert "REVIEW_REQUIRED" in reply["error"]["message"]


def test_v3_post_execution_identity_recheck_closes_hash_execute_race(
    tmp_path: Path,
) -> None:
    script = (
        "#!/bin/sh\n"
        "printf '\\n# execution-time drift\\n' >> "
        '"$(dirname "$0")/../src/implementation.py"\n'
        'cat "$1"\n'
    )
    dest_root, _tool_dir, project_root, _upstream = _registered_v3_tool(
        tmp_path,
        executable_body=script,
    )
    fresh = tmp_path / "fresh-race.txt"
    expected = tmp_path / "expected-race.txt"
    fresh.write_text("ALREADY NORMALIZED\n", encoding="utf-8")
    expected.write_text("ALREADY NORMALIZED\n", encoding="utf-8")

    result = audit_tool(
        dest_root,
        "transformer",
        input_path=fresh,
        expected_file=expected,
        project_root=project_root,
    )

    assert result["operational_status"] == REVIEW_REQUIRED
    assert result["reason_code"] == "PACKAGE_IDENTITY_CHANGED_DURING_AUDIT"
    assert result["failure_owner"] == "HARNESS"
    assert result["failure_class"] == "PACKAGE_IDENTITY"
    assert operational_status(dest_root, "transformer") == REVIEW_REQUIRED


def test_v3_semantic_mechanism_failure_clears_prior_active_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from repoproof.runner import tool_release as tool_release_module
    from repoproof.verification import semantic_artifact

    dest_root, _tool_dir, project_root, upstream = _registered_v3_tool(tmp_path)
    monkeypatch.setattr(
        tool_release_module,
        "frozen_python_environment",
        lambda **_kwargs: nullcontext(sys.executable),
    )
    monkeypatch.setattr(
        semantic_artifact,
        "offline_sandbox_argv",
        lambda argv, _writable_root: argv,
    )
    _mock_installed_semantic_runtime(
        tmp_path, monkeypatch, semantic_artifact, upstream
    )
    fresh = tmp_path / "fresh-active.txt"
    expected = tmp_path / "expected-active.txt"
    fresh.write_text("ALREADY NORMALIZED\n", encoding="utf-8")
    expected.write_text("ALREADY NORMALIZED\n", encoding="utf-8")
    first = audit_tool(
        dest_root,
        "transformer",
        input_path=fresh,
        expected_file=expected,
        project_root=project_root,
    )
    assert first["operational_status"] == ACTIVE
    (upstream / "unexpected.py").write_text("drift = True\n", encoding="utf-8")

    second = audit_tool(
        dest_root,
        "transformer",
        input_path=fresh,
        expected_file=expected,
        project_root=project_root,
    )

    assert second["operational_status"] == REVIEW_REQUIRED
    assert second["reason_code"] == "SEMANTIC_VERIFIER_CONTEXT_INVALID"
    assert second["failure_class"] == "HARNESS_ENVIRONMENT"
    assert second["failure_stage"] == "SEMANTIC_VERIFICATION"
    assert second["retry_policy"] == "REVIEW_REQUIRED"
    assert second["requires_new_task_version"] is False
    assert operational_status(dest_root, "transformer") == REVIEW_REQUIRED


@pytest.mark.parametrize("downgraded_schema", [None, 2], ids=["removed", "v2"])
def test_registered_v3_package_cannot_delete_or_downgrade_semantic_identity(
    tmp_path: Path,
    downgraded_schema: int | None,
) -> None:
    dest_root, tool_dir, _project_root, _upstream = _registered_v3_tool(tmp_path)
    manifest_path = tool_dir / "tool.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if downgraded_schema is None:
        manifest.pop("contract_schema_version")
    else:
        manifest["contract_schema_version"] = downgraded_schema
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    provenance_path = tool_dir / "evidence" / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance.pop("semantic_verifier_identity")
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    fresh = tmp_path / "fresh.txt"
    expected = tmp_path / "expected.txt"
    fresh.write_text("fresh value\n", encoding="utf-8")
    expected.write_text("fresh value\n", encoding="utf-8")

    with pytest.raises(ToolAuditError) as caught:
        audit_tool(
            dest_root,
            "transformer",
            input_path=fresh,
            expected_file=expected,
        )

    assert caught.value.reason_code == "SEMANTIC_VERIFIER_IDENTITY_INVALID"
    assert operational_status(dest_root, "transformer") == REVIEW_REQUIRED
    assert len(load_release_decisions(dest_root)) == 1


@pytest.mark.parametrize(
    "relative_path",
    [
        "src/implementation.py",
        "bin/transformer",
        "build.sh",
        "requirements.lock.txt",
    ],
)
def test_v3_audit_rejects_any_immutable_package_payload_drift(
    tmp_path: Path,
    relative_path: str,
) -> None:
    dest_root, tool_dir, _project_root, _upstream = _registered_v3_tool(tmp_path)
    payload = tool_dir / relative_path
    payload.write_bytes(payload.read_bytes() + b"\n# post-registration drift\n")
    fresh = tmp_path / "fresh.txt"
    expected = tmp_path / "expected.txt"
    fresh.write_text("fresh value\n", encoding="utf-8")
    expected.write_text("fresh value\n", encoding="utf-8")

    with pytest.raises(ToolAuditError) as caught:
        audit_tool(
            dest_root,
            "transformer",
            input_path=fresh,
            expected_file=expected,
        )

    assert caught.value.reason_code == "PACKAGE_PAYLOAD_IDENTITY_INVALID"
    assert operational_status(dest_root, "transformer") == REVIEW_REQUIRED
    assert len(load_release_decisions(dest_root)) == 1


@pytest.mark.parametrize("drift", ["tracked", "untracked"])
def test_v3_audit_rejects_frozen_upstream_checkout_drift(
    tmp_path: Path,
    drift: str,
) -> None:
    dest_root, tool_dir, project_root, upstream = _registered_v3_tool(tmp_path)
    if drift == "tracked":
        (upstream / "fixture_upstream.py").write_text(
            "def transform(text):\n    return 'changed'\n",
            encoding="utf-8",
        )
    else:
        (upstream / "unexpected.py").write_text(
            "raise RuntimeError('untracked drift')\n",
            encoding="utf-8",
        )
    fresh = tmp_path / "fresh.txt"
    expected = tmp_path / "expected.txt"
    fresh.write_text("fresh value\n", encoding="utf-8")
    expected.write_text("fresh value\n", encoding="utf-8")

    result = audit_tool(
        dest_root,
        "transformer",
        input_path=fresh,
        expected_file=expected,
        project_root=project_root,
    )

    assert result["ok"] is False
    assert result["reason_code"] == "SEMANTIC_VERIFIER_CONTEXT_INVALID"
    assert result["operational_status"] == REVIEW_REQUIRED
    assert result["semantic_verifier_passed"] is False
    assert operational_status(dest_root, "transformer") == REVIEW_REQUIRED
    assert not (tool_dir / "evidence" / "semantic-audits").exists()
    assert len(load_release_decisions(dest_root)) == 2


@pytest.mark.parametrize("schema_version", [1, 2])
def test_legacy_v1_v2_audit_remains_byte_or_contract_based(
    tmp_path: Path,
    schema_version: int,
) -> None:
    contract = None
    if schema_version == 2:
        contract = {
            "media_type": "text/plain",
            "root_type": "text",
            "required": {},
            "validation_profile": "plain_text_v1",
        }
    name = f"legacy-v{schema_version}"
    tool_dir = _fake_tool(tmp_path, name, contract=contract)
    if schema_version == 2:
        manifest_path = tool_dir / "tool.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["contract_schema_version"] = schema_version
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    register_tool(tmp_path, tool_dir, run_id=f"run-{name}", exported_at=_WHEN)
    registry_path = tmp_path / ".repoproof-registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    legacy_entry = registry["tools"][name]
    legacy_entry.pop("contract_schema_version")
    legacy_entry.pop("package_payload_sha256")
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    fresh = tmp_path / f"fresh-v{schema_version}.txt"
    expected = tmp_path / f"expected-v{schema_version}.txt"
    fresh.write_text(f"legacy {schema_version}\n", encoding="utf-8")
    expected.write_text(f"legacy {schema_version}\n", encoding="utf-8")

    result = audit_tool(
        tmp_path,
        name,
        input_path=fresh,
        expected_file=expected,
    )

    assert result["ok"] is True
    assert result["reason_code"] == "FRESH_INPUT_PASS"
    assert not any(key.startswith("semantic_verifier_") for key in result)
    assert operational_status(tmp_path, name) == ACTIVE


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
    assert result["failure_owner"] == "VERIFICATION"
    assert result["failure_stage"] == "REFERENCE_COMPARISON"
    assert result["failure_class"] == "REFERENCE_MISMATCH"
    assert result["retry_policy"] == "REVIEW_REQUIRED"
    assert result["requires_new_task_version"] is False
    assert operational_status(tmp_path, "echoer") == REVOKED


def test_fresh_audit_rebuild_ignores_generated_egg_info_but_not_source(
    tmp_path: Path,
) -> None:
    """Editable-install metadata must not manufacture payload drift.

    ``build.sh`` is allowed to reconstruct installation state.  A first
    editable build writes ``*.egg-info`` beside ``src`` even though that path
    was absent from the verified/exported git payload.  The runtime environment
    receives its own identity; authored source remains part of the immutable
    package identity.
    """

    from repoproof.runner.tool_package_identity import package_payload_sha256

    tool_dir = _fake_tool(tmp_path, "echoer")
    build_script = tool_dir / "build.sh"
    build_script.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "mkdir -p src/echoer.egg-info\n"
        "printf 'generated metadata\\n' > src/echoer.egg-info/PKG-INFO\n",
        encoding="utf-8",
    )
    build_script.chmod(0o755)
    source = tool_dir / "src" / "implementation.py"
    source.parent.mkdir(exist_ok=True)
    source.write_text("def transform(value):\n    return value\n", encoding="utf-8")
    registered_identity = package_payload_sha256(tool_dir)
    register_tool(tmp_path, tool_dir, run_id="run-echoer", exported_at=_WHEN)
    fresh = tmp_path / "fresh.txt"
    expected = tmp_path / "expected.txt"
    fresh.write_text("fresh value\n", encoding="utf-8")
    expected.write_text("fresh value\n", encoding="utf-8")

    result = audit_tool(
        tmp_path,
        "echoer",
        input_path=fresh,
        expected_file=expected,
        run_build=True,
    )

    assert result["ok"] is True
    assert result["operational_status"] == ACTIVE
    assert (tool_dir / "src" / "echoer.egg-info" / "PKG-INFO").is_file()
    assert package_payload_sha256(tool_dir) == registered_identity

    source.write_text("def transform(value):\n    return 'changed'\n", encoding="utf-8")
    assert package_payload_sha256(tool_dir) != registered_identity


def test_audit_execution_failure_is_typed_as_adapter_owned(tmp_path: Path) -> None:
    tool_dir = _fake_tool(tmp_path, "broken")
    executable = tool_dir / "bin" / "broken"
    executable.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
    executable.chmod(0o755)
    fresh = tmp_path / "fresh.txt"
    expected = tmp_path / "expected.txt"
    fresh.write_text("fresh\n", encoding="utf-8")
    expected.write_text("fresh\n", encoding="utf-8")

    result = audit_tool(tmp_path, "broken", input_path=fresh, expected_file=expected)

    assert result["reason_code"] == "FRESH_INPUT_EXECUTION_FAILED"
    assert result["failure_owner"] == "AGENT_ADAPTER"
    assert result["failure_stage"] == "ADAPTER_EXECUTION"
    assert result["failure_class"] == "ADAPTER_EXECUTION"
    assert result["retry_policy"] == "NEW_TASK_VERSION_REQUIRED"
    assert result["requires_new_task_version"] is True


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


@pytest.mark.parametrize(
    ("media_type", "validation_profile", "body"),
    [
        (
            "application/x-research-info-systems",
            "ris_interchange_v1",
            '{"not":"RIS"}\n',
        ),
        (
            "text/tab-separated-values",
            "tsv_table_v1",
            "sample\tvalue\nA\t1\textra\n",
        ),
        ("text/markdown", "markdown_document_v1", '{"not":"Markdown"}\n'),
        (
            "text/html",
            "safe_self_contained_xhtml_v1",
            '<html><body><script>bad()</script></body></html>\n',
        ),
    ],
)
def test_audit_rejects_matching_but_wrong_multiformat_artifacts(
    tmp_path: Path,
    media_type: str,
    validation_profile: str,
    body: str,
) -> None:
    """A bad golden cannot relabel JSON/unsafe text as a scientific artifact."""
    contract = {
        "media_type": media_type,
        "root_type": "text",
        "required": {},
        "validation_profile": validation_profile,
    }
    tool_dir = _fake_tool(tmp_path, "artifact", contract=contract)
    register_tool(tmp_path, tool_dir, run_id="run-artifact", exported_at=_WHEN)
    fresh = tmp_path / "fresh.txt"
    expected = tmp_path / "expected.txt"
    fresh.write_text(body, encoding="utf-8")
    expected.write_text(body, encoding="utf-8")

    result = audit_tool(tmp_path, "artifact", input_path=fresh, expected_file=expected)
    assert result["ok"] is False
    assert result["reason_code"] == "OUTPUT_CONTRACT_MISMATCH"
    assert operational_status(tmp_path, "artifact") == REVOKED


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
    with pytest.raises(ToolAuditError, match="fresh non-example") as caught:
        audit_tool(tmp_path, "echoer", input_path=packaged, expected_file=expected)
    assert caught.value.failure.failure_owner == "USER_INPUT"
    assert caught.value.failure.failure_stage == "AUDIT_INPUT"
    assert caught.value.failure.failure_class == "USER_INPUT"
    assert caught.value.failure.retry_policy == "RETRY_AFTER_INPUT_CORRECTION"
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
    assert rows[1]["reason_code"] == "MIGRATED_AUDIT_FAIL"
    assert "private observation" not in (tmp_path / RELEASE_LEDGER_NAME).read_text(encoding="utf-8")

    counts = import_audit_decisions(audits, tmp_path)
    assert counts == {"imported": 0, "skipped": 2, "active": 0, "revoked": 0}
    assert len(load_release_decisions(tmp_path)) == 2


def test_legacy_note_wording_never_controls_migration_reason(tmp_path: Path) -> None:
    """Free prose is evidence context, never a failure-classification API."""

    rows = []
    for name, note in (
        ("wordy", "contract oracle 合同 题面 mismatch"),
        ("plain", "an unrelated operator observation"),
    ):
        _fake_tool(tmp_path, name)
        rows.append({
            "task_id": f"tool-{name}-v1",
            "tool": name,
            "audited_at": "2026-08-23",
            "verdict": "FAIL",
            "mode": "fresh-input-cli",
            "input_is_example": False,
            "note": note,
        })
    audits = tmp_path / "wording.jsonl"
    audits.write_text(
        "".join(f"{json.dumps(row, ensure_ascii=False)}\n" for row in rows),
        encoding="utf-8",
    )

    assert import_audit_decisions(audits, tmp_path) == {
        "imported": 2,
        "skipped": 0,
        "active": 0,
        "revoked": 2,
    }
    assert {
        row["reason_code"] for row in load_release_decisions(tmp_path)
    } == {"MIGRATED_AUDIT_FAIL"}


def test_v3_legacy_audit_import_cannot_create_active_without_current_evidence(
    tmp_path: Path,
) -> None:
    dest_root, _tool_dir, _project_root, _upstream = _registered_v3_tool(tmp_path)
    audits = tmp_path / "legacy-v3-audits.jsonl"
    audits.write_text(
        json.dumps(
            {
                "task_id": "tool-transformer-v1",
                "tool": "transformer",
                "audited_at": "2026-08-23",
                "mode": "fresh-input-cli",
                "input_is_example": False,
                "verdict": "PASS",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before = load_release_decisions(dest_root)

    with pytest.raises(ReleaseLedgerError, match="ToolSpec v3"):
        import_audit_decisions(audits, dest_root)

    assert load_release_decisions(dest_root) == before
    assert operational_status(dest_root, "transformer") == REVIEW_REQUIRED


def test_imported_legacy_failure_cannot_be_overridden_by_later_pass(
    tmp_path: Path,
) -> None:
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
        "MIGRATED_AUDIT_FAIL"
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


def test_cli_audit_identity_mismatch_emits_stable_structured_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tool_dir = _fake_tool(tmp_path, "echoer")
    register_tool(tmp_path, tool_dir, run_id="run-echoer", exported_at=_WHEN)
    fresh = tmp_path / "fresh.txt"
    expected = tmp_path / "expected.txt"
    action_result = tmp_path / "audit-result.json"
    fresh.write_text("new input\n", encoding="utf-8")
    expected.write_text("new input\n", encoding="utf-8")

    assert main([
        "tool", "audit", "echoer", "--dest-root", str(tmp_path),
        "--input", str(fresh), "--expected-file", str(expected),
        "--expected-task-id", "tool-echoer-v2",
        "--job-id", "audit-identity-test", "--result-json", str(action_result),
    ]) == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["reason_codes"] == ["AUDIT_TASK_IDENTITY_MISMATCH"]
    assert payload["failure_owner"] == "HARNESS"
    assert payload["failure_stage"] == "AUDIT_PRECONDITION"
    assert payload["failure_class"] == "PACKAGE_IDENTITY"
    assert payload["retry_policy"] == "RETRY_AFTER_INPUT_REFRESH"
    assert payload["requires_new_task_version"] is False
    assert payload["recommended_action_code"] == "REFRESH_AUDIT_CANDIDATE"
    structured = json.loads(action_result.read_text(encoding="utf-8"))
    assert structured["task_id"] == "tool-echoer-v2"
    assert structured["reason_codes"] == ["AUDIT_TASK_IDENTITY_MISMATCH"]
    assert structured["product_stop_code"] == "STOP_HARNESS_OR_EXTERNAL"
    assert structured["failure_class"] == "PACKAGE_IDENTITY"
    assert structured["retry_policy"] == "RETRY_AFTER_INPUT_REFRESH"
    assert operational_status(tmp_path, "echoer") == REVIEW_REQUIRED
