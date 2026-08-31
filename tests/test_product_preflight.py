"""Zero-model preflight catches environment and contract faults before Agent."""

from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import yaml

from repoproof.runner.product_preflight import run_product_preflight


def _world(tmp_path: Path) -> dict[str, Path | str]:
    project = tmp_path / "project"
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    wheel = wheelhouse / "demo_upstream-1.0-py3-none-any.whl"
    dist_info = "demo_upstream-1.0.dist-info"
    records = [
        "demo_upstream.py,,",
        f"{dist_info}/METADATA,,",
        f"{dist_info}/WHEEL,,",
        f"{dist_info}/RECORD,,",
    ]
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "demo_upstream.py", "def convert(value):\n    return value.upper()\n"
        )
        archive.writestr(
            f"{dist_info}/METADATA",
            "Metadata-Version: 2.1\nName: demo-upstream\nVersion: 1.0\n",
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: RepoProof test\n"
            "Root-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(f"{dist_info}/RECORD", "\n".join(records) + "\n")

    upstream = project / "upstream-cache" / "pending"
    upstream.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(upstream)], check=True)
    (upstream / "README.md").write_text("demo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(upstream), "add", "README.md"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(upstream),
            "-c",
            "user.name=RepoProof Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    commit = subprocess.run(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    pinned = project / "upstream-cache" / f"upstream-{commit[:12]}"
    upstream.rename(pinned)

    task_id = "tool-demo-v1"
    reference_dir = project / "controls" / task_id / "reference"
    reference_dir.mkdir(parents=True)
    (reference_dir / "requirements.lock.txt").write_text(
        "demo-upstream==1.0\n", encoding="utf-8"
    )
    (reference_dir / "impl.py").write_text(
        "import json\nfrom pathlib import Path\nimport demo_upstream\n"
        "def extract(input_path: Path) -> str:\n"
        "    return json.dumps({'value': demo_upstream.convert(input_path.read_text())}, separators=(',', ':'))\n",
        encoding="utf-8",
    )
    skeleton = project / "fixtures" / "tool_skeleton_demo"
    fixtures = skeleton / "public_tests" / "fixtures"
    (fixtures / "inputs").mkdir(parents=True)
    (fixtures / "expected").mkdir()
    (skeleton / "public_examples").mkdir()
    (fixtures / "inputs" / "one.txt").write_text("alpha", encoding="utf-8")
    (fixtures / "expected" / "one.json").write_text(
        '{"value":"ALPHA"}\n', encoding="utf-8"
    )
    (skeleton / "public_examples" / "truth_table.json").write_text(
        json.dumps({
            "examples": [{
                "input_file": "inputs/one.txt",
                "expected_file": "expected/one.json",
            }]
        }),
        encoding="utf-8",
    )
    contracts = project / "contracts"
    contracts.mkdir()
    tool_contract = contracts / f"{task_id}.yaml"
    tool_contract.write_text(
        yaml.safe_dump({
            "task_id": task_id,
            "source_repo": {
                "resolved_commit": commit,
                "distribution": "demo-upstream",
                "import_module": "demo_upstream",
            },
            "target_project": {"path": "fixtures/tool_skeleton_demo"},
            "tool": {"interface": {"output": {"contract": {
                "media_type": "application/json",
                "root_type": "object",
                "required": {"value": "string"},
            }}}},
        }),
        encoding="utf-8",
    )
    host_contract = project / "tool_tasks" / task_id / "contract.yaml"
    host_contract.parent.mkdir(parents=True)
    host_contract.write_text(
        yaml.safe_dump({
            "task_id": task_id,
            "source_repo": {"resolved_commit": commit},
            "host": {"wheelhouse_path": str(wheelhouse)},
        }),
        encoding="utf-8",
    )
    return {
        "project": project,
        "task_id": task_id,
        "tool_contract": tool_contract,
        "host_contract": host_contract,
        "wheelhouse": wheelhouse,
        "expected": fixtures / "expected" / "one.json",
    }


def _run(world: dict[str, Path | str]):
    return run_product_preflight(
        project_root=Path(world["project"]),
        task_id=str(world["task_id"]),
        tool_contract_path=Path(world["tool_contract"]),
        host_contract_path=Path(world["host_contract"]),
        wheelhouse=Path(world["wheelhouse"]),
    )


def _mark_tool_contract_v3(world: dict[str, Path | str]) -> dict:
    contract_path = Path(world["tool_contract"])
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    contract["tool"]["schema_version"] = 3
    contract_path.write_text(
        yaml.safe_dump(contract, sort_keys=False),
        encoding="utf-8",
    )
    return contract


def test_product_preflight_proves_offline_reference_path(tmp_path: Path) -> None:
    result = _run(_world(tmp_path))
    assert result.ok is True
    assert [check.name for check in result.checks] == [
        "contract_identity",
        "pinned_upstream",
        "upstream_pin",
        "wheelhouse_upstream",
        "public_example",
        "offline_install",
        "upstream_import",
        "reference_execution",
        "reference_output_contract",
    ]


def test_v3_preflight_stops_before_agent_when_task_package_is_missing(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    _mark_tool_contract_v3(world)

    result = _run(world)

    assert result.ok is False
    assert result.failure_owner == "HARNESS"
    assert result.reason_codes == ["FROZEN_TASK_PACKAGE_INVALID"]
    assert all(check.name != "offline_install" for check in result.checks)


def test_v3_preflight_binds_complete_wheelhouse_before_agent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from repoproof.harness.wheelhouse import compute_manifest

    world = _world(tmp_path)
    contract = _mark_tool_contract_v3(world)
    wheelhouse = Path(world["wheelhouse"])
    wheel_manifest = compute_manifest(wheelhouse)
    frozen = SimpleNamespace(
        source_commit=contract["source_repo"]["resolved_commit"],
        source_git_tree_hash="a" * 40,
        wheelhouse_root=wheel_manifest["root"],
        wheelhouse_wheels=wheel_manifest["wheels"],
    )
    monkeypatch.setattr(
        "repoproof.harness.task_package.load_and_verify",
        lambda *_args, **_kwargs: frozen,
    )

    result = _run(world)

    assert result.ok is True
    assert "frozen_task_package" in [check.name for check in result.checks]
    assert "frozen_wheelhouse" in [check.name for check in result.checks]

    wheel = next(wheelhouse.glob("*.whl"))
    wheel.write_bytes(wheel.read_bytes() + b"tamper")
    rejected = _run(world)
    assert rejected.ok is False
    assert rejected.reason_codes == ["FROZEN_WHEELHOUSE_IDENTITY_MISMATCH"]
    assert all(check.name != "offline_install" for check in rejected.checks)


def test_missing_upstream_wheel_stops_as_harness_fault(tmp_path: Path) -> None:
    world = _world(tmp_path)
    for wheel in Path(world["wheelhouse"]).iterdir():
        wheel.unlink()
    result = _run(world)
    assert result.ok is False
    assert result.failure_owner == "HARNESS"
    assert result.reason_codes == ["UPSTREAM_WHEEL_MISSING"]
    assert result.product_stop_code == "STOP_HARNESS_OR_EXTERNAL"


def test_missing_upstream_lock_stops_before_install(tmp_path: Path) -> None:
    world = _world(tmp_path)
    lock = (
        Path(world["project"]) / "controls" / str(world["task_id"])
        / "reference" / "requirements.lock.txt"
    )
    lock.unlink()
    result = _run(world)
    assert result.ok is False
    assert result.failure_owner == "HARNESS"
    assert result.reason_codes == ["UPSTREAM_PIN_MISSING"]
    assert all(check.name != "offline_install" for check in result.checks)


def test_upstream_import_failure_is_external_not_agent_repair(tmp_path: Path) -> None:
    world = _world(tmp_path)
    contract_path = Path(world["tool_contract"])
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    contract["source_repo"]["import_module"] = "not_a_real_demo_module"
    contract_path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    result = _run(world)
    assert result.ok is False
    assert result.failure_owner == "UPSTREAM"
    assert result.reason_codes == ["UPSTREAM_IMPORT_FAILED"]
    assert result.recommended_action == "RETRY_INFRASTRUCTURE"


def test_reference_failure_stops_as_contract_fault(tmp_path: Path) -> None:
    world = _world(tmp_path)
    reference = (
        Path(world["project"]) / "controls" / str(world["task_id"])
        / "reference" / "impl.py"
    )
    reference.write_text(
        "from pathlib import Path\n"
        "def extract(input_path: Path) -> str:\n"
        "    raise RuntimeError('broken reference')\n",
        encoding="utf-8",
    )
    result = _run(world)
    assert result.ok is False
    assert result.failure_owner == "CONTRACT"
    assert result.reason_codes == ["REFERENCE_EXECUTION_FAILED"]


def test_reference_golden_mismatch_stops_as_contract_fault(tmp_path: Path) -> None:
    world = _world(tmp_path)
    Path(world["expected"]).write_text('{"value":"WRONG"}\n', encoding="utf-8")
    result = _run(world)
    assert result.ok is False
    assert result.failure_owner == "CONTRACT"
    assert result.reason_codes == ["REFERENCE_GOLDEN_MISMATCH"]
    assert result.recommended_action == "ASK_USER"
