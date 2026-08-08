"""用户实测三连修的回归钉(2026-08-08 inflection 事故):

1. 上游打包损坏 → 空壳 wheel 必须在构建时被拦截(不是 agent 阶段炸探针);
2. 运行崩溃必须留下 report.json——运行绝不允许"隐身";
3. 失败后重装配同一 distribution 自动升版本号,不撞名不覆盖。
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from repoproof.domain.models import AdmissionError
from repoproof.runner.agent_run import write_crash_report
from repoproof.runner.baseline import _Runner


def _make_wheel(path: Path, names: list[str]) -> None:
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            z.writestr(n, "x")


def test_empty_wheel_rejected_with_actionable_reason(tmp_path: Path) -> None:
    wh = tmp_path
    _make_wheel(wh / "demo-0+rp.pinned.abc-py3-none-any.whl", [
        "demo-0+rp.pinned.abc.dist-info/METADATA",
        "demo-0+rp.pinned.abc.dist-info/RECORD",
    ])
    with pytest.raises(AdmissionError, match="空壳"):
        _Runner.assert_wheel_contains_code(wh, "demo")


def test_wheel_with_code_passes_and_missing_wheel_rejected(tmp_path: Path) -> None:
    _make_wheel(tmp_path / "demo-1.0-py3-none-any.whl", [
        "demo/__init__.py", "demo-1.0.dist-info/METADATA",
    ])
    _Runner.assert_wheel_contains_code(tmp_path, "demo")  # 不抛
    with pytest.raises(AdmissionError, match="找不到"):
        _Runner.assert_wheel_contains_code(tmp_path, "other-dist")


def test_crash_report_makes_run_visible_and_is_idempotent(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "adopt-demo-guided-v1-20260101-000000"
    run.mkdir(parents=True)
    out = write_crash_report(tmp_path, "adopt-demo-guided-v1", "guided-repair",
                             RuntimeError("env probe unparseable"))
    assert out and (run / "report.json").exists()
    rep = json.loads((run / "report.json").read_text(encoding="utf-8"))
    assert rep["final_verdict"] == "BLOCKED"
    assert rep["state"] == "CRASHED_INTERNAL"
    assert "env probe" in rep["error"]
    assert any("不是任务结论" in r for r in rep["gate_reasons"])
    # 幂等:已有报告的运行绝不被覆盖
    (run / "report.json").write_text('{"final_verdict": "PASS_ADAPTED"}', encoding="utf-8")
    assert write_crash_report(tmp_path, "adopt-demo-guided-v1", "guided-repair",
                              RuntimeError("again")) is None
    assert json.loads((run / "report.json").read_text())["final_verdict"] == "PASS_ADAPTED"


def test_reassembly_bumps_version_and_keeps_v1(tmp_path: Path) -> None:
    from repoproof.adoption.assembly.task_assembler import assemble_task

    kw = dict(
        goal="为我的项目引入演示能力,输入输出都是字符串",
        repo_url="https://github.com/example/demo",
        resolved_commit="a" * 40, distribution="demo", import_module="demo",
        license_id="MIT",
        examples=[{"input": "a", "expected": "1"}, {"input": "b", "expected": "2"},
                  {"input": "c", "expected": "3"}, {"input": "d", "expected": "4"}],
    )
    out1 = assemble_task(tmp_path, **kw)
    assert out1["task_id"] == "adopt-demo-guided-v1"
    v1_contract = (tmp_path / "contracts" / "adopt-demo-guided-v1.yaml").read_bytes()

    out2 = assemble_task(tmp_path, **kw)
    assert out2["task_id"] == "adopt-demo-guided-v2"  # 自动升版本,不撞名
    assert any("assembled_demo-v2" in f for f in out2["files"])  # 消费夹具也分版本
    assert (tmp_path / "contracts" / "adopt-demo-guided-v1.yaml").read_bytes() == v1_contract
