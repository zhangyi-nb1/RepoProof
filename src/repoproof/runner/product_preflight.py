"""Zero-model Product journey preflight.

This gate proves the frozen contract, offline dependency bundle, pinned
upstream import, and first confirmed public example are mutually executable
before any Coding Agent or repair round can consume budget.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from repoproof.adoption.assembly.output_contract import validate_output_text
from repoproof.adoption.intake.upstream_pin import normalize_dist_name
from repoproof.domain.models import TaskPackageManifest, WorkspaceArtifactContractV1
from repoproof.execution.workspace_bundle import (
    build_artifact_manifest,
    run_workspace_smoke,
    validate_workspace,
)
from repoproof.verification.output_match import compare_output

PreflightOwner = Literal["HARNESS", "UPSTREAM", "CONTRACT", "USER_INPUT"]


class ProductPreflightCheck(BaseModel):
    name: str
    ok: bool
    reason_code: str | None = None
    detail: str = ""


class ProductPreflightResult(BaseModel):
    schema_version: int = 1
    ok: bool
    failure_owner: PreflightOwner | None = None
    reason_codes: list[str] = Field(default_factory=list)
    recommended_action: str = "STOP"
    product_stop_code: str = ""
    checks: list[ProductPreflightCheck] = Field(default_factory=list)


def _failure(
    checks: list[ProductPreflightCheck],
    *,
    owner: PreflightOwner,
    code: str,
    detail: str,
) -> ProductPreflightResult:
    checks.append(
        ProductPreflightCheck(name=code.lower(), ok=False, reason_code=code, detail=detail)
    )
    return ProductPreflightResult(
        ok=False,
        failure_owner=owner,
        reason_codes=[code],
        recommended_action=(
            "ASK_USER" if owner in {"CONTRACT", "USER_INPUT"}
            else "RETRY_INFRASTRUCTURE"
        ),
        product_stop_code=(
            "STOP_NEEDS_HUMAN"
            if owner in {"CONTRACT", "USER_INPUT"}
            else "STOP_HARNESS_OR_EXTERNAL"
        ),
        checks=checks,
    )


def _load_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} 根节点必须是 object")
    return value


def _lock_pins(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _pin_distribution(pin: str) -> str:
    return normalize_dist_name(re.split(r"[=<>!~\[]", pin, maxsplit=1)[0])


def _wheelhouse_has_distribution(wheelhouse: Path, distribution: str) -> bool:
    wanted = normalize_dist_name(distribution)
    for path in wheelhouse.iterdir():
        if not path.is_file():
            continue
        filename_dist = normalize_dist_name(path.name.split("-", 1)[0])
        if filename_dist == wanted:
            return True
    return False


def _fixture_path(skeleton: Path, relative: str) -> Path | None:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    candidates = (
        skeleton / "public_examples" / rel,
        skeleton / "public_tests" / "fixtures" / rel,
    )
    return next((path for path in candidates if path.exists() and not path.is_symlink()), None)


_REFERENCE_RUNNER = """
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("repoproof_reference", sys.argv[1])
if spec is None or spec.loader is None:
    raise RuntimeError("reference module cannot be loaded")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
result = module.extract(Path(sys.argv[2]))
if not isinstance(result, str):
    raise TypeError("reference extract() must return str")
sys.stdout.write(result)
""".strip()


_WORKSPACE_REFERENCE_RUNNER = """
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("repoproof_reference", sys.argv[1])
if spec is None or spec.loader is None:
    raise RuntimeError("reference module cannot be loaded")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
result = module.build_workspace(Path(sys.argv[2]), Path(sys.argv[3]))
if result is not None:
    raise TypeError("reference build_workspace() must return None")
