"""Agent 自测输出要有一个 Harness 给定、随会话丢弃的去处(incident-no-sanctioned-scratch-location-*)。

现象:一例把自测输出整棵工作区(含 11 个 wheel)写进包内 `_scratch/`,能力 6/6 却因
"adaptation files 60 > max_patch_files 16" 判 FAIL;另一例把正确输出写进 /tmp,与受保护期望件
逐字节相同,触发 H9-a 残留闸门拦停之后的每一发。两次都因为:题面既没说包内留下的每个文件都
计入补丁预算,也没给任何自测输出的合法去处。

不变量:
  I1 会话环境提供 `REPOPROOF_SCRATCH_DIR`,位于会话根之内、包目录之外(随会话销毁,残留
     闸门显式跳过 `_sessions/`),目录已建好;
  I2 题面渲染出该绝对路径(`scratch_abs`),系统提示写明:自测输出放这里,包内留下的每个文件
     都计入补丁预算,不要写 /tmp;
  I3 workspace-tool-v1 题面同样点名该变量与"包内每个新文件都计数"。
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import StrictUndefined, Template
from test_workspace_statement_teaches_public_fixtures import _contract

from repoproof.agents.backend import SYSTEM_TEMPLATE
from repoproof.agents.repoproof_env import RepoProofEnvironment
from repoproof.execution.local_worktree_backend import LocalWorktreeBackend
from repoproof.runner.host_guided import build_host_prompt


def test_backend_env_names_a_scratch_dir_inside_the_session_outside_the_package(tmp_path: Path) -> None:
    backend = LocalWorktreeBackend(sessions_root=tmp_path / "sessions")
    session = backend.start(name_prefix="rp")
    root = backend.session_root(session)
    (root / "host").mkdir()
    env = backend.build_env(session)
    scratch = Path(env["REPOPROOF_SCRATCH_DIR"])
    assert scratch.is_dir()
    assert root in scratch.parents
    assert (root / "host") not in scratch.parents and scratch != root / "host"


def test_template_renders_the_scratch_path_and_teaches_the_budget(tmp_path: Path) -> None:
    backend = LocalWorktreeBackend(sessions_root=tmp_path / "sessions")
    session = backend.start(name_prefix="rp")
    env = RepoProofEnvironment(
        backend=backend, container=session, store=None, command_timeout_s=10, command_budget=10, default_cwd="host"
    )
    variables = env.get_template_vars()
    expected = backend.build_env(session)["REPOPROOF_SCRATCH_DIR"]
    assert variables["scratch_abs"] == expected
    rendered = Template(SYSTEM_TEMPLATE, undefined=StrictUndefined).render(**variables)
    assert expected in rendered
    lowered = rendered.lower()
    assert "scratch" in lowered and "patch budget" in lowered and "/tmp" in lowered


def test_workspace_prompt_names_the_scratch_variable_and_the_counting_rule() -> None:
    prompt = build_host_prompt(_contract(), wheel_note="package wheelhouse")
    assert "REPOPROOF_SCRATCH_DIR" in prompt
    lowered = prompt.lower()
    assert "every file you leave inside the package" in lowered or "every new file inside the package" in lowered
