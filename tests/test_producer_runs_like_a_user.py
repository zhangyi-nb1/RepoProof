"""生产者要在**用户那样的解释器**下跑,验收不许比用户宽松(incident-acceptance-env-more-permissive-*)。

现象:一个已导出 READY 的工作区工具,在用户环境里每个输入都 exit 2 ——
`WORKSPACE_EXTRA_FILE: __pycache__/<app>.cpython-312.pyc`:生产者把应用文件写进交付目录后
又 import 了它,CPython 在交付目录里留下字节码。冻结件复跑的决定性对照:带
`PYTHONDONTWRITEBYTECODE=1` 5/5 通过,不带 5/5 失败——**闸门全程带着这个用户不会有的开关**,
于是这个必然复现的缺陷一路通过了自检、彩排、真发与净室复跑。

不变量:
  I1 `sanitised_subprocess_env` 默认仍禁字节码(受保护树上的 pytest 不许留 __pycache__),
     但显式 `write_bytecode=True` 时不设该变量 —— 生产者按用户语义跑;
  I2 候选生成执行参考实现时用 `write_bytecode=True`:把自己写进交付目录再 import 的生产者,
     在**冻结前**就被结构校验以 WORKSPACE_EXTRA_FILE_FORBIDDEN 拒掉;
  I3 装配器编译出的验收测试调用交付工具时清掉该开关(新冻结件生效),
     使验收与用户看到同一份产物;
  I4 交付之后才跑的 smoke 保持禁字节码 —— 那时再写 .pyc 会改掉已交付树的身份。
"""

from __future__ import annotations

import inspect
from pathlib import Path

from repoproof.adoption.assembly import workspace_tool_assembler
from repoproof.execution.offline_sandbox import sanitised_subprocess_env
from repoproof.ui.services import product_jobs


def test_sanitised_env_can_run_like_a_user(tmp_path: Path) -> None:
    default = sanitised_subprocess_env(tmp_path, [])
    assert default.get("PYTHONDONTWRITEBYTECODE") == "1"
    user_like = sanitised_subprocess_env(tmp_path, [], write_bytecode=True)
    assert "PYTHONDONTWRITEBYTECODE" not in user_like
    assert user_like["HOME"] == str(tmp_path)  # everything else unchanged


def test_reference_candidate_execution_runs_like_a_user() -> None:
    source = inspect.getsource(product_jobs._run_workspace_reference_candidate)
    assert "write_bytecode=True" in source


def test_smoke_after_delivery_still_forbids_bytecode() -> None:
    from repoproof.execution import workspace_bundle

    source = inspect.getsource(workspace_bundle.run_workspace_smoke)
    assert "write_bytecode=True" not in source


def test_frozen_acceptance_invokes_the_tool_like_a_user() -> None:
    prelude = workspace_tool_assembler._TEST_PRELUDE
    assert "PYTHONDONTWRITEBYTECODE" in prelude
    namespace: dict = {"__file__": "/tmp/x/public_tests/t.py"}
    exec(compile(prelude.replace('os.environ["REPOPROOF_TOOL_BIN"]', '"unused"'), "p", "exec"), namespace)  # noqa: S102
    env = namespace["_tool_env"]()
    assert env["PYTHONDONTWRITEBYTECODE"] == ""