""".strip()


def run_product_preflight(
    *,
    project_root: Path,
    task_id: str,
    tool_contract_path: Path,
    host_contract_path: Path,
    wheelhouse: Path,
) -> ProductPreflightResult:
    """Run all Product pre-agent checks in a disposable offline venv."""

    project_root = Path(project_root)
    checks: list[ProductPreflightCheck] = []
    try:
        tool_contract = _load_yaml(Path(tool_contract_path))
        host_contract = _load_yaml(Path(host_contract_path))
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        return _failure(
            checks, owner="CONTRACT", code="FROZEN_CONTRACT_INVALID", detail=str(exc)
        )

    tool_source = tool_contract.get("source_repo") or {}
    host_source = host_contract.get("source_repo") or {}
    commit = str(tool_source.get("resolved_commit") or "")
    if (
        tool_contract.get("task_id") != task_id
        or host_contract.get("task_id") != task_id
        or not commit
        or commit != str(host_source.get("resolved_commit") or "")
    ):
        return _failure(
            checks,
            owner="CONTRACT",
            code="TASK_CONTRACT_IDENTITY_MISMATCH",
            detail="工具合同、宿主合同与 task_id/resolved commit 不一致",
        )
    checks.append(ProductPreflightCheck(name="contract_identity", ok=True))

    package_manifest: TaskPackageManifest | None = None
    tool_document = tool_contract.get("tool") or {}
    tool_schema_version = int(tool_document.get("schema_version") or 1)
    delivery_profile_id = str(tool_document.get("delivery_profile_id") or "cli_v2")
    workspace_contract: WorkspaceArtifactContractV1 | None = None
    if delivery_profile_id == "workspace_bundle_v1":
        if tool_schema_version != 4:
            return _failure(
                checks,
                owner="CONTRACT",
                code="WORKSPACE_PROFILE_SCHEMA_MISMATCH",
                detail="workspace_bundle_v1 必须由 ToolSpec v4 冻结",
            )
        try:
            workspace_contract = WorkspaceArtifactContractV1.model_validate(
                tool_document.get("workspace_contract")
            )
        except (TypeError, ValueError) as exc:
            return _failure(
                checks,
                owner="CONTRACT",
                code="WORKSPACE_CONTRACT_INVALID",
                detail=str(exc),
            )
    if tool_schema_version >= 3:
        from repoproof.harness.task_package import load_and_verify

        try:
            package_manifest = load_and_verify(
                project_root,
                Path(tool_contract_path),
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            return _failure(
                checks,
                owner="HARNESS",
                code="FROZEN_TASK_PACKAGE_INVALID",
                detail=(
                    "ToolSpec v3 冻结证据束缺失、损坏或与合同/oracle/目标骨架不一致"
                ),
            )
        if (
            package_manifest.source_commit != commit
            or not package_manifest.source_git_tree_hash
            or not package_manifest.wheelhouse_root
            or not package_manifest.wheelhouse_wheels
        ):
            return _failure(
                checks,
                owner="HARNESS",
                code="FROZEN_TASK_PACKAGE_INVALID",
                detail="ToolSpec v3 冻结证据束没有完整的 upstream/wheelhouse 身份",
            )
        checks.append(ProductPreflightCheck(name="frozen_task_package", ok=True))

    upstream = project_root / "upstream-cache" / f"upstream-{commit[:12]}"
    try:
        head = subprocess.run(
            ["git", "-C", str(upstream), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _failure(
            checks, owner="UPSTREAM", code="PINNED_UPSTREAM_UNREADABLE", detail=str(exc)
        )
    if head.returncode != 0 or head.stdout.strip() != commit:
        return _failure(
            checks,
            owner="UPSTREAM",
            code="PINNED_UPSTREAM_COMMIT_MISMATCH",
            detail="钉版上游目录缺失或 HEAD 与冻结合同不一致",
        )
    checks.append(ProductPreflightCheck(name="pinned_upstream", ok=True))

    distribution = str(tool_source.get("distribution") or "")
    import_module = str(tool_source.get("import_module") or "")
    lock = project_root / "controls" / task_id / "reference" / "requirements.lock.txt"
    pins = _lock_pins(lock)
    if not distribution or not any(
        _pin_distribution(pin) == normalize_dist_name(distribution) for pin in pins
    ):
        return _failure(
            checks,
            owner="HARNESS",
            code="UPSTREAM_PIN_MISSING",
            detail="reference requirements.lock.txt 未包含冻结 upstream distribution",
        )
    checks.append(ProductPreflightCheck(name="upstream_pin", ok=True))

    wheelhouse = Path(wheelhouse)
    if not wheelhouse.is_dir() or not _wheelhouse_has_distribution(
        wheelhouse, distribution
    ):
        return _failure(
            checks,
            owner="HARNESS",
            code="UPSTREAM_WHEEL_MISSING",
            detail="离线 wheelhouse 未包含冻结 upstream distribution",
        )
    checks.append(ProductPreflightCheck(name="wheelhouse_upstream", ok=True))
    if package_manifest is not None:
        from repoproof.harness.wheelhouse import verify_wheelhouse

        try:
            verify_wheelhouse(
                wheelhouse,
                expected_wheels=dict(package_manifest.wheelhouse_wheels or {}),
                expected_root=str(package_manifest.wheelhouse_root or ""),
            )
        except (OSError, RuntimeError, ValueError):
            return _failure(
                checks,
                owner="HARNESS",
                code="FROZEN_WHEELHOUSE_IDENTITY_MISMATCH",
                detail="当前 wheelhouse 与冻结任务包的文件集合或哈希不一致",
            )
        checks.append(ProductPreflightCheck(name="frozen_wheelhouse", ok=True))

    reference = project_root / "controls" / task_id / "reference" / "impl.py"
    skeleton = project_root / str((tool_contract.get("target_project") or {}).get("path") or "")
    truth_path = skeleton / "public_examples" / "truth_table.json"
    try:
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        first = (truth.get("examples") or [])[0]
        if delivery_profile_id == "workspace_bundle_v1":
            input_path = _fixture_path(
                skeleton, f"{first['example_id']}/input"
            )
            expected_path = _fixture_path(
                skeleton, f"{first['example_id']}/expected"
            )
        else:
            input_path = _fixture_path(skeleton, str(first["input_file"]))
            expected_path = _fixture_path(skeleton, str(first["expected_file"]))
    except (OSError, UnicodeError, ValueError, KeyError, IndexError, TypeError) as exc:
        return _failure(
            checks,
            owner="USER_INPUT",
            code="PUBLIC_EXAMPLE_MISSING",
            detail=f"第一个已确认公开样例无法读取：{exc}",
        )
    if input_path is None or expected_path is None or not reference.is_file():
        return _failure(
            checks,
            owner="USER_INPUT",
            code="PUBLIC_EXAMPLE_MISSING",
            detail="公开样例输入、期望值或冻结 reference implementation 缺失",
        )
    checks.append(ProductPreflightCheck(name="public_example", ok=True))

    with tempfile.TemporaryDirectory(prefix="rp-product-preflight-") as temp:
        temp_root = Path(temp)
        venv = temp_root / "venv"
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", str(venv)],
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
            python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            installed = subprocess.run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-index",
                    "--find-links",
                    str(wheelhouse),
                    *pins,
                ],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return _failure(
                checks,
                owner="HARNESS",
                code="OFFLINE_INSTALL_FAILED",
                detail=f"离线预检环境创建失败：{exc}",
            )
        if installed.returncode != 0:
            return _failure(
                checks,
                owner="HARNESS",
                code="OFFLINE_INSTALL_FAILED",
                detail="依赖锁无法仅从 wheelhouse 安装",
            )
        checks.append(ProductPreflightCheck(name="offline_install", ok=True))

        imported = subprocess.run(
            [str(python), "-c", "import importlib,sys; importlib.import_module(sys.argv[1])", import_module],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if imported.returncode != 0:
            return _failure(
                checks,
                owner="UPSTREAM",
                code="UPSTREAM_IMPORT_FAILED",
                detail="冻结 import_module 无法在离线预检环境导入",
            )
        checks.append(ProductPreflightCheck(name="upstream_import", ok=True))

        runner = temp_root / "run_reference.py"
        reference_output = temp_root / "reference-output"
        if delivery_profile_id == "workspace_bundle_v1":
            reference_output.mkdir()
            runner.write_text(_WORKSPACE_REFERENCE_RUNNER + "\n", encoding="utf-8")
            reference_command = [
                str(python),
                str(runner),
                str(reference),
                str(input_path),
                str(reference_output),
            ]
        else:
            runner.write_text(_REFERENCE_RUNNER + "\n", encoding="utf-8")
            reference_command = [
                str(python), str(runner), str(reference), str(input_path)
            ]
        reference_run = subprocess.run(
            reference_command,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if reference_run.returncode != 0:
            return _failure(
                checks,
                owner="CONTRACT",
                code="REFERENCE_EXECUTION_FAILED",
                detail="冻结 reference implementation 无法运行第一个公开样例",
            )
        checks.append(ProductPreflightCheck(name="reference_execution", ok=True))

        if workspace_contract is not None:
            structure = validate_workspace(reference_output, workspace_contract)
            if not structure.ok:
                return _failure(
                    checks,
                    owner="CONTRACT",
                    code="REFERENCE_WORKSPACE_CONTRACT_MISMATCH",
                    detail="；".join(structure.reason_codes[:3]),
                )
            checks.append(
                ProductPreflightCheck(name="reference_workspace_contract", ok=True)
            )
            actual_manifest = build_artifact_manifest(
                reference_output, limits=workspace_contract.limits
            )
            expected_manifest = build_artifact_manifest(
                expected_path, limits=workspace_contract.limits
            )
            if actual_manifest.tree_sha256 != expected_manifest.tree_sha256:
                return _failure(
                    checks,
                    owner="CONTRACT",
                    code="REFERENCE_GOLDEN_MISMATCH",
                    detail="冻结 reference 目录树与第一个用户确认的期望工作区不一致",
                )
            checks.append(
                ProductPreflightCheck(name="reference_workspace_golden", ok=True)
            )
            if workspace_contract.runnable:
                runtime = run_workspace_smoke(reference_output, workspace_contract)
                if not runtime.passed:
                    isolation_unavailable = (
                        "WORKSPACE_SMOKE_ISOLATION_UNAVAILABLE"
                        in runtime.reason_codes
                    )
                    return _failure(
                        checks,
                        owner="HARNESS" if isolation_unavailable else "CONTRACT",
                        code=(
                            "WORKSPACE_SMOKE_ISOLATION_UNAVAILABLE"
                            if isolation_unavailable
                            else "REFERENCE_WORKSPACE_SMOKE_FAILED"
                        ),
                        detail="；".join(runtime.reason_codes[:3]),
                    )
                checks.append(
                    ProductPreflightCheck(name="reference_workspace_smoke", ok=True)
                )

    if workspace_contract is not None:
        return ProductPreflightResult(ok=True, checks=checks)

    output = ((tool_document.get("interface") or {}).get("output") or {})
    output_contract = output.get("contract") or {
        "media_type": "text/plain",
        "root_type": "text",
        "required": {},
    }
    errors = validate_output_text(reference_run.stdout, output_contract)
    if errors:
        return _failure(
            checks,
            owner="CONTRACT",
            code="REFERENCE_OUTPUT_CONTRACT_MISMATCH",
            detail="；".join(errors[:3]),
        )
    try:
        expected = expected_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return _failure(
            checks,
            owner="USER_INPUT",
            code="PUBLIC_EXPECTED_OUTPUT_INVALID",
            detail=str(exc),
        )
    root_type = str((output_contract or {}).get("root_type") or "text")
    matches, _mode = compare_output(reference_run.stdout, expected, root_type=root_type)
    if not matches:
        return _failure(
            checks,
            owner="CONTRACT",
            code="REFERENCE_GOLDEN_MISMATCH",
            detail="冻结 reference 输出与第一个用户确认的期望值不一致",
        )
    checks.append(ProductPreflightCheck(name="reference_output_contract", ok=True))
    return ProductPreflightResult(ok=True, checks=checks)


def cleanup_preflight_artifacts(path: Path) -> None:
    """Compatibility helper for callers that allocated an external temp root."""

    shutil.rmtree(path, ignore_errors=True)
