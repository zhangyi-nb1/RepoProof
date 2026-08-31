from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from repoproof.adoption.delivery.portable_workspace_runtime import (
    WorkspaceRuntimeError,
    materialize_workspace,
    seal_offline_python_runtime,
)
from repoproof.domain.models import WorkspaceArtifactContractV1
from repoproof.execution.workspace_bundle import run_workspace_smoke


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


def _runtime_contract() -> dict:
    contract = _contract()
    contract.update(
        {
            "rules": [
                {
                    "path_pattern": "app.py",
                    "role": "application",
                    "media_type": "text/x-python",
                    "validation_profile": "python_compile_v1",
                    "min_count": 1,
                    "max_count": 1,
                    "executable": False,
                },
                {
                    "path_pattern": "run.sh",
                    "role": "launcher",
                    "media_type": "text/x-shellscript",
                    "validation_profile": "shell_v1",
                    "min_count": 1,
                    "max_count": 1,
                    "executable": True,
                },
                {
                    "path_pattern": "requirements.lock.txt",
                    "role": "lock",
                    "media_type": "text/plain",
                    "validation_profile": "text_utf8_v1",
                    "min_count": 1,
                    "max_count": 1,
                    "executable": False,
                },
                {
                    "path_pattern": "THIRD_PARTY_NOTICES.md",
                    "role": "inventory",
                    "media_type": "text/markdown",
                    "validation_profile": "text_utf8_v1",
                    "min_count": 1,
                    "max_count": 1,
                    "executable": False,
                },
                {
                    "path_pattern": "vendor/wheels/*.whl",
                    "role": "wheels",
                    "media_type": "application/zip",
                    "validation_profile": "wheel_v1",
                    "min_count": 1,
                    "max_count": 4,
                    "executable": False,
                },
            ],
            "entrypoints": ["run.sh"],
            "smoke_command": ["./run.sh", "--help"],
            "smoke_timeout_seconds": 30,
            "require_offline_wheelhouse": True,
            "runtime_python_entrypoint": "app.py",
            "limits": {
                "max_files": 16,
                "max_total_bytes": 1024 * 1024,
                "max_file_bytes": 512 * 1024,
                "max_depth": 4,
                "max_path_bytes": 120,
            },
        }
    )
    return contract


def _minimal_wheel(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("demo_runtime/__init__.py", "VALUE = 'sealed'\n")
        archive.writestr(
            "demo_runtime-1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: demo-runtime\nVersion: 1.0\n",
        )
        archive.writestr(
            "demo_runtime-1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: repoproof-test\n"
            "Root-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr("demo_runtime-1.0.dist-info/RECORD", "")


def test_portable_runtime_seals_and_executes_offline_python_closure(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.txt"
    source.write_text("input", encoding="utf-8")
    runtime = tmp_path / "runtime"
    wheels = runtime / "vendor" / "wheels"
    wheels.mkdir(parents=True)
    _minimal_wheel(wheels / "demo_runtime-1.0-py3-none-any.whl")
    (runtime / "requirements.lock.txt").write_text(
        "demo-runtime==1.0\n", encoding="utf-8"
    )

    def builder(_source: Path, output: Path) -> None:
        (output / "app.py").write_text(
            "import demo_runtime, sys\n"
            "assert demo_runtime.VALUE == 'sealed'\n"
            "print('ready' if '--help' in sys.argv else demo_runtime.VALUE)\n",
            encoding="utf-8",
        )

    output = tmp_path / "output"
    contract = _runtime_contract()
    materialize_workspace(
        builder,
        source,
        output,
        contract,
        runtime_source_root=runtime,
    )

    assert (output / "run.sh").stat().st_mode & 0o111
    assert not ((output / "app.py").stat().st_mode & 0o111)
    assert (output / "requirements.lock.txt").read_text() == "demo-runtime==1.0\n"
    smoke = run_workspace_smoke(
        output,
        WorkspaceArtifactContractV1.model_validate(contract),
        isolation_required=False,
    )
    assert smoke.passed, smoke.reason_codes


def test_runtime_seal_rejects_builder_collision(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    (output / "app.py").write_text("pass\n", encoding="utf-8")
    (output / "run.sh").write_text("model-owned\n", encoding="utf-8")
    runtime = tmp_path / "runtime"
    wheels = runtime / "vendor" / "wheels"
    wheels.mkdir(parents=True)
    _minimal_wheel(wheels / "demo_runtime-1.0-py3-none-any.whl")
    lock = runtime / "requirements.lock.txt"
    lock.write_text("demo-runtime==1.0\n", encoding="utf-8")

    with pytest.raises(
        WorkspaceRuntimeError, match="WORKSPACE_RUNTIME_OWNED_PATH_COLLISION"
    ):
        seal_offline_python_runtime(
            output,
            _runtime_contract(),
            wheelhouse=wheels,
            requirements_lock=lock,
        )
