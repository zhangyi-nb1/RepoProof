from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from repoproof.runner import tool_pipeline
from repoproof.runner.tool_pipeline import (
    PipelineError,
    _record_workspace_repair_incidents,
    _stage_workspace_wheelhouse,
)


def _documents(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    host_copy = tmp_path / "host"
    (host_copy / "vendor/wheels").mkdir(parents=True)
    (host_copy / "vendor/wheels/.gitkeep").touch()
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "demo-1.0-py3-none-any.whl").write_bytes(b"wheel")
    tool_contract = tmp_path / "tool.yaml"
    tool_contract.write_text(
        yaml.safe_dump(
            {
                "tool": {
                    "schema_version": 4,
                    "delivery_profile_id": "workspace_bundle_v1",
                }
            }
        ),
        encoding="utf-8",
    )
    host_contract = tmp_path / "host.yaml"
    host_contract.write_text(
        yaml.safe_dump({"host": {"copy_path": str(host_copy)}}),
        encoding="utf-8",
    )
    return host_copy, wheelhouse, tool_contract, host_contract


def test_workspace_pipeline_stages_only_frozen_wheels_into_delivery(
    tmp_path: Path,
) -> None:
    host_copy, wheelhouse, tool_contract, host_contract = _documents(tmp_path)

    result = _stage_workspace_wheelhouse(
        host_contract_path=host_contract,
        tool_contract_path=tool_contract,
        wheelhouse=wheelhouse,
    )

    assert result is not None
    assert result["wheel_count"] == 1
    assert not (host_copy / "vendor/wheels/.gitkeep").exists()
    assert (host_copy / "vendor/wheels/demo-1.0-py3-none-any.whl").read_bytes() == b"wheel"


def test_workspace_pipeline_rejects_sdist_in_portable_wheelhouse(
    tmp_path: Path,
) -> None:
    _host_copy, wheelhouse, tool_contract, host_contract = _documents(tmp_path)
    (wheelhouse / "dependency-1.0.tar.gz").write_bytes(b"sdist")

    with pytest.raises(PipelineError, match="non-wheel"):
        _stage_workspace_wheelhouse(
            host_contract_path=host_contract,
            tool_contract_path=tool_contract,
            wheelhouse=wheelhouse,
        )


def test_workspace_pipeline_appends_public_repair_round_incidents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = "tool-study-workspace-v1"
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / f"{task_id}.yaml").write_text(
        yaml.safe_dump(
            {
                "tool": {
                    "schema_version": 4,
                    "delivery_profile_id": "workspace_bundle_v1",
                }
            }
        ),
        encoding="utf-8",
    )
    package = tmp_path / "src/repoproof"
    package.mkdir(parents=True)
    (package / "generic.py").write_text("VALUE = 1\n", encoding="utf-8")
    round_root = tmp_path / "runs/run-one/repair/round-1"
    round_root.mkdir(parents=True)
    (round_root / "record.json").write_text(
        json.dumps(
            {
                "round_index": 1,
                "changed_files": ["src/tool/impl.py"],
                "diff_lines": 12,
                "public_failed": 1,
                "regression_failed": 0,
                "policy_violations": 0,
                "failure_packets": [{"type": "PUBLIC_TEST"}],
                "failure_owner": "AGENT_ADAPTER",
                "public_failure_fingerprint": "a" * 16,
                "reason_codes": ["PUBLIC_CONTRACT_FAILED"],
                "adapter_diff_present": True,
                "recommended_action": "REPAIR",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        tool_pipeline.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="b" * 40 + "\n"),
    )

    written = _record_workspace_repair_incidents(
        project_root=tmp_path,
        task_id=task_id,
        run_id="run-one",
    )

    assert len(written) == 1
    incident = json.loads(Path(written[0]).read_text(encoding="utf-8"))
    assert incident["stage"] == "AGENT_ADAPTER"
    assert incident["repair_eligible"] is True
    assert incident["public_failed_nodes"] == ["PUBLIC_TEST"]
    assert incident["artifact_tree_diff"]["changed_file_count"] == 1


def test_agent_owned_terminal_incident_can_stop_without_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = "tool-study-workspace-v1"
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / f"{task_id}.yaml").write_text(
        yaml.safe_dump(
            {
                "tool": {
                    "schema_version": 4,
                    "delivery_profile_id": "workspace_bundle_v1",
                }
            }
        ),
        encoding="utf-8",
    )
    package = tmp_path / "src/repoproof"
    package.mkdir(parents=True)
    (package / "generic.py").write_text("VALUE = 1\n", encoding="utf-8")
    round_root = tmp_path / "runs/run-two/repair/round-2"
    round_root.mkdir(parents=True)
    (round_root / "record.json").write_text(
        json.dumps(
            {
                "round_index": 2,
                "changed_files": [],
                "public_failed": 1,
                "failure_packets": [{"type": "PUBLIC_TEST"}],
                "failure_owner": "AGENT_ADAPTER",
                "adapter_diff_present": False,
                "recommended_action": "STOP",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        tool_pipeline.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="b" * 40 + "\n"),
    )

    written = _record_workspace_repair_incidents(
        project_root=tmp_path,
        task_id=task_id,
        run_id="run-two",
    )
    incident = json.loads(Path(written[0]).read_text(encoding="utf-8"))
    assert incident["owner"] == "AGENT_ADAPTER"
    assert incident["repair_eligible"] is False
    assert incident["disposition"] == "STOP_NEEDS_HUMAN"
    assert "NO_ADAPTER_DIFF" in incident["reason_codes"]
