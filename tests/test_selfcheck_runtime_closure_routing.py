"""Core 闭包步骤发现的合同-生产者分歧也要能修(incident-selfcheck-runtime-closure-code-unrouted-*)。

不变量:
  I1 `WORKSPACE_RUNTIME_APPLICATION_MISSING`(合同声明了 runtime_python_entrypoint,
     reference 却没写出它)必须有修复路由:先修生产者(它没履行自己的合同),
     同码再犯则修合同表示(runnable/entrypoint);
  I2 环境性的 WORKSPACE_RUNTIME_* 码(wheelhouse/锁/wheel 集不安全)仍不路由——
     那些不是模型能修的;
  I3 候选生成把这一失败投影时必须带公开诊断:缺的是哪一个 entrypoint 路径。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.adoption.delivery.portable_workspace_runtime import WorkspaceRuntimeError
from repoproof.adoption.intake.draft_selfcheck import repair_target_for
from repoproof.execution.workspace_bundle import WorkspaceBundleError
from repoproof.ui.services import product_jobs


def test_missing_entrypoint_routes_to_reference_then_contract() -> None:
    assert repair_target_for("WORKSPACE_RUNTIME_APPLICATION_MISSING", round_index=1) == "reference"
    assert repair_target_for("WORKSPACE_RUNTIME_APPLICATION_MISSING", round_index=2) == "contract"


def test_environment_runtime_codes_stay_unrouted() -> None:
    for code in (
        "WORKSPACE_RUNTIME_WHEELHOUSE_UNSAFE",
        "WORKSPACE_RUNTIME_LOCK_UNSAFE",
        "WORKSPACE_RUNTIME_WHEEL_SET_INVALID",
    ):
        assert repair_target_for(code, round_index=1) is None


def test_runtime_closure_failure_carries_the_entrypoint_in_public_diagnostics(tmp_path: Path) -> None:
    error = WorkspaceRuntimeError("WORKSPACE_RUNTIME_APPLICATION_MISSING", "app.py")
    projected = product_jobs._runtime_closure_bundle_error(error)
    assert isinstance(projected, WorkspaceBundleError)
    assert projected.code == "WORKSPACE_RUNTIME_APPLICATION_MISSING"
    diagnostics = list(projected.diagnostics)
    assert diagnostics[0] == "WORKSPACE_RUNTIME_APPLICATION_MISSING"
    assert any("app.py" in row and "runtime_python_entrypoint" in row for row in diagnostics[1:])
