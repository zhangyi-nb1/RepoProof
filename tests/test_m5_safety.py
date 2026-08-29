"""M5 safety regressions for managed state, package identity, and upgrades."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from repoproof.runner import tool_export, tool_mcp, tool_paths, tool_release
from repoproof.runner.tool_export import ToolExportError, install_verified_tool
from repoproof.runner.tool_mcp import write_mcp_server
from repoproof.runner.tool_paths import ToolPathError
from repoproof.runner.tool_registry import list_tools, register_tool
from repoproof.runner.tool_release import (
    ACTIVE,
    RELEASE_LEDGER_NAME,
    RELEASE_LOCK_NAME,
    REVIEW_REQUIRED,
    REVOKED,
    ReleaseLedgerError,
    ToolAuditError,
    append_release_decision,
    audit_tool,
    load_release_decisions,
)

_ZERO_HASH = "0" * 64
_WHEN = "2026-08-24T00:00:00Z"


def _fake_tool(
    dest_root: Path,
    name: str = "alpha",
    *,
    task_id: str | None = None,
    run_id: str | None = None,
    contract_sha256: str = "1" * 64,
) -> Path:
    task_id = task_id or f"tool-{name}-v1"
    run_id = run_id or f"run-{name}-v1"
    tool_dir = dest_root / name
    (tool_dir / "bin").mkdir(parents=True)
    (tool_dir / "evidence").mkdir()
    launcher = tool_dir / "bin" / name
    launcher.write_text("#!/bin/sh\ncat \"$1\"\n", encoding="utf-8")
    launcher.chmod(0o755)
    manifest = {
        "manifest_version": 1,
        "name": name,
        "version": "1.0.0",
        "summary": "M5 safety test tool",
        "source": {
            "url": "https://example.invalid/tool.git",
            "resolved_commit": "c",
            "license": "MIT",
            "distribution": f"{name}-dist",
        },
        "interface": {
            "usage": f"{name} <input>",
            "input": {"kind": "file", "format": "TXT"},
            "output": {"kind": "stdout", "format": "TXT"},
            "exit_codes": {"0": "success", "1": "user", "2": "internal"},
        },
        "verification": {
            "verdict": "VERIFIED_TOOL_READY",
            "run_id": run_id,
            "contract_sha256": contract_sha256,
        },
    }
    (tool_dir / "tool.json").write_text(
        json.dumps(manifest, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (tool_dir / "evidence" / "provenance.json").write_text(
        json.dumps(
            {
                "tool": name,
                "task_id": task_id,
                "run_id": run_id,
                "tool_contract_sha256": contract_sha256,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return tool_dir


def _append_active(
    dest_root: Path,
    name: str = "alpha",
    *,
    task_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    return append_release_decision(
        dest_root,
        tool=name,
        task_id=task_id or f"tool-{name}-v1",
        run_id=run_id or f"run-{name}-v1",
        decision=ACTIVE,
        reason_code="M5_SAFETY_ACTIVE",
        reason="Synthetic active decision for an M5 safety regression.",
        evidence_sha256=_ZERO_HASH,
        actor="operator",
        decided_at=_WHEN,
    )


def _mcp_request(server: Path, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {},
    }
    completed = subprocess.run(
        [sys.executable, str(server)],
        input=json.dumps(request) + "\n",
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return json.loads(completed.stdout)


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _prepare_upgrade_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, dict[str, Path]]:
    dest_root = tmp_path / "tools"
    current = _fake_tool(
        dest_root,
        task_id="tool-alpha-v1",
        run_id="run-alpha-v1",
        contract_sha256="1" * 64,
    )
    register_tool(
        dest_root,
        current,
        run_id="run-alpha-v1",
        exported_at=_WHEN,
    )

    host = tmp_path / "host-v2"
    (host / "bin").mkdir(parents=True)
    (host / "bin" / "alpha").write_text(
        "#!/bin/sh\necho v2\n", encoding="utf-8"
    )
    (host / "build.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (host / "version.txt").write_text("v2\n", encoding="utf-8")
    (host / "tool.json").write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "name": "alpha",
                "version": "2.0.0",
                "summary": "M5 safety upgrade candidate",
                "source": {
                    "url": "https://example.invalid/tool.git",
                    "resolved_commit": "c",
                },
                "interface": {
                    "usage": "alpha <input>",
                    "input": {"kind": "file", "format": "TXT"},
                    "output": {"kind": "stdout", "format": "TXT"},
                    "exit_codes": {"0": "success"},
                },
                "verification": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    run_dir = tmp_path / "run-v2"
    run_dir.mkdir()
    (run_dir / "report.json").write_text(
        json.dumps(
            {
                "task_id": "tool-alpha-v2",
                "run_id": "run-alpha-v2",
                "verdict": "PASS_ADAPTED",
                "verdict_public": "VERIFIED_TOOL_READY",
                "final_trace_sha256": "2" * 64,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    host_contract = tmp_path / "host-v2.json"
    host_contract.write_text(
        json.dumps({"host": {"copy_path": str(host)}}) + "\n",
        encoding="utf-8",
    )
    tool_contract = tmp_path / "tool-alpha-v2.yaml"
    tool_contract.write_text("synthetic: true\n", encoding="utf-8")
    reference = tmp_path / "controls" / "tool-alpha-v2" / "reference"
    reference.mkdir(parents=True)
    (reference / "impl.py").write_text(
        "def extract(path):\n    return path.read_text()\n", encoding="utf-8"
    )
    (reference / "requirements.lock.txt").write_text(
        "alpha-dist==2.0.0\n", encoding="utf-8"
    )
    contract = SimpleNamespace(
        task_family="LOCAL-TOOL",
        task_id="tool-alpha-v2",
        tool=SimpleNamespace(name="alpha"),
        source_repo=SimpleNamespace(
            url="https://example.invalid/tool.git",
            resolved_commit="c",
            license="MIT",
            distribution="alpha-dist",
        ),
    )

    def load_frozen(
        _cls: type, path: Path, *, require_sidecar: bool = False
    ) -> tuple[SimpleNamespace, str]:
        assert Path(path) == tool_contract
        assert require_sidecar is True
        return contract, "2" * 64

    monkeypatch.setattr(
        tool_export.TaskContract,
        "load_frozen",
        classmethod(load_frozen),
    )
    return dest_root, current, {
        "run_dir": run_dir,
        "host_contract": host_contract,
        "tool_contract": tool_contract,
    }


def _install_upgrade(dest_root: Path, context: dict[str, Path]) -> Path:
    return install_verified_tool(
        context["run_dir"],
        host_contract_path=context["host_contract"],
        tool_contract_path=context["tool_contract"],
        dest_root=dest_root,
        exported_at=_WHEN,
    )


def test_release_ledger_symlink_rejects_core_and_generated_mcp_without_touching_target(
    tmp_path: Path,
) -> None:
    dest_root = tmp_path / "tools"
    tool_dir = _fake_tool(dest_root)
    _append_active(dest_root)
    server = write_mcp_server(tool_dir)
    ledger = dest_root / RELEASE_LEDGER_NAME
    outside = tmp_path / "outside-valid-ledger.jsonl"
    outside.write_bytes(ledger.read_bytes())
    before = outside.read_bytes()
    ledger.unlink()
    ledger.symlink_to(outside)

    with pytest.raises(ReleaseLedgerError, match="安全打开|release ledger"):
        load_release_decisions(dest_root)
    with pytest.raises(ReleaseLedgerError):
        _append_active(dest_root, name="beta")
    reply = _mcp_request(server, "tools/list")

    assert reply["error"] == {
        "code": -32001,
        "message": "release ledger schema invalid",
    }
    assert ledger.is_symlink()
    assert outside.read_bytes() == before


def test_release_lock_symlink_rejects_append_without_touching_target(tmp_path: Path) -> None:
    dest_root = tmp_path / "tools"
    dest_root.mkdir()
    outside = tmp_path / "outside-release-lock"
    outside.write_text("release-lock-marker\n", encoding="utf-8")
    before = outside.read_bytes()
    (dest_root / RELEASE_LOCK_NAME).symlink_to(outside)

    with pytest.raises(ReleaseLedgerError, match="控制文件|安全打开"):
        _append_active(dest_root)

    assert outside.read_bytes() == before
    assert not (dest_root / RELEASE_LEDGER_NAME).exists()


def test_install_lock_symlink_rejects_audit_and_mcp_without_touching_target(
    tmp_path: Path,
) -> None:
    dest_root = tmp_path / "tools"
    tool_dir = _fake_tool(dest_root)
    _append_active(dest_root)
    outside = tmp_path / "outside-install-lock"
    outside.write_text("install-lock-marker\n", encoding="utf-8")
    before = outside.read_bytes()
    (dest_root / tool_paths.INSTALL_LOCK_NAME).symlink_to(outside)
    fresh = tmp_path / "fresh.txt"
    expected = tmp_path / "expected.txt"
    fresh.write_text("fresh\n", encoding="utf-8")
    expected.write_text("fresh\n", encoding="utf-8")

    with pytest.raises(ToolPathError, match="控制文件|安全打开"):
        audit_tool(dest_root, "alpha", input_path=fresh, expected_file=expected)
    with pytest.raises(ToolPathError, match="控制文件|安全打开"):
        write_mcp_server(tool_dir)

    assert outside.read_bytes() == before
    assert not (tool_dir / "mcp_server.py").exists()


def test_unterminated_nonempty_ledger_blocks_core_append_and_generated_tools_list(
    tmp_path: Path,
) -> None:
    dest_root = tmp_path / "tools"
    tool_dir = _fake_tool(dest_root)
    _append_active(dest_root)
    server = write_mcp_server(tool_dir)
    ledger = dest_root / RELEASE_LEDGER_NAME
    ledger.write_bytes(ledger.read_bytes().removesuffix(b"\n"))
    before = ledger.read_bytes()

    with pytest.raises(ReleaseLedgerError, match="换行"):
        load_release_decisions(dest_root)
    with pytest.raises(ReleaseLedgerError, match="换行"):
        _append_active(dest_root, name="beta")
    reply = _mcp_request(server, "tools/list")

    assert reply["error"] == {
        "code": -32001,
        "message": "release ledger schema invalid",
    }
    assert ledger.read_bytes() == before


@pytest.mark.parametrize(
    "damage",
    ["missing", "empty", "identity-mismatch", "tool-mismatch", "task-mismatch"],
)
def test_damaged_provenance_blocks_audit_mcp_and_active_list_projection(
    tmp_path: Path,
    damage: str,
) -> None:
    dest_root = tmp_path / "tools"
    tool_dir = _fake_tool(dest_root)
    register_tool(
        dest_root,
        tool_dir,
        run_id="run-alpha-v1",
        exported_at=_WHEN,
    )
    _append_active(dest_root)
    executed = tmp_path / "tool-executed"
    launcher = tool_dir / "bin" / "alpha"
    launcher.write_text(
        f"#!/bin/sh\nprintf executed > {shlex.quote(str(executed))}\ncat \"$1\"\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    provenance = tool_dir / "evidence" / "provenance.json"
    if damage == "missing":
        provenance.unlink()
    elif damage == "empty":
        provenance.write_bytes(b"")
    else:
        doc = json.loads(provenance.read_text(encoding="utf-8"))
        if damage == "identity-mismatch":
            doc["run_id"] = "forged-run"
        elif damage == "task-mismatch":
            doc["task_id"] = "tool-beta-v1"
        else:
            doc["tool"] = "beta"
        provenance.write_text(json.dumps(doc) + "\n", encoding="utf-8")

    fresh = tmp_path / "fresh.txt"
    expected = tmp_path / "expected.txt"
    fresh.write_text("fresh\n", encoding="utf-8")
    expected.write_text("fresh\n", encoding="utf-8")

    with pytest.raises((ToolAuditError, ValueError)):
        audit_tool(dest_root, "alpha", input_path=fresh, expected_file=expected)
    with pytest.raises((RuntimeError, ValueError)):
        write_mcp_server(tool_dir)
    listed = list_tools(dest_root)

    assert not executed.exists()
    assert not (tool_dir / "mcp_server.py").exists()
    assert len(listed) == 1
    assert listed[0]["status"] == "INVALID_IDENTITY"
    assert listed[0]["operational_status"] == REVIEW_REQUIRED
    assert listed[0]["operational_reason_code"] == "INVALID_PACKAGE_IDENTITY"


def test_generated_mcp_blocks_package_identity_drift_at_call_time(
    tmp_path: Path,
) -> None:
    dest_root = tmp_path / "tools"
    tool_dir = _fake_tool(dest_root)
    register_tool(dest_root, tool_dir, run_id="run-alpha-v1", exported_at=_WHEN)
    _append_active(dest_root)
    server = write_mcp_server(tool_dir)

    provenance_path = tool_dir / "evidence" / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["run_id"] = "forged-after-mcp-generation"
    provenance_path.write_text(json.dumps(provenance) + "\n", encoding="utf-8")

    reply = _mcp_request(server, "tools/list")
    assert reply["error"] == {
        "code": -32001,
        "message": "managed package identity changed",
    }


@pytest.mark.parametrize(
    ("relative", "operation"),
    [
        ("mcp_server.py", "mcp"),
        ("bin/alpha", "audit"),
        ("build.sh", "audit-build"),
    ],
)
def test_package_symlinks_are_never_written_or_executed(
    tmp_path: Path,
    relative: str,
    operation: str,
) -> None:
    dest_root = tmp_path / "tools"
    tool_dir = _fake_tool(dest_root)
    _append_active(dest_root)
    external_effect = tmp_path / "external-effect"
    external_target = tmp_path / f"outside-{Path(relative).name}"
    external_target.write_text(
        "#!/bin/sh\n"
        f"printf executed > {shlex.quote(str(external_effect))}\n"
        "cat \"$1\"\n",
        encoding="utf-8",
    )
    external_target.chmod(0o755)
    before = external_target.read_bytes()
    package_path = tool_dir / relative
    if package_path.exists():
        package_path.unlink()
    package_path.symlink_to(external_target)
    fresh = tmp_path / "fresh.txt"
    expected = tmp_path / "expected.txt"
    fresh.write_text("fresh\n", encoding="utf-8")
    expected.write_text("fresh\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="symlink"):
        if operation == "mcp":
            write_mcp_server(tool_dir)
        else:
            audit_tool(
                dest_root,
                "alpha",
                input_path=fresh,
                expected_file=expected,
                run_build=operation == "audit-build",
            )

    assert package_path.is_symlink()
    assert external_target.read_bytes() == before
    assert not external_effect.exists()


@pytest.mark.parametrize(
    "mutation", ["launcher-symlink", "identity", "manifest-nonobject"]
)
def test_audit_build_revalidates_package_before_executing_launcher(
    tmp_path: Path,
    mutation: str,
) -> None:
    dest_root = tmp_path / "tools"
    tool_dir = _fake_tool(dest_root)
    external_effect = tmp_path / "external-effect"
    external_launcher = tmp_path / "outside-launcher"
    external_launcher.write_text(
        "#!/bin/sh\n"
        f"printf executed > {shlex.quote(str(external_effect))}\n"
        'cat "$1"\n',
        encoding="utf-8",
    )
    external_launcher.chmod(0o755)

    if mutation == "launcher-symlink":
        build_body = (
            "rm -f bin/alpha\n"
            f"ln -s {shlex.quote(str(external_launcher))} bin/alpha\n"
        )
    elif mutation == "identity":
        provenance = json.loads(
            (tool_dir / "evidence" / "provenance.json").read_text(
                encoding="utf-8"
            )
        )
        provenance["run_id"] = "forged-by-build"
        build_body = (
            "printf '%s\\n' "
            f"{shlex.quote(json.dumps(provenance))} "
            "> evidence/provenance.json\n"
        )
    else:
        build_body = "printf '%s\\n' '[]' > tool.json\n"
    (tool_dir / "build.sh").write_text(
        "#!/bin/sh\nset -eu\n" + build_body,
        encoding="utf-8",
    )

    fresh = tmp_path / "fresh.txt"
    expected = tmp_path / "expected.txt"
    fresh.write_text("fresh\n", encoding="utf-8")
    expected.write_text("fresh\n", encoding="utf-8")

    result = audit_tool(
        dest_root,
        "alpha",
        input_path=fresh,
        expected_file=expected,
        run_build=True,
    )

    assert result["ok"] is False
    assert result["operational_status"] == REVOKED
    assert result["reason_code"] == "BUILD_FAILED"
    assert not external_effect.exists()
    assert load_release_decisions(dest_root)[-1]["decision"] == REVOKED


def test_mcp_out_uses_fresh_staging_and_preserves_old_file_when_tool_writes_nothing(
    tmp_path: Path,
) -> None:
    dest_root = tmp_path / "tools"
    tool_dir = _fake_tool(dest_root, name="silent")
    launcher = tool_dir / "bin" / "silent"
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    _append_active(dest_root, name="silent")
    server = write_mcp_server(tool_dir)
    input_path = tmp_path / "fresh.txt"
    input_path.write_text("fresh\n", encoding="utf-8")
    output_path = tmp_path / "existing-output.txt"
    output_path.write_text("trusted old output\n", encoding="utf-8")
    before = output_path.read_bytes()

    reply = _mcp_request(
        server,
        "tools/call",
        {
            "name": "silent",
            "arguments": {
                "input_path": str(input_path),
                "out": str(output_path),
            },
        },
    )

    assert reply["result"] == {
        "content": [
            {"type": "text", "text": "declared output file unavailable"}
        ],
        "isError": True,
    }
    assert output_path.read_bytes() == before
    assert not list(tmp_path.glob(".existing-output.txt.repoproof-*.tmp"))


def test_mcp_out_rejects_symlink_without_writing_external_target(
    tmp_path: Path,
) -> None:
    dest_root = tmp_path / "tools"
    tool_dir = _fake_tool(dest_root, name="writer")
    launcher = tool_dir / "bin" / "writer"
    launcher.write_text(
        '#!/bin/sh\nif [ "$2" = "--out" ]; then cat "$1" > "$3"; fi\n',
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    _append_active(dest_root, name="writer")
    server = write_mcp_server(tool_dir)
    input_path = tmp_path / "fresh.txt"
    input_path.write_text("NEW\n", encoding="utf-8")
    victim = tmp_path / "victim.txt"
    victim.write_text("SENTINEL\n", encoding="utf-8")
    requested = tmp_path / "requested-output.txt"
    requested.symlink_to(victim)

    reply = _mcp_request(
        server,
        "tools/call",
        {
            "name": "writer",
            "arguments": {
                "input_path": str(input_path),
                "out": str(requested),
            },
        },
    )

    assert reply["error"] == {
        "code": -32000,
        "message": "declared output target is unsafe",
    }
    assert requested.is_symlink()
    assert victim.read_text(encoding="utf-8") == "SENTINEL\n"


def test_external_versions_symlink_blocks_upgrade_and_preserves_canonical_v1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest_root, current, context = _prepare_upgrade_world(tmp_path, monkeypatch)
    canonical_before = _tree_digest(current)
    registry = dest_root / ".repoproof-registry.json"
    registry_before = registry.read_bytes()
    outside_versions = tmp_path / "outside-versions"
    outside_versions.mkdir()
    marker = outside_versions / "marker.txt"
    marker.write_text("external history must remain untouched\n", encoding="utf-8")
    marker_before = marker.read_bytes()
    (dest_root / ".repoproof-versions").symlink_to(
        outside_versions, target_is_directory=True
    )

    with pytest.raises(ToolExportError, match="symlink|受管目录"):
        _install_upgrade(dest_root, context)

    assert (dest_root / "alpha").is_dir()
    assert _tree_digest(dest_root / "alpha") == canonical_before
    assert registry.read_bytes() == registry_before
    assert marker.read_bytes() == marker_before
    assert sorted(path.name for path in outside_versions.iterdir()) == ["marker.txt"]


def test_audit_and_upgrade_serialize_on_shared_install_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest_root, _current, context = _prepare_upgrade_world(tmp_path, monkeypatch)
    fresh = tmp_path / "fresh.txt"
    expected = tmp_path / "expected.txt"
    fresh.write_text("fresh\n", encoding="utf-8")
    expected.write_text("fresh\n", encoding="utf-8")
    holding_lock = threading.Barrier(2)
    release_operation = threading.Event()
    audit_results: list[dict[str, Any]] = []
    audit_errors: list[BaseException] = []
    upgrade_errors: list[BaseException] = []
    upgrade_attempted_lock = threading.Event()
    upgrade_acquired_lock = threading.Event()
    original_audit = tool_release._audit_tool_locked

    def paused_audit(*args: Any, **kwargs: Any) -> dict[str, Any]:
        holding_lock.wait(timeout=10)
        assert release_operation.wait(timeout=10)
        return original_audit(*args, **kwargs)

    monkeypatch.setattr(tool_release, "_audit_tool_locked", paused_audit)

    def run_audit() -> None:
        try:
            audit_results.append(
                audit_tool(
                    dest_root,
                    "alpha",
                    input_path=fresh,
                    expected_file=expected,
                )
            )
        except BaseException as exc:
            audit_errors.append(exc)

    audit_thread = threading.Thread(target=run_audit, name="m5-audit")
    audit_thread.start()
    holding_lock.wait(timeout=10)

    original_flock = tool_paths.fcntl.flock

    def observed_flock(fd: int, operation: int) -> Any:
        is_upgrade_exclusive = (
            threading.current_thread().name == "m5-upgrader"
            and operation == tool_paths.fcntl.LOCK_EX
        )
        if is_upgrade_exclusive:
            upgrade_attempted_lock.set()
        result = original_flock(fd, operation)
        if is_upgrade_exclusive:
            upgrade_acquired_lock.set()
        return result

    monkeypatch.setattr(tool_paths.fcntl, "flock", observed_flock)

    def run_upgrade() -> None:
        try:
            _install_upgrade(dest_root, context)
        except BaseException as exc:
            upgrade_errors.append(exc)

    upgrade_thread = threading.Thread(target=run_upgrade, name="m5-upgrader")
    upgrade_thread.start()
    assert upgrade_attempted_lock.wait(timeout=10)
    assert not upgrade_acquired_lock.is_set()
    assert upgrade_thread.is_alive()

    release_operation.set()
    assert upgrade_acquired_lock.wait(timeout=10)
    audit_thread.join(timeout=10)
    upgrade_thread.join(timeout=10)

    assert not audit_thread.is_alive()
    assert not upgrade_thread.is_alive()
    assert audit_errors == []
    assert upgrade_errors == []
    assert audit_results[0]["operational_status"] == ACTIVE
    assert (dest_root / "alpha" / "version.txt").read_text(encoding="utf-8") == "v2\n"


def test_stale_fresh_audit_truth_cannot_activate_upgraded_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A candidate made for v1 fails closed if v2 wins the install race."""

    dest_root, _current, context = _prepare_upgrade_world(tmp_path, monkeypatch)
    fresh = tmp_path / "fresh-v1.txt"
    expected = tmp_path / "expected-v1.txt"
    fresh.write_text("truth generated for v1\n", encoding="utf-8")
    expected.write_text("truth generated for v1\n", encoding="utf-8")

    # Candidate generation happened while v1 was current. The competing
    # upgrade settles v2 before the delayed audit acquires the install lock.
    _install_upgrade(dest_root, context)
    ledger_before = (dest_root / RELEASE_LEDGER_NAME).read_bytes()

    with pytest.raises(ToolAuditError) as caught:
        audit_tool(
            dest_root,
            "alpha",
            input_path=fresh,
            expected_file=expected,
            expected_task_id="tool-alpha-v1",
            run_build=True,
        )

    assert caught.value.reason_code == "AUDIT_TASK_IDENTITY_MISMATCH"
    assert "registry 当前为 tool-alpha-v2" in str(caught.value)
    assert (dest_root / RELEASE_LEDGER_NAME).read_bytes() == ledger_before
    assert list_tools(dest_root)[0]["task_id"] == "tool-alpha-v2"
    assert list_tools(dest_root)[0]["operational_status"] == REVIEW_REQUIRED


