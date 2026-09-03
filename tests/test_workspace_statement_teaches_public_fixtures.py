"""工作区题面必须先教"验收比什么"(incident-statement-does-not-teach-golden-comparison-*)。

现象:两个独立任务版本上,Agent 把 20/20 次模型调用全部花在反推
(a) 黄金树是逐字节比对、连应用文件和 README 也在内,(b) run.sh 等运行时文件由 Harness 封存
不用写,(c) 哪些期望文件与输入无关、在所有公开样例里逐字节相同——最后一次写入都没做成。
这些事实全部可以从公开样例算出来,题面却一个字没说。

不变量:
  I1 `public_fixture_digest(task_dir)` 只读公开样例,列出:样例数与路径布局、Harness 封存
     的运行时路径(不写)、跨样例逐字节相同的文件(可逐字节复制)、随输入变化的文件;
  I2 workspace-tool-v1 题面带上这段,并说明黄金比对是逐字节、含应用文件与 README;
  I3 摘要不含任何文件内容(不泄字节),只有路径与分类;非 workspace 档口不受影响。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.runner.host_guided import HostContract, build_host_prompt, public_fixture_digest


def _task_dir(tmp_path: Path) -> Path:
    task = tmp_path / "task"
    for name, body in (("alpha", "x=1\n"), ("beta", "x=2\n")):
        fx = task / "public_tests" / "fixtures" / name
        (fx / "input").mkdir(parents=True)
        (fx / "input" / "data.csv").write_text(f"k,v\n{name},{body}", encoding="utf-8")
        exp = fx / "expected"
        (exp / "output").mkdir(parents=True)
        (exp / "vendor" / "wheels").mkdir(parents=True)
        (exp / "app.py").write_text("print('same')\n", encoding="utf-8")
        (exp / "README.md").write_text("# same\n", encoding="utf-8")
        (exp / "output" / "report.txt").write_text(body, encoding="utf-8")
        (exp / "run.sh").write_text('#!/bin/sh\n"$RUNTIME/venv/bin/python" "$ROOT/app.py" "$@"\n', encoding="utf-8")
        (exp / "requirements.lock.txt").write_text("up==1\n", encoding="utf-8")
        (exp / "THIRD_PARTY_NOTICES.md").write_text("n\n", encoding="utf-8")
        (exp / "vendor" / "wheels" / "up-1-py3-none-any.whl").write_bytes(b"PK")
    return task


def _contract() -> HostContract:
    return HostContract.model_validate(
        {
            "task_id": "anon-workspace-task",
            "task_version": "v1",
            "kind": "local-tool",
            "host": {
                "repo": "anon/host",
                "commit": "c" * 40,
                "copy_path": "host",
                "regression_command": ["true"],
            },
            "capability": {
                "statement": "make a workspace",
                "requirements": [{"id": "workspace-examples", "text": "Generate the workspace."}],
            },
            "budgets": {
                "max_rounds": 1,
                "max_model_calls": 20,
                "max_commands": 100,
                "max_patch_files": 10,
                "max_patch_lines": 2000,
                "max_wall_time_minutes": 30,
                "max_input_tokens_total": 1000000,
                "max_output_tokens_total": 100000,
            },
            "acceptance": {
                "public_test_command": ["python", "-m", "pytest", "public_tests", "-q"],
                "hidden_oracle_command": ["python", "-m", "pytest", "oracle", "-q"],
            },
            "prompt_profile": "workspace-tool-v1",
        }
    )


def test_digest_classifies_public_expected_files_without_leaking_bytes(tmp_path: Path) -> None:
    digest = public_fixture_digest(_task_dir(tmp_path))
    assert "public_tests/fixtures/<name>/input" in digest and "2 public example" in digest
    constant_line = next(line for line in digest.splitlines() if "identical across" in line.lower())
    assert "app.py" in constant_line and "README.md" in constant_line
    assert "run.sh" not in constant_line  # sealed runtime paths are not the agent's to write
    varying_line = next(line for line in digest.splitlines() if "vary with the input" in line.lower())
    assert "output/report.txt" in varying_line
    sealed_line = next(line for line in digest.splitlines() if "sealed" in line.lower())
    assert "run.sh" in sealed_line and "vendor/wheels" in sealed_line
    app_line = next(line for line in digest.splitlines() if "application file" in line.lower())
    assert "app.py" in app_line and "read it first" in app_line.lower()  # the generator, not just a constant
    for leak in ("print('same')", "x=1", "x=2", "# same"):
        assert leak not in digest


def test_workspace_prompt_carries_the_digest_and_names_the_byte_comparison(tmp_path: Path) -> None:
    digest = public_fixture_digest(_task_dir(tmp_path))
    prompt = build_host_prompt(_contract(), wheel_note="package wheelhouse", public_fixture_digest=digest)
    assert digest.strip() in prompt
    lowered = prompt.lower()
    assert "byte-for-byte" in lowered or "byte for byte" in lowered
    assert "readme" in lowered and "application file" in lowered


def test_digest_is_empty_when_there_are_no_public_fixtures(tmp_path: Path) -> None:
    assert public_fixture_digest(tmp_path / "nothing") == ""
