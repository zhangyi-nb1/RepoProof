from __future__ import annotations

from pathlib import Path

import pytest

from repoproof.adoption.delivery.portable_workspace_runtime import (
    WorkspaceRuntimeError,
    materialize_workspace,
)


def _contract() -> dict:
    return {
        "schema_version": 1,
        "rules": [
            {
                "path_pattern": "README.md",
                "role": "docs",
                "media_type": "text/markdown",
                "validation_profile": "text_utf8_v1",
                "min_count": 1,
                "max_count": 1,
                "executable": False,
            },
            {
                "path_pattern": "run.sh",
                "role": "entrypoint",
                "media_type": "text/x-shellscript",
                "validation_profile": "shell_v1",
                "min_count": 1,
                "max_count": 1,
                "executable": True,
            },
        ],
        "allow_extra_files": False,
        "entrypoints": ["run.sh"],
        "runnable": True,
        "smoke_command": ["./run.sh"],
        "smoke_timeout_seconds": 5,
        "require_offline_wheelhouse": False,
        "limits": {
            "max_files": 10,
            "max_total_bytes": 4096,
            "max_file_bytes": 2048,
            "max_depth": 4,
            "max_path_bytes": 120,
        },
    }


def _builder(_source: Path, output: Path) -> None:
    (output / "README.md").write_text("# Ready\n", encoding="utf-8")
    runner = output / "run.sh"
    runner.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    runner.chmod(0o755)


def test_portable_runtime_atomically_materializes_workspace(tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("input", encoding="utf-8")
    output = tmp_path / "output"
    materialize_workspace(_builder, source, output, _contract())
    assert (output / "README.md").is_file()
    assert not list(tmp_path.glob(".output.rp-*"))


def test_portable_runtime_cleans_failed_partial_directory(tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("input", encoding="utf-8")
    output = tmp_path / "output"

    def invalid(_source: Path, partial: Path) -> None:
        (partial / "unexpected").write_text("bad", encoding="utf-8")

    with pytest.raises(WorkspaceRuntimeError, match="WORKSPACE_EXTRA_FILE"):
        materialize_workspace(invalid, source, output, _contract())
    assert not output.exists()
    assert not list(tmp_path.glob(".output.rp-*"))


def test_portable_runtime_rejects_existing_output_and_symlink(tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("input", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(WorkspaceRuntimeError, match="WORKSPACE_OUTPUT_ALREADY_EXISTS"):
        materialize_workspace(_builder, source, output, _contract())

    output.rmdir()

    def linked(_source: Path, partial: Path) -> None:
        (partial / "README.md").write_text("# Ready\n", encoding="utf-8")
        (partial / "run.sh").symlink_to("README.md")

    with pytest.raises(WorkspaceRuntimeError, match="WORKSPACE_SYMLINK_FORBIDDEN"):
        materialize_workspace(linked, source, output, _contract())