def test_mcp_generation_and_upgrade_serialize_on_shared_install_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest_root, current, context = _prepare_upgrade_world(tmp_path, monkeypatch)
    _append_active(dest_root)
    holding_lock = threading.Barrier(2)
    release_operation = threading.Event()
    mcp_results: list[Path] = []
    mcp_errors: list[BaseException] = []
    upgrade_errors: list[BaseException] = []
    upgrade_attempted_lock = threading.Event()
    upgrade_acquired_lock = threading.Event()
    original_write = tool_mcp._write_mcp_server_install_locked

    def paused_write(tool_dir: Path, release_root: Path) -> Path:
        holding_lock.wait(timeout=10)
        assert release_operation.wait(timeout=10)
        return original_write(tool_dir, release_root)

    monkeypatch.setattr(tool_mcp, "_write_mcp_server_install_locked", paused_write)

    def run_mcp_generation() -> None:
        try:
            mcp_results.append(write_mcp_server(current))
        except BaseException as exc:
            mcp_errors.append(exc)

    mcp_thread = threading.Thread(target=run_mcp_generation, name="m5-mcp")
    mcp_thread.start()
    holding_lock.wait(timeout=10)

    original_flock = tool_paths.fcntl.flock

    def observed_flock(fd: int, operation: int) -> Any:
        is_upgrade_exclusive = (
            threading.current_thread().name == "m5-upgrader"
            and operation == tool_paths.fcntl.LOCK_EX
        )
        if is_upgrade_exclusive:
            upgrade_attempted_lock.set()
        result = original_flock(fd, operation)
        if is_upgrade_exclusive:
            upgrade_acquired_lock.set()
        return result

    monkeypatch.setattr(tool_paths.fcntl, "flock", observed_flock)

    def run_upgrade() -> None:
        try:
            _install_upgrade(dest_root, context)
        except BaseException as exc:
            upgrade_errors.append(exc)

    upgrade_thread = threading.Thread(target=run_upgrade, name="m5-upgrader")
    upgrade_thread.start()
    assert upgrade_attempted_lock.wait(timeout=10)
    assert not upgrade_acquired_lock.is_set()
    assert upgrade_thread.is_alive()

    release_operation.set()
    assert upgrade_acquired_lock.wait(timeout=10)
    mcp_thread.join(timeout=10)
    upgrade_thread.join(timeout=10)

    assert not mcp_thread.is_alive()
    assert not upgrade_thread.is_alive()
    assert mcp_errors == []
    assert upgrade_errors == []
    assert mcp_results[0].name == "mcp_server.py"
    assert (dest_root / "alpha" / "version.txt").read_text(encoding="utf-8") == "v2\n"


