from __future__ import annotations

import json
import os
import sqlite3
import stat
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from repoproof.domain.models import (
    WorkspaceArtifactContractV1,
    WorkspaceArtifactLimits,
    WorkspaceArtifactRule,
)
from repoproof.execution.workspace_bundle import (
    WorkspaceBundleError,
    build_artifact_manifest,
    identify_input_path,
    materialize_workspace_atomic,
    run_workspace_smoke,
    snapshot_admitted_path,
    validate_workspace,
    workspace_path_matches,
    write_deterministic_zip,
)


def _contract(*, allow_extra: bool = False) -> WorkspaceArtifactContractV1:
    return WorkspaceArtifactContractV1(
        rules=(
            WorkspaceArtifactRule(
                path_pattern="README.md",
                role="human documentation",
                media_type="text/markdown",
                validation_profile="text_utf8_v1",
            ),
            WorkspaceArtifactRule(
                path_pattern="data/*.csv",
                role="derived tables",
                media_type="text/csv",
                validation_profile="csv_v1",
                min_count=1,
                max_count=3,
            ),
            WorkspaceArtifactRule(
                path_pattern="scripts/run.sh",
                role="entrypoint",
                media_type="text/x-shellscript",
                validation_profile="shell_v1",
                executable=True,
            ),
        ),
        allow_extra_files=allow_extra,
        entrypoints=("scripts/run.sh",),
        runnable=True,
        smoke_command=("./scripts/run.sh",),
    )


def _valid_tree(root: Path) -> None:
    (root / "data").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "README.md").write_text("# Result\n", encoding="utf-8")
    (root / "data" / "rows.csv").write_text("id,value\n1,ok\n", encoding="utf-8")
    runner = root / "scripts" / "run.sh"
    runner.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    runner.chmod(0o755)


def test_toolspec_v4_requires_workspace_shape() -> None:
    from repoproof.domain.models import ToolSpec

    raw = {
        "schema_version": 4,
        "name": "workspace-maker",
        "summary": "Build a workspace",
        "delivery_profile_id": "workspace_bundle_v1",
        "workspace_contract": _contract().model_dump(mode="json"),
        "interface": {
            "usage": "workspace-maker <input> --out-dir <new-directory>",
            "input": {"kind": "directory", "format": "local data bundle"},
            "output": {"kind": "directory", "format": "workspace bundle"},
            "exit_codes": {"0": "ok", "1": "user", "2": "internal"},
        },
    }
    assert ToolSpec.model_validate(raw).workspace_contract is not None
    raw["interface"]["output"]["kind"] = "stdout"
    with pytest.raises(ValidationError, match="output must be a directory"):
        ToolSpec.model_validate(raw)


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("data/*.csv", "data/a.csv", True),
        ("data/*.csv", "data/nested/a.csv", False),
        ("site/**/index.html", "site/index.html", True),
        ("site/**/index.html", "site/a/b/index.html", True),
        ("site/**/index.html", "other/index.html", False),
    ],
)
def test_restricted_workspace_glob(pattern: str, path: str, expected: bool) -> None:
    assert workspace_path_matches(pattern, path) is expected


@pytest.mark.parametrize(
    "path",
    ["/absolute", "../escape", "a//b", "a\\b", "a[0].txt", "a/**x/b"],
)
def test_workspace_contract_rejects_unsafe_patterns(path: str) -> None:
    with pytest.raises(ValidationError):
        WorkspaceArtifactRule(
            path_pattern=path,
            role="unsafe",
            media_type="text/plain",
            validation_profile="text_utf8_v1",
        )


