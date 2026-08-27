"""M5 verified-tool installation and same-command task-version upgrades."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from repoproof.runner import tool_export, tool_registry
from repoproof.runner.tool_export import (
    ToolExportError,
    export_verified_tool,
    install_verified_tool,
    preflight_tool_install,
)
from repoproof.runner.tool_release import (
    ACTIVE,
    REVIEW_REQUIRED,
    REVOKED,
    append_release_decision,
    load_release_decisions,
    operational_status,
)


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _candidate_world(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, dict[str, Path]], Path]:
    contexts: dict[str, dict[str, Path]] = {}
    contracts: dict[Path, tuple[SimpleNamespace, str]] = {}
    for version in (1, 2):
        task_id = f"tool-alpha-v{version}"
        host = root / f"host-v{version}"
        (host / "bin").mkdir(parents=True)
        (host / "bin" / "alpha").write_text(
            f"#!/bin/sh\necho v{version}\n", encoding="utf-8"
        )
        (host / "build.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (host / "version.txt").write_text(f"v{version}\n", encoding="utf-8")
        (host / "tool.json").write_text(
            json.dumps(
                {
                    "manifest_version": 1,
                    "name": "alpha",
                    "version": f"{version}.0.0",
                    "summary": "synthetic upgrade tool",
                    "source": {"url": "u", "resolved_commit": "c"},
                    "interface": {
                        "usage": "alpha <input>",
                        "input": {"kind": "file", "format": "TXT"},
                        "output": {"kind": "stdout", "format": "TXT"},
                        "exit_codes": {"0": "success"},
                    },
                    "verification": None,
                }
            ),
            encoding="utf-8",
        )
        host_contract = root / f"host-v{version}.json"
        host_contract.write_text(
            json.dumps({"host": {"copy_path": str(host)}}), encoding="utf-8"
        )
        contract_path = root / f"{task_id}.yaml"
        contract_path.write_text("synthetic: true\n", encoding="utf-8")
        run = root / f"run-v{version}"
        run.mkdir()
        (run / "report.json").write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "run_id": f"run-alpha-v{version}",
                    "verdict": "PASS_ADAPTED",
                    "verdict_public": "VERIFIED_TOOL_READY",
                    "final_trace_sha256": f"{version}" * 64,
                }
            ),
            encoding="utf-8",
        )
        contract = SimpleNamespace(
            task_family="LOCAL-TOOL",
            task_id=task_id,
            tool=SimpleNamespace(name="alpha"),
            source_repo=SimpleNamespace(
                url="u",
                resolved_commit="c",
                license="MIT",
                distribution="alpha-dist",
            ),
        )
        contracts[contract_path] = (contract, f"{version}" * 64)
        contexts[task_id] = {
            "run": run,
            "host_contract": host_contract,
            "tool_contract": contract_path,
        }

    def load_frozen(
        _cls: type, path: Path, *, require_sidecar: bool = False
    ) -> tuple[SimpleNamespace, str]:
        assert require_sidecar is True
        return contracts[Path(path)]

    monkeypatch.setattr(
        tool_export.TaskContract, "load_frozen", classmethod(load_frozen)
    )
    dest_root = root / "tools"
    return contexts, dest_root


def _install(context: dict[str, Path], dest_root: Path) -> Path:
    return install_verified_tool(
        context["run"],
        host_contract_path=context["host_contract"],
        tool_contract_path=context["tool_contract"],
        dest_root=dest_root,
        exported_at="2026-08-24T00:00:00Z",
    )


def _decision(dest_root: Path, task_id: str, decision: str, reason_code: str) -> None:
    append_release_decision(
        dest_root,
        tool="alpha",
        task_id=task_id,
        run_id=task_id.replace("tool-", "run-"),
        decision=decision,
        reason_code=reason_code,
        reason="synthetic upgrade decision",
        evidence_sha256="0" * 64,
        actor="operator",
        decided_at="2026-08-24T00:00:00Z",
    )


def test_revoked_v1_upgrades_to_archived_v1_and_review_required_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contexts, dest_root = _candidate_world(tmp_path, monkeypatch)
    current = _install(contexts["tool-alpha-v1"], dest_root)
    _decision(dest_root, "tool-alpha-v1", ACTIVE, "FRESH_INPUT_PASS")
    _decision(dest_root, "tool-alpha-v1", REVOKED, "OUTPUT_CONTRACT_MISMATCH")
    old_digest = _tree_digest(current)

    upgraded = _install(contexts["tool-alpha-v2"], dest_root)

    provenance = json.loads(
        (upgraded / "evidence" / "provenance.json").read_text(encoding="utf-8")
    )
    archive = dest_root / provenance["replaces"]["archive_path"]
    assert archive.is_dir()
    assert _tree_digest(archive) == old_digest
    assert (archive / "version.txt").read_text(encoding="utf-8") == "v1\n"
    assert (upgraded / "version.txt").read_text(encoding="utf-8") == "v2\n"
    assert operational_status(
        dest_root, "alpha", task_id="tool-alpha-v2"
    ) == REVIEW_REQUIRED
    assert [row["decision"] for row in load_release_decisions(dest_root)] == [
        REVIEW_REQUIRED,
        ACTIVE,
        REVOKED,
        REVIEW_REQUIRED,
    ]

    registry = json.loads(
        (dest_root / ".repoproof-registry.json").read_text(encoding="utf-8")
    )["tools"]["alpha"]
    assert registry["task_id"] == "tool-alpha-v2"
    assert registry["previous_versions"] == [
        {
            "archive_path": provenance["replaces"]["archive_path"],
            "contract_sha256": "1" * 64,
            "exported_at": "2026-08-24T00:00:00Z",
            "historical_verdict": "VERIFIED_TOOL_READY",
            "run_id": "run-alpha-v1",
            "task_id": "tool-alpha-v1",
        }
    ]

    before = _tree_digest(upgraded)
    before_ledger = (dest_root / ".repoproof-release-decisions.jsonl").read_bytes()
    with pytest.raises(ToolExportError, match="同一 task_id"):
        preflight_tool_install(dest_root, "alpha", "tool-alpha-v2")
    with pytest.raises(ToolExportError, match="更高 task version"):
        preflight_tool_install(dest_root, "alpha", "tool-alpha-v1")
    assert _tree_digest(upgraded) == before
    assert (dest_root / ".repoproof-release-decisions.jsonl").read_bytes() == before_ledger


def test_registry_failure_restores_old_package_and_leaves_fail_closed_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contexts, dest_root = _candidate_world(tmp_path, monkeypatch)
    current = _install(contexts["tool-alpha-v1"], dest_root)
    _decision(dest_root, "tool-alpha-v1", ACTIVE, "FRESH_INPUT_PASS")
    old_digest = _tree_digest(current)
    registry_before = (dest_root / ".repoproof-registry.json").read_bytes()

    def fail_save(_dest_root: Path, _doc: dict) -> None:
        raise OSError("injected registry save failure")

    monkeypatch.setattr(tool_registry, "_save", fail_save)
    with pytest.raises(ToolExportError, match="旧包已恢复"):
        _install(contexts["tool-alpha-v2"], dest_root)

    assert _tree_digest(dest_root / "alpha") == old_digest
    assert (dest_root / ".repoproof-registry.json").read_bytes() == registry_before
    assert operational_status(
        dest_root, "alpha", task_id="tool-alpha-v1"
    ) == REVIEW_REQUIRED
    assert load_release_decisions(dest_root)[-1]["task_id"] == "tool-alpha-v2"
    assert load_release_decisions(dest_root)[-1]["decision"] == REVIEW_REQUIRED
    assert not list((dest_root / ".repoproof-versions").rglob("tool.json"))


def test_keyboard_interrupt_during_second_rename_restores_old_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contexts, dest_root = _candidate_world(tmp_path, monkeypatch)
    current = _install(contexts["tool-alpha-v1"], dest_root)
    old_digest = _tree_digest(current)
    registry_before = (dest_root / ".repoproof-registry.json").read_bytes()
    original_replace = tool_export.os.replace
    calls = 0

    def interrupt_second_replace(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        original_replace(source, target)

    monkeypatch.setattr(tool_export.os, "replace", interrupt_second_replace)
    with pytest.raises(KeyboardInterrupt):
        _install(contexts["tool-alpha-v2"], dest_root)

    assert _tree_digest(dest_root / "alpha") == old_digest
    assert (dest_root / ".repoproof-registry.json").read_bytes() == registry_before
    assert operational_status(
        dest_root, "alpha", task_id="tool-alpha-v1"
    ) == REVIEW_REQUIRED
    assert not list((dest_root / ".repoproof-versions").rglob("tool.json"))


def test_interrupt_after_old_package_rename_recovers_from_actual_disk_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contexts, dest_root = _candidate_world(tmp_path, monkeypatch)
    current = _install(contexts["tool-alpha-v1"], dest_root)
    old_digest = _tree_digest(current)
    registry_before = (dest_root / ".repoproof-registry.json").read_bytes()
    original_replace = tool_export.os.replace
    calls = 0

    def commit_first_move_then_interrupt(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        original_replace(source, target)
        if calls == 1:
            raise KeyboardInterrupt

    monkeypatch.setattr(tool_export.os, "replace", commit_first_move_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        _install(contexts["tool-alpha-v2"], dest_root)

    assert _tree_digest(dest_root / "alpha") == old_digest
    assert (dest_root / ".repoproof-registry.json").read_bytes() == registry_before
    assert not list((dest_root / ".repoproof-versions").rglob("tool.json"))


def test_interrupt_after_candidate_rename_recovers_from_actual_disk_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contexts, dest_root = _candidate_world(tmp_path, monkeypatch)
    current = _install(contexts["tool-alpha-v1"], dest_root)
    old_digest = _tree_digest(current)
    registry_before = (dest_root / ".repoproof-registry.json").read_bytes()
    original_replace = tool_export.os.replace
    calls = 0

    def commit_second_move_then_interrupt(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        original_replace(source, target)
        if calls == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(tool_export.os, "replace", commit_second_move_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        _install(contexts["tool-alpha-v2"], dest_root)

    assert _tree_digest(dest_root / "alpha") == old_digest
    assert (dest_root / ".repoproof-registry.json").read_bytes() == registry_before
    assert not list((dest_root / ".repoproof-versions").rglob("tool.json"))


def test_keyboard_interrupt_during_registry_save_restores_old_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contexts, dest_root = _candidate_world(tmp_path, monkeypatch)
    current = _install(contexts["tool-alpha-v1"], dest_root)
    old_digest = _tree_digest(current)
    registry_before = (dest_root / ".repoproof-registry.json").read_bytes()

    def interrupt_save(_dest_root: Path, _doc: dict) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(tool_registry, "_save", interrupt_save)
    with pytest.raises(KeyboardInterrupt):
        _install(contexts["tool-alpha-v2"], dest_root)

    assert _tree_digest(dest_root / "alpha") == old_digest
    assert (dest_root / ".repoproof-registry.json").read_bytes() == registry_before
    assert operational_status(
        dest_root, "alpha", task_id="tool-alpha-v1"
    ) == REVIEW_REQUIRED
    assert not list((dest_root / ".repoproof-versions").rglob("tool.json"))


def test_interrupt_after_atomic_registry_commit_keeps_new_package_and_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contexts, dest_root = _candidate_world(tmp_path, monkeypatch)
    _install(contexts["tool-alpha-v1"], dest_root)
    original_save = tool_registry._save

    def commit_then_interrupt(root: Path, doc: dict) -> None:
        original_save(root, doc)
        raise KeyboardInterrupt

    monkeypatch.setattr(tool_registry, "_save", commit_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        _install(contexts["tool-alpha-v2"], dest_root)

    assert (dest_root / "alpha" / "version.txt").read_text(encoding="utf-8") == "v2\n"
    registry = json.loads(
        (dest_root / ".repoproof-registry.json").read_text(encoding="utf-8")
    )["tools"]["alpha"]
    assert registry["task_id"] == "tool-alpha-v2"
    assert registry["run_id"] == "run-alpha-v2"
    assert registry["contract_sha256"] == "2" * 64
    assert [row["task_id"] for row in registry["previous_versions"]] == [
        "tool-alpha-v1"
    ]
    assert len(list((dest_root / ".repoproof-versions").rglob("tool.json"))) == 1
    assert operational_status(
        dest_root, "alpha", task_id="tool-alpha-v2"
    ) == REVIEW_REQUIRED


@pytest.mark.parametrize("interrupt_call", [3, 4])
def test_post_commit_interrupt_during_recovery_still_restores_old_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupt_call: int,
) -> None:
    contexts, dest_root = _candidate_world(tmp_path, monkeypatch)
    current = _install(contexts["tool-alpha-v1"], dest_root)
    old_digest = _tree_digest(current)
    registry_before = (dest_root / ".repoproof-registry.json").read_bytes()
    original_replace = tool_export.os.replace
    calls = 0

    def interrupt_recovery_after_move(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        original_replace(source, target)
        if calls == interrupt_call:
            raise KeyboardInterrupt

    def fail_registry_save(_dest_root: Path, _doc: dict) -> None:
        raise OSError("force package recovery")

    monkeypatch.setattr(tool_export.os, "replace", interrupt_recovery_after_move)
    monkeypatch.setattr(tool_registry, "_save", fail_registry_save)
    with pytest.raises(ToolExportError, match="旧包已恢复"):
        _install(contexts["tool-alpha-v2"], dest_root)

    assert _tree_digest(dest_root / "alpha") == old_digest
    assert (dest_root / ".repoproof-registry.json").read_bytes() == registry_before
    assert not list((dest_root / ".repoproof-versions").rglob("tool.json"))


def test_upgrade_requires_complete_matching_registry_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contexts, dest_root = _candidate_world(tmp_path, monkeypatch)
    _install(contexts["tool-alpha-v1"], dest_root)
    registry_path = dest_root / ".repoproof-registry.json"
    registry_path.unlink()

    with pytest.raises(ToolExportError, match="tool list --scan"):
        preflight_tool_install(dest_root, "alpha", "tool-alpha-v2")
    tool_registry.list_tools(dest_root, scan=True)
    assert preflight_tool_install(
        dest_root, "alpha", "tool-alpha-v2"
    )["task_id"] == "tool-alpha-v1"

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["tools"]["alpha"]["run_id"] = "forged-run"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(ToolExportError, match="run_id 不一致"):
        preflight_tool_install(dest_root, "alpha", "tool-alpha-v2")

    registry["tools"]["alpha"]["run_id"] = "run-alpha-v1"
    registry["schema_version"] = 2
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(ToolExportError, match="严格加载|schema"):
        preflight_tool_install(dest_root, "alpha", "tool-alpha-v2")

    registry["schema_version"] = 1
    registry["tools"]["unrelated-damaged-entry"] = "not-an-object"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(ToolExportError, match="严格加载|schema"):
        preflight_tool_install(dest_root, "alpha", "tool-alpha-v2")


def test_scan_and_upgrade_share_registry_install_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contexts, dest_root = _candidate_world(tmp_path, monkeypatch)
    _install(contexts["tool-alpha-v1"], dest_root)
    scanner_at_save = threading.Event()
    allow_scanner_save = threading.Event()
    original_save = tool_registry._save

    def paused_save(root: Path, doc: dict) -> None:
        if threading.current_thread().name == "registry-scanner":
            scanner_at_save.set()
            assert allow_scanner_save.wait(timeout=2)
        original_save(root, doc)

    monkeypatch.setattr(tool_registry, "_save", paused_save)
    scanner = threading.Thread(
        target=tool_registry.list_tools,
        kwargs={"dest_root": dest_root, "scan": True},
        name="registry-scanner",
    )
    scanner.start()
    assert scanner_at_save.wait(timeout=2)

    upgrade_errors: list[BaseException] = []

    def upgrade() -> None:
        try:
            _install(contexts["tool-alpha-v2"], dest_root)
        except BaseException as exc:
            upgrade_errors.append(exc)

    upgrader = threading.Thread(target=upgrade, name="tool-upgrader")
    upgrader.start()
    time.sleep(0.1)
    assert upgrader.is_alive(), "upgrade should wait for scanner's registry lock"
    allow_scanner_save.set()
    scanner.join(timeout=2)
    upgrader.join(timeout=2)

    assert not scanner.is_alive() and not upgrader.is_alive()
    assert upgrade_errors == []
    registry = json.loads(
        (dest_root / ".repoproof-registry.json").read_text(encoding="utf-8")
    )["tools"]["alpha"]
    assert registry["task_id"] == "tool-alpha-v2"
    assert [row["task_id"] for row in registry["previous_versions"]] == [
        "tool-alpha-v1"
    ]


def test_upgrade_preflight_blocks_legacy_mcp_without_mutating_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contexts, dest_root = _candidate_world(tmp_path, monkeypatch)
    current = _install(contexts["tool-alpha-v1"], dest_root)
    (current / "mcp_server.py").write_text("# pre-M5 server\n", encoding="utf-8")
    before = _tree_digest(current)
    ledger_before = (dest_root / ".repoproof-release-decisions.jsonl").read_bytes()

    with pytest.raises(ToolExportError, match="LEGACY_MCP_MUST_BE_DETACHED"):
        preflight_tool_install(dest_root, "alpha", "tool-alpha-v2")

    assert _tree_digest(current) == before
    assert (dest_root / ".repoproof-release-decisions.jsonl").read_bytes() == ledger_before


def test_upgrade_preflight_rejects_tool_name_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(ToolExportError, match="非法 tool.name"):
        preflight_tool_install(
            tmp_path / "tools", "../escape", "tool-escape-v1"
        )
    assert not (tmp_path / "escape").exists()


def test_managed_tool_path_rejects_in_root_symlink_alias(tmp_path: Path) -> None:
    dest_root = tmp_path / "tools"
    target = dest_root / "beta"
    target.mkdir(parents=True)
    marker = target / "marker.txt"
    marker.write_text("must remain untouched\n", encoding="utf-8")
    (dest_root / "alpha").symlink_to(target, target_is_directory=True)

    with pytest.raises(ToolExportError, match="逃逸 dest_root"):
        preflight_tool_install(dest_root, "alpha", "tool-alpha-v2")

    assert marker.read_text(encoding="utf-8") == "must remain untouched\n"
    assert target.is_dir()


def test_candidate_manifest_symlink_is_rejected_before_external_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contexts, dest_root = _candidate_world(tmp_path, monkeypatch)
    context = contexts["tool-alpha-v1"]
    (context["run"] / "adaptation.patch").write_text("synthetic\n", encoding="utf-8")
    external = tmp_path / "external-tool.json"
    external.write_text('{"sentinel":"unchanged"}\n', encoding="utf-8")
    before = external.read_bytes()

    def synthesize_symlink(_argv: list[str], **kwargs: object) -> SimpleNamespace:
        candidate_manifest = Path(kwargs["cwd"]) / "tool.json"
        candidate_manifest.unlink()
        candidate_manifest.symlink_to(external)
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(tool_export.subprocess, "run", synthesize_symlink)
    with pytest.raises(ToolExportError, match="禁止 symlink"):
        _install(context, dest_root)

    assert external.read_bytes() == before
    assert not (dest_root / "alpha").exists()


def test_adaptation_cannot_create_or_modify_candidate_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contexts, dest_root = _candidate_world(tmp_path, monkeypatch)
    context = contexts["tool-alpha-v1"]
    (context["run"] / "adaptation.patch").write_text("synthetic\n", encoding="utf-8")
    external = tmp_path / "external-python"
    external.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    before = external.stat().st_mode

    def synthesize_venv_link(_argv: list[str], **kwargs: object) -> SimpleNamespace:
        candidate = Path(kwargs["cwd"])
        (candidate / ".venv" / "bin").mkdir(parents=True)
        (candidate / ".venv" / "bin" / "python").symlink_to(external)
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(tool_export.subprocess, "run", synthesize_venv_link)
    with pytest.raises(ToolExportError, match="不得创建或修改.*venv"):
        _install(context, dest_root)

    assert external.stat().st_mode == before
    assert not (dest_root / "alpha").exists()


def test_legacy_export_post_commit_interrupt_removes_canonical_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contexts, dest_root = _candidate_world(tmp_path, monkeypatch)
    context = contexts["tool-alpha-v1"]
    original_replace = tool_export.os.replace
    interrupted = False

    def commit_then_interrupt(source: Path, target: Path) -> None:
        nonlocal interrupted
        original_replace(source, target)
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt

    monkeypatch.setattr(tool_export.os, "replace", commit_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        export_verified_tool(
            context["run"],
            host_contract_path=context["host_contract"],
            tool_contract_path=context["tool_contract"],
            dest_root=dest_root,
        )

    assert not (dest_root / "alpha").exists()
    assert not list(dest_root.glob(".repoproof-export-*"))


def test_relative_destination_root_upgrades_with_one_canonical_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contexts, _absolute_dest = _candidate_world(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)

    _install(contexts["tool-alpha-v1"], Path("tools"))
    upgraded = _install(contexts["tool-alpha-v2"], Path("tools"))

    assert upgraded == (tmp_path / "tools" / "alpha").resolve()
    assert (upgraded / "version.txt").read_text(encoding="utf-8") == "v2\n"
    registry = json.loads(
        (tmp_path / "tools" / ".repoproof-registry.json").read_text(
            encoding="utf-8"
        )
    )["tools"]["alpha"]
    assert registry["path"] == str(upgraded)
    assert registry["previous_versions"][0]["task_id"] == "tool-alpha-v1"


def test_pipeline_preflights_upgrade_before_models_and_uses_safe_installer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from repoproof.runner import host_guided, tool_pipeline

    project = tmp_path / "project"
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "draft.yaml").write_text(
        json.dumps(
            {
                "source_repo": {
                    "url": "u",
                    "resolved_commit": "c",
                    "distribution": "alpha-dist",
                },
                "tool": {
                    "name": "alpha",
                    "interface": {"input": {"format": "TXT"}},
                },
            }
        ),
        encoding="utf-8",
    )
    task_id = "tool-alpha-v2"
    contract = project / "contracts" / f"{task_id}.yaml"
    events: list[str] = []

    monkeypatch.setattr(
        tool_pipeline,
        "confirm_tool_draft",
        lambda _draft, _project: {"task_id": task_id, "public": 3, "held": 1},
    )
    monkeypatch.setattr(tool_pipeline, "check_draft_complete", lambda *_args: [])
    monkeypatch.setattr(
        tool_pipeline, "next_tool_task_id", lambda *_args: task_id
    )
    monkeypatch.setattr(
        tool_pipeline,
        "preflight_tool_install",
        lambda _root, _name, _task: events.append("preflight")
        or {"task_id": "tool-alpha-v1"},
    )
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    monkeypatch.setattr(
        tool_pipeline, "ensure_pinned_upstream", lambda *_args: upstream
    )
    monkeypatch.setattr(tool_pipeline, "select_upstream_tests", lambda *_args: [])

    def materialize(*_args: object, **_kwargs: object) -> Path:
        (project / "tool_tasks" / task_id).mkdir(parents=True)
        contract.parent.mkdir(parents=True)
        contract.write_text("synthetic: true\n", encoding="utf-8")
        return contract

    monkeypatch.setattr(tool_pipeline, "materialize_tool_task", materialize)

    def fake_run(
        _contract: Path,
        _project: Path,
        *,
        fake: str | None,
        batch: str,
        backend: str = "mini-swe",
    ) -> dict:
        assert batch == "TEST"
        if fake is None:
            assert backend == "mini-swe"
        events.append("rehearsal" if fake else "real")
        return {
            "report": {
                "task_id": task_id,
                "run_id": "run-alpha-v2",
                "verdict": "PASS_ADAPTED",
                "verdict_public": "VERIFIED_TOOL_READY",
                "gate_reasons": [],
            }
        }

    monkeypatch.setattr(host_guided, "run_host_guided_cli", fake_run)
    dest_root = tmp_path / "tools"

    def install(*_args: object, **kwargs: object) -> Path:
        events.append("install")
        assert kwargs["tool_contract_path"] == contract
        dest = dest_root / "alpha"
        dest.mkdir(parents=True)
        return dest

    monkeypatch.setattr(tool_pipeline, "install_verified_tool", install)

    result = tool_pipeline.tool_build(
        draft,
        project,
        bench_root=tmp_path / "bench",
        dest_root=dest_root,
        run_real=True,
        wheelhouse_cmd=["true"],
        batch="TEST",
    )

    assert events == ["preflight", "rehearsal", "real", "install"]
    assert result["stages"]["install_preflight"] == {
        "ok": True,
        "mode": "upgrade",
        "previous_task_id": "tool-alpha-v1",
    }
    assert result["historical_verdict"] == "VERIFIED_TOOL_READY"
    assert result["operational_status"] == REVIEW_REQUIRED


def test_pipeline_rejects_unsafe_upgrade_before_confirm_freezes_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from repoproof.runner import tool_pipeline

    project = tmp_path / "project"
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "draft.yaml").write_text(
        json.dumps({"tool": {"name": "alpha"}}), encoding="utf-8"
    )
    monkeypatch.setattr(tool_pipeline, "check_draft_complete", lambda *_args: [])
    monkeypatch.setattr(
        tool_pipeline,
        "next_tool_task_id",
        lambda *_args: "tool-alpha-v2",
    )
    monkeypatch.setattr(
        tool_pipeline,
        "preflight_tool_install",
        lambda *_args: (_ for _ in ()).throw(
            ToolExportError("LEGACY_MCP_MUST_BE_DETACHED")
        ),
    )
    monkeypatch.setattr(
        tool_pipeline,
        "confirm_tool_draft",
        lambda *_args: pytest.fail("confirm must not run after install preflight fails"),
    )

    with pytest.raises(tool_pipeline.PipelineError, match="LEGACY_MCP"):
        tool_pipeline.tool_build(
            draft,
            project,
            bench_root=tmp_path / "bench",
            dest_root=tmp_path / "tools",
            run_real=True,
        )

    assert not (project / "contracts").exists()
