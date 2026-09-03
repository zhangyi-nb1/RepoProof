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


_PRODUCER = """import sys
from pathlib import Path

out = Path(sys.argv[1])
out.mkdir(parents=True)
(out / "app.py").write_text("VALUE = 1\\n", encoding="utf-8")
(out / "README.md").write_text("# report\\n", encoding="utf-8")
sys.path.insert(0, str(out))
import app  # the producer imports the file it just delivered

(out / "report.txt").write_text(str(app.VALUE), encoding="utf-8")
"""


def _contract():
    from repoproof.domain.models import WorkspaceArtifactContractV1

    return WorkspaceArtifactContractV1.model_validate(
        {
            "schema_version": 1,
            "rules": [
                {
                    "path_pattern": "app.py",
                    "role": "application",
                    "media_type": "text/x-python",
                    "validation_profile": "python_compile_v1",
                },
                {
                    "path_pattern": "README.md",
                    "role": "docs",
                    "media_type": "text/markdown",
                    "validation_profile": "text_utf8_v1",
                },
                {
                    "path_pattern": "report.txt",
                    "role": "report",
                    "media_type": "text/plain",
                    "validation_profile": "text_utf8_v1",
                },
            ],
            "allow_extra_files": False,
            "entrypoints": [],
            "runnable": False,
            "smoke_command": [],
            "smoke_timeout_seconds": 10,
            "require_offline_wheelhouse": False,
            "limits": {
                "max_files": 16,
                "max_total_bytes": 100000,
                "max_file_bytes": 50000,
                "max_depth": 4,
                "max_path_bytes": 160,
            },
        }
    )


def test_behaviour_a_self_importing_producer_is_rejected_under_user_semantics(tmp_path: Path) -> None:
    """The real behaviour, not a source grep: the same producer passes validation
    under the hidden flag and is rejected the way a user's run would be."""

    import subprocess
    import sys

    from repoproof.execution.workspace_bundle import validate_workspace

    script = tmp_path / "producer.py"
    script.write_text(_PRODUCER, encoding="utf-8")
    contract = _contract()
    outcomes = {}
    for label, write_bytecode in (("hidden", False), ("user_like", True)):
        home = tmp_path / f"home-{label}"
        home.mkdir()
        target = tmp_path / f"out-{label}"
        process = subprocess.run(
            [sys.executable, str(script), str(target)],
            env=sanitised_subprocess_env(home, [], write_bytecode=write_bytecode),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert process.returncode == 0, process.stderr
        result = validate_workspace(target, contract)
        outcomes[label] = result

    assert outcomes["hidden"].ok is True, outcomes["hidden"].details
    assert outcomes["user_like"].ok is False
    assert "WORKSPACE_EXTRA_FILE_FORBIDDEN" in outcomes["user_like"].reason_codes
    assert any("__pycache__" in row for row in outcomes["user_like"].details)


def test_both_statements_teach_the_residue_rule() -> None:
    """闸门要杀的先教:两个任务版本的 Agent 都选了"把生成器写进交付目录再 import"这条捷径,
    而题面从没说过它会在交付里留下字节码。"""

    from repoproof.adoption.intake import tool_drafter
    from repoproof.runner import host_guided

    for text in (
        inspect.getsource(host_guided._build_workspace_tool_prompt),
        tool_drafter._WORKSPACE_REFERENCE_REPAIR_SYSTEM,
    ):
        lowered = text.lower()
        assert "__pycache__" in lowered
        assert "output_dir" in lowered