def test_manifest_is_stable_and_binds_mode(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    _valid_tree(root)
    first = build_artifact_manifest(root)
    second = build_artifact_manifest(root)
    assert first == second
    runner = root / "scripts" / "run.sh"
    runner.chmod(0o644)
    changed = build_artifact_manifest(root)
    assert changed.tree_sha256 != first.tree_sha256


def test_structural_and_format_validation(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    _valid_tree(root)
    result = validate_workspace(root, _contract())
    assert result.ok is True
    assert result.manifest is not None
    assert result.matched_paths["data/*.csv"] == ("data/rows.csv",)

    (root / "unexpected.txt").write_text("not contracted", encoding="utf-8")
    result = validate_workspace(root, _contract())
    assert result.ok is False
    assert "WORKSPACE_EXTRA_FILE_FORBIDDEN" in result.reason_codes


def test_runnable_workspace_smoke_is_bounded_and_hashed(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    _valid_tree(root)
    evidence = run_workspace_smoke(root, _contract(), isolation_required=False)
    assert evidence.passed is True
    assert evidence.exit_code == 0
    assert evidence.artifact_tree_sha256 == build_artifact_manifest(root).tree_sha256
    assert evidence.reason_codes == ()


def test_runnable_contract_requires_frozen_entrypoint_command() -> None:
    with pytest.raises(ValidationError, match="frozen smoke command"):
        WorkspaceArtifactContractV1(
            rules=_contract().rules,
            entrypoints=("scripts/run.sh",),
            runnable=True,
        )


def test_workspace_smoke_reports_nonzero_without_mutating_original(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    _valid_tree(root)
    runner = root / "scripts" / "run.sh"
    runner.write_text(
        "#!/usr/bin/env bash\nprintf changed > README.md\nexit 7\n",
        encoding="utf-8",
    )
    before = build_artifact_manifest(root)
    evidence = run_workspace_smoke(root, _contract(), isolation_required=False)
    assert evidence.passed is False
    assert evidence.exit_code == 7
    assert "WORKSPACE_SMOKE_NONZERO_EXIT" in evidence.reason_codes
    assert build_artifact_manifest(root) == before


def test_format_profiles_cover_structured_workspace_files(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "config.yaml").write_text("value: 1\n", encoding="utf-8")
    (root / "config.toml").write_text("value = 1\n", encoding="utf-8")
    (root / "payload.json").write_text('{"value": 1}\n', encoding="utf-8")
    (root / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "index.html").write_text("<!doctype html><p>offline</p>\n", encoding="utf-8")
    (root / "graph.xml").write_text("<graph><node /></graph>\n", encoding="utf-8")
    (root / "figure.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>\n", encoding="utf-8")
    database = root / "data.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("create table rows(value integer)")
    connection.commit()
    connection.close()
    rules = []
    for name, profile, media in (
        ("config.yaml", "yaml_v1", "application/yaml"),
        ("config.toml", "toml_v1", "application/toml"),
        ("payload.json", "json_v1", "application/json"),
        ("module.py", "python_compile_v1", "text/x-python"),
        ("index.html", "html_v1", "text/html"),
        ("graph.xml", "xml_v1", "application/xml"),
        ("figure.svg", "svg_xml_v1", "image/svg+xml"),
        ("data.sqlite", "sqlite_v1", "application/vnd.sqlite3"),
    ):
        rules.append(
            WorkspaceArtifactRule(
                path_pattern=name,
                role=name,
                media_type=media,
                validation_profile=profile,
            )
        )
    result = validate_workspace(
        root,
        WorkspaceArtifactContractV1(rules=tuple(rules)),
    )
    assert result.ok is True


def test_html_external_resources_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "index.html").write_text(
        '<img src="https://example.invalid/tracker.png">',
        encoding="utf-8",
    )
    contract = WorkspaceArtifactContractV1(
        rules=(
            WorkspaceArtifactRule(
                path_pattern="index.html",
                role="site",
                media_type="text/html",
                validation_profile="html_v1",
            ),
        )
    )
    result = validate_workspace(root, contract)
    assert result.ok is False
    assert "WORKSPACE_HTML_EXTERNAL_RESOURCE" in result.reason_codes


def test_symlink_hardlink_and_fifo_are_rejected(tmp_path: Path) -> None:
    for name, creator, expected in (
        (
            "symlink",
            lambda root: (root / "bad").symlink_to(root / "target"),
            "WORKSPACE_SYMLINK_FORBIDDEN",
        ),
        (
            "hardlink",
            lambda root: os.link(root / "target", root / "bad"),
            "WORKSPACE_HARDLINK_FORBIDDEN",
        ),
        (
            "fifo",
            lambda root: os.mkfifo(root / "bad"),
            "WORKSPACE_SPECIAL_FILE",
        ),
    ):
        root = tmp_path / name
        root.mkdir()
        (root / "target").write_text("x", encoding="utf-8")
        creator(root)
        with pytest.raises(WorkspaceBundleError) as caught:
            build_artifact_manifest(root)
        assert caught.value.code == expected


def test_limits_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "a").write_bytes(b"12")
    limits = WorkspaceArtifactLimits(
        max_files=1,
        max_total_bytes=1,
        max_file_bytes=1,
    )
    with pytest.raises(WorkspaceBundleError) as caught:
        build_artifact_manifest(root, limits)
    assert caught.value.code == "WORKSPACE_FILE_TOO_LARGE"


def test_atomic_materialization_publishes_only_valid_tree(tmp_path: Path) -> None:
    destination = tmp_path / "result"

    def builder(root: Path) -> None:
        _valid_tree(root)

    result = materialize_workspace_atomic(destination, builder, _contract())
    assert result.ok is True
    assert destination.is_dir()
    assert not list(tmp_path.glob(".result.rp-*"))

    with pytest.raises(WorkspaceBundleError) as caught:
        materialize_workspace_atomic(destination, builder, _contract())
    assert caught.value.code == "WORKSPACE_OUTPUT_ALREADY_EXISTS"


def test_atomic_materialization_removes_failed_partial_tree(tmp_path: Path) -> None:
    destination = tmp_path / "result"

    def invalid_builder(root: Path) -> None:
        (root / "partial.txt").write_text("partial", encoding="utf-8")

    with pytest.raises(WorkspaceBundleError) as caught:
        materialize_workspace_atomic(destination, invalid_builder, _contract())
    assert caught.value.code == "WORKSPACE_CONTRACT_FAILED"
    assert not destination.exists()
    assert not list(tmp_path.glob(".result.rp-*"))


def test_input_identity_supports_file_and_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "input.yaml"
    file_path.write_text("value: 1\n", encoding="utf-8")
    file_identity = identify_input_path(file_path)
    assert file_identity.kind == "file"
    assert file_identity.file_count == 1

    directory = tmp_path / "inputs"
    directory.mkdir()
    (directory / "a.txt").write_text("a", encoding="utf-8")
    directory_identity = identify_input_path(directory)
    assert directory_identity.kind == "directory"
    assert directory_identity.sha256 == build_artifact_manifest(directory).tree_sha256


def test_snapshot_admitted_path_copies_file_and_directory(tmp_path: Path) -> None:
    source_file = tmp_path / "input.txt"
    source_file.write_text("stable\n", encoding="utf-8")
    file_snapshot = tmp_path / "snapshots" / "input.txt"
    file_identity = snapshot_admitted_path(source_file, file_snapshot)
    assert file_identity == identify_input_path(file_snapshot)

    source_dir = tmp_path / "input-dir"
    source_dir.mkdir()
    (source_dir / "a.txt").write_text("a", encoding="utf-8")
    executable = source_dir / "run.sh"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    directory_snapshot = tmp_path / "snapshots" / "input-dir"
    directory_identity = snapshot_admitted_path(source_dir, directory_snapshot)
    assert directory_identity == identify_input_path(directory_snapshot)
    assert stat.S_IMODE((directory_snapshot / "run.sh").stat().st_mode) == 0o755


def test_snapshot_admitted_path_rejects_unsafe_sources(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (source / "link").symlink_to(outside)
    with pytest.raises(WorkspaceBundleError) as caught:
        snapshot_admitted_path(source, tmp_path / "snapshot")
    assert caught.value.code == "WORKSPACE_SYMLINK_FORBIDDEN"
    assert not (tmp_path / "snapshot").exists()


def test_deterministic_zip_is_transport_only_but_reproducible(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    _valid_tree(root)
    first = write_deterministic_zip(root, tmp_path / "first.zip")
    second = write_deterministic_zip(root, tmp_path / "second.zip")
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert archive.testzip() is None
        assert sorted(archive.namelist()) == [
            "README.md",
            "data/rows.csv",
            "scripts/run.sh",
        ]


def test_manifest_rejects_mode_and_path_tampering(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    _valid_tree(root)
    manifest = build_artifact_manifest(root)
    data = manifest.model_dump(mode="json")
    data["entries"][0]["path"] = "../escape"
    with pytest.raises(ValidationError):
        type(manifest).model_validate(data)
    data = manifest.model_dump(mode="json")
    data["entries"][0]["mode"] = stat.S_IFIFO
    with pytest.raises(ValidationError):
        type(manifest).model_validate(data)


def test_manifest_json_round_trip_is_canonical(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    _valid_tree(root)
    manifest = build_artifact_manifest(root)
    payload = json.dumps(manifest.model_dump(mode="json"), sort_keys=True)
    assert type(manifest).model_validate_json(payload) == manifest
