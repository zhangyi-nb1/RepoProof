"""自检必须用 preflight 同一把 smoke 尺子先跑一遍(incident-selfcheck-omits-runtime-smoke-*)。

不变量:
  I1 runnable 合同的候选生成在首个候选的密封工作区上执行 `run_workspace_smoke`(preflight
     用的同一函数),失败投影为 `WORKSPACE_REFERENCE_SMOKE_FAILED`,诊断带 smoke 码、
     退出码与 stderr 摘录;非 runnable 合同不跑;
  I2 smoke 证据边界不变(证据里只有哈希),摘录经显式 sink 交给调用方;
  I3 该码路由为先修生产者、同码再犯修合同(smoke_command 属合同表示)。
"""

from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path

import yaml

from repoproof.adoption.intake.draft_selfcheck import repair_target_for
from repoproof.domain.models import WorkspaceArtifactContractV1
from repoproof.execution.workspace_bundle import run_workspace_smoke
from repoproof.ui.services import product_jobs

_spec = importlib.util.spec_from_file_location(
    "_probe_fixtures", Path(__file__).with_name("test_reference_reproducibility_probe.py")
)
_probe = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_probe)


def _make_runnable(draft: Path) -> None:
    doc = yaml.safe_load((draft / "draft.yaml").read_text(encoding="utf-8"))
    contract = doc["tool"]["workspace_contract"]
    contract["runnable"] = True
    contract["entrypoints"] = ["run.sh"]
    contract["smoke_command"] = ["./run.sh"]
    contract["rules"] = list(contract.get("rules") or []) + [
        {
            "path_pattern": "run.sh",
            "role": "launcher",
            "media_type": "text/x-shellscript",
            "validation_profile": "shell_v1",
            "executable": True,
        }
    ]
    (draft / "draft.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")


class _FailingSmoke:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, expected_dir: Path, contract):
        self.calls += 1
        evidence = type(
            "E",
            (),
            {"passed": False, "reason_codes": ("WORKSPACE_SMOKE_NONZERO_EXIT",), "exit_code": 1},
        )()
        return evidence, "FileNotFoundError: [Errno 2] No such file or directory: 'spec.json'"


def test_runnable_contract_smoke_failure_is_projected_with_evidence(tmp_path: Path, monkeypatch) -> None:
    draft, _runs = _probe._prepare(tmp_path, monkeypatch, drift=False)
    _make_runnable(draft)
    smoke = _FailingSmoke()
    monkeypatch.setattr(product_jobs, "_smoke_reference_workspace", smoke)
    result = product_jobs.propose_workspace_fixture_candidates(draft, n=1, offline=True)
    assert result["ok"] is False
    assert result["reason_codes"] == ["WORKSPACE_REFERENCE_SMOKE_FAILED"]
    assert result["failure_owner"] == "CONTRACT"
    diagnostics = " | ".join(result["diagnostics"])
    assert "WORKSPACE_SMOKE_NONZERO_EXIT" in diagnostics
    assert "exit_code=1" in diagnostics and "spec.json" in diagnostics
    assert smoke.calls == 1


def test_non_runnable_contract_never_runs_smoke(tmp_path: Path, monkeypatch) -> None:
    draft, _runs = _probe._prepare(tmp_path, monkeypatch, drift=False)
    smoke = _FailingSmoke()
    monkeypatch.setattr(product_jobs, "_smoke_reference_workspace", smoke)
    result = product_jobs.propose_workspace_fixture_candidates(draft, n=1, offline=True)
    assert result.get("reason_codes") != ["WORKSPACE_REFERENCE_SMOKE_FAILED"]
    assert smoke.calls == 0


def test_smoke_failure_routes_to_reference_then_contract() -> None:
    assert repair_target_for("WORKSPACE_REFERENCE_SMOKE_FAILED", round_index=1) == "reference"
    assert repair_target_for("WORKSPACE_REFERENCE_SMOKE_FAILED", round_index=2) == "contract"


def test_smoke_runner_hands_a_bounded_stderr_excerpt_to_the_sink_only(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "README.md").write_text("# x\n", encoding="utf-8")
    launcher = root / "run.sh"
    launcher.write_text("#!/bin/sh\necho 'boom: spec.json missing' >&2\nexit 3\n", encoding="utf-8")
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    contract = WorkspaceArtifactContractV1.model_validate(
        {
            "schema_version": 1,
            "rules": [
                {
                    "path_pattern": "README.md",
                    "role": "docs",
                    "media_type": "text/markdown",
                    "validation_profile": "text_utf8_v1",
                },
                {
                    "path_pattern": "run.sh",
                    "role": "launcher",
                    "media_type": "text/x-shellscript",
                    "validation_profile": "shell_v1",
                    "executable": True,
                },
            ],
            "allow_extra_files": False,
            "entrypoints": ["run.sh"],
            "runnable": True,
            "smoke_command": ["./run.sh"],
            "smoke_timeout_seconds": 10,
            "require_offline_wheelhouse": False,
            "limits": {
                "max_files": 10,
                "max_total_bytes": 4096,
                "max_file_bytes": 2048,
                "max_depth": 3,
                "max_path_bytes": 120,
            },
        }
    )
    captured: list[str] = []
    evidence = run_workspace_smoke(root, contract, isolation_required=False, stderr_sink=captured.append)
    assert evidence.passed is False and evidence.exit_code == 3
    assert "WORKSPACE_SMOKE_NONZERO_EXIT" in evidence.reason_codes
    assert captured and "spec.json missing" in captured[0]
    assert "boom" not in evidence.model_dump_json()
    assert os.environ.get("REPOPROOF_NEVER_SET") is None