def test_generated_mcp_holds_release_lock_from_active_check_through_execution(
    tmp_path: Path,
) -> None:
    dest_root = tmp_path / "tools"
    tool_dir = _fake_tool(dest_root)
    started = tmp_path / "execution-started"
    allow_finish = tmp_path / "allow-finish"
    launcher = tool_dir / "bin" / "alpha"
    launcher.write_text(
        "#!/bin/sh\n"
        f"touch {shlex.quote(str(started))}\n"
        f"while [ ! -f {shlex.quote(str(allow_finish))} ]; do sleep 0.01; done\n"
        'cat "$1"\n',
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    _append_active(dest_root)
    server = write_mcp_server(tool_dir)
    input_path = tmp_path / "fresh.txt"
    input_path.write_text("authorized-before-revoke\n", encoding="utf-8")
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"arguments": {"input_path": str(input_path)}},
    }
    call_results: list[subprocess.CompletedProcess[str]] = []

    def run_call() -> None:
        call_results.append(
            subprocess.run(
                [sys.executable, str(server)],
                input=json.dumps(request) + "\n",
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
        )

    call_thread = threading.Thread(target=run_call, name="m5-runtime-call")
    call_thread.start()
    deadline = time.monotonic() + 10
    while not started.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert started.exists()

    revoke_started = threading.Event()
    revoke_rows: list[dict[str, Any]] = []

    def revoke() -> None:
        revoke_started.set()
        revoke_rows.append(
            append_release_decision(
                dest_root,
                tool="alpha",
                task_id="tool-alpha-v1",
                run_id="run-alpha-v1",
                decision=REVOKED,
                reason_code="CONCURRENT_REVOKE",
                reason="Revoke after the already-authorized call linearization point.",
                evidence_sha256="f" * 64,
                actor="operator",
                decided_at="2026-08-24T00:00:01Z",
            )
        )

    revoke_thread = threading.Thread(target=revoke, name="m5-runtime-revoke")
    revoke_thread.start()
    assert revoke_started.wait(timeout=10)
    time.sleep(0.1)
    assert revoke_thread.is_alive(), "revoke must wait for the in-flight MCP call"

    allow_finish.write_text("go\n", encoding="utf-8")
    call_thread.join(timeout=10)
    revoke_thread.join(timeout=10)

    assert not call_thread.is_alive() and not revoke_thread.is_alive()
    reply = json.loads(call_results[0].stdout)
    assert reply["result"]["isError"] is False
    assert reply["result"]["content"][0]["text"] == "authorized-before-revoke\n"
    assert revoke_rows[0]["decision"] == REVOKED
    assert load_release_decisions(dest_root)[-1]["reason_code"] == "CONCURRENT_REVOKE"

def test_audit_uses_the_same_yardstick_as_the_contract(tmp_path: Path):
    """抽查的比对口径必须与**合同自己的验收测试**一致。

    2026-08-28 实录:抽查用裸字节比对,而 example_compiler 生成的能力测试
    用 `_norm`(去首尾空白 + 行尾空白)。金标准样例文件不以换行结尾、工具
    stdout 带 `\\n` —— 工具通过了全部 6 条能力测试,却被抽查判 MISMATCH
    并**自动撤回**。用户照着实际输出原样粘贴,同样被撤回。

    抽查是"拿没见过的输入再验一次同一份合同",判据就该是合同的判据。
    比合同更严不是更严谨,是换了一把尺子 —— 那样"通过合同"推不出
    "通过抽查",两个结论各说各话。
    """
    from repoproof.verification.output_match import compare_output

    stdout, golden = '{"a":1}\n', '{"a":1}'   # 金标准文件不以换行结尾
    assert stdout != golden                     # 裸字节:不等(旧口径判撤回)
    assert compare_output(stdout, golden, root_type="object")[0]   # 合同口径:相等
    assert compare_output(stdout, golden, root_type="text")[0]

    # 真正的不一致仍然必须被抓住
    assert not compare_output('{"a":1}', '{"a":2}', root_type="object")[0]
    assert not compare_output("red\n", "blue\n", root_type="text")[0]
