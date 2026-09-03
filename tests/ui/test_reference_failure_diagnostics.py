"""reference 执行失败必须带公开定位(incident-reference-failure-diagnostics-opaque-*)。

不变量:reference 是模型自己的草稿,它的异常信息与 reference 源内的帧位置
不是答案键;自检/有界自修必须拿到 `异常类型: 消息 @ reference_impl.py:行 函数`
这一行公开诊断,而不是只有异常类型名——否则修复只能靠猜。
`diagnostics[0]` 保持为异常类型名(既有 UI 修复入口按此校验)。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from repoproof.domain.models import WorkspaceArtifactContractV1
from repoproof.execution import offline_sandbox
from repoproof.execution.workspace_bundle import WorkspaceBundleError
from repoproof.ui.services import product_jobs

_REFERENCE = (
    "from pathlib import Path\n"
    "\n"
    "def _row(record):\n"
    "    return record['summary']\n"
    "\n"
    "def build_workspace(input_path: Path, output_dir: Path) -> None:\n"
    "    output_dir.mkdir()\n"
    "    _row({'title': 'x'})\n"
)


def _run(tmp_path: Path, monkeypatch) -> WorkspaceBundleError:
    source = tmp_path / "reference_impl.py"
    source.write_text(_REFERENCE, encoding="utf-8")
    input_path = tmp_path / "input"
    input_path.mkdir()
    (input_path / "brief.txt").write_text("study\n", encoding="utf-8")
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    monkeypatch.setattr(offline_sandbox, "offline_sandbox_argv", lambda argv, _root: argv)
    with pytest.raises(WorkspaceBundleError) as caught:
        product_jobs._run_workspace_reference_candidate(
            reference_source=source,
            input_path=input_path,
            expected_dir=tmp_path / "expected",
            contract=WorkspaceArtifactContractV1(
                rules=(
                    {
                        "path_pattern": "README.md",
                        "role": "guide",
                        "media_type": "text/markdown",
                        "validation_profile": "text_utf8_v1",
                    },
                )
            ),
            python_exe=sys.executable,
            upstream_dir=upstream,
        )
    return caught.value


def test_reference_failure_carries_public_location_and_message(tmp_path: Path, monkeypatch) -> None:
    error = _run(tmp_path, monkeypatch)
    assert error.code == "WORKSPACE_REFERENCE_EXECUTION_FAILED"
    assert error.detail == "KeyError"
    diagnostics = list(error.diagnostics)
    assert diagnostics[0] == "KeyError"
    location = diagnostics[1]
    assert location.startswith("KeyError: 'summary' @ reference_impl.py:4 _row")
    assert "reference_impl.py:8 build_workspace" in location


def test_candidate_generation_result_exposes_both_diagnostics(tmp_path: Path, monkeypatch) -> None:
    error = _run(tmp_path, monkeypatch)
    projected = product_jobs._workspace_bundle_error_diagnostics(error)
    assert projected[0] == "KeyError"
    assert len(projected) == 2 and "@ reference_impl.py:" in projected[1]
