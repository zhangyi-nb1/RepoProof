"""Agent 题面必须描述**它真正所处的环境**(incident-agent-task-statement-*)。

不变量:
  I1 系统提示不得声称一个本次运行并不提供的执行环境(比如"Linux 容器");
  I2 必须给出 shell 实际启动的**绝对工作目录**,且与后端解析出的目录一致 ——
     不给,模型就只能靠猜/搜盘,而搜盘正是被策略拒的动作;
  I3 会咬人的规则要先教:全盘扫描被 `filesystem_root_sweep` 拒,题面必须先说;
  I4 题面按运行渲染:两个不同会话根渲染出不同的绝对路径,不能是硬编码常量。

这条不变量与模型无关:它只是让题面为真。谁按字面读题面,谁都不该因此吃亏。
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import StrictUndefined, Template

from repoproof.agents.backend import SYSTEM_TEMPLATE
from repoproof.agents.repoproof_env import RepoProofEnvironment


class _Backend:
    """Minimal stand-in for the execution backend: only session_root matters."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def session_root(self, session: str) -> Path:
        return self._root / session


def _env(tmp_path: Path, session: str = "anon-session") -> RepoProofEnvironment:
    return RepoProofEnvironment(
        backend=_Backend(tmp_path),
        container=session,
        store=None,
        command_timeout_s=10,
        command_budget=10,
        default_cwd="host",
    )


def _render(env: RepoProofEnvironment) -> str:
    return Template(SYSTEM_TEMPLATE, undefined=StrictUndefined).render(**env.get_template_vars())


def test_statement_does_not_claim_an_environment_the_run_does_not_provide(tmp_path: Path) -> None:
    rendered = _render(_env(tmp_path)).lower()
    assert "container" not in rendered
    assert "linux" not in rendered


def test_statement_gives_the_absolute_working_directory_the_shell_starts_in(tmp_path: Path) -> None:
    env = _env(tmp_path)
    expected = str((tmp_path / "anon-session" / "host").resolve())
    assert env.get_template_vars()["workdir_abs"] == expected
    assert expected in _render(env)


def test_statement_discloses_the_filesystem_sweep_rule_before_it_bites(tmp_path: Path) -> None:
    from repoproof.harness.policy import evaluate_agent_command

    denied = evaluate_agent_command("find / -maxdepth 6 -iname 'tool*'")
    assert denied.allowed is False and any("sweep" in reason for reason in denied.reasons)
    rendered = _render(_env(tmp_path)).lower()
    assert "filesystem" in rendered and ("denied" in rendered or "refuse" in rendered)


def test_statement_is_rendered_per_run_not_hardcoded(tmp_path: Path) -> None:
    one = _render(_env(tmp_path, "session-one"))
    two = _render(_env(tmp_path, "session-two"))
    assert one != two
    assert "session-one" in one and "session-two" in two
