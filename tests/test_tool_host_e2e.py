"""LOCAL-TOOL × host_guided 全链 fake E2E(M1「先 fake 钉死机制」)。

合成 mini 上游(minilib,git 钉版)+ 装配 + bridge 物化 + fake 四发:
  positive(=reference,真 import minilib) → PASS_ADAPTED + clean replay;
  control:negative_reimpl(硬编码零 import,oracle 全绿) → FAIL,
      failure_types 含 UPSTREAM_CAPABILITY_REIMPLEMENTED —— [D4] 弱档
      provenance 执法的全链自证(没有这条,假成功直通);
  control:negative_hardcode(只背公开样例) → FAIL(held-out 杀);
  noop(骨架初始态) → FAIL(诚实失败,零假绿)。

环境边界(如实):setup 用内联 shim(.venv/bin/python → 仓 venv +
PYTHONPATH),零网零 pip —— 本文件钉的是**链条机制**(装配→prompt→
fake 轮→冻结→四验证→provenance→replay→gate),pip 依赖归因路径属
真跑段,不在此测。保护目录指纹在本测收窄为空:并行会话写本仓会打脏
秒级指纹窗口(smoke 实测),而指纹面自有专测。
"""

from __future__ import annotations

import json
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

from repoproof.adoption.assembly.tool_assembler import assemble_tool_task
from repoproof.domain.models import ToolInterface, ToolInterfaceIO, ToolSpec
from repoproof.runner.tool_host_bridge import materialize_tool_task

_REPO_PY = sys.executable
_REPO_SITE = sysconfig.get_paths()["purelib"]

_MINILIB = '''MAGIC = "MINI\\n"


class FormatError(ValueError):
    pass


def rows_to_markdown(text):
    if not text.startswith(MAGIC):
        raise FormatError("missing MINI header")
    rows = [l for l in text[len(MAGIC):].splitlines() if l.strip()]
    return "\\n".join(f"| {r} |" for r in rows)
'''

_REFERENCE = '''"""reference:真调 pinned minilib 的参考实现(出题人提供,绝不交付)。"""
from pathlib import Path

import minilib


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        text = input_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:      # malformed=伪二进制:解码错=用户错误
        raise UserInputError(str(e)) from e
    try:
        return minilib.rows_to_markdown(text)
    except minilib.FormatError as e:
        raise UserInputError(str(e)) from e
'''

_SPEC = ToolSpec(name="mini-tool", summary="MINI 文本转 Markdown 行表",
                 interface=ToolInterface(
                     usage="mini-tool <input.txt> [--out FILE]",
                     input=ToolInterfaceIO(kind="file", format="TXT"),
                     output=ToolInterfaceIO(kind="stdout", format="markdown-table"),
                     exit_codes={"0": "success", "1": "user_error",
                                 "2": "internal_error"}))

_EXAMPLES = [
    {"input": "--help", "expected": "contains:usage"},
    {"input_file": "inputs/a.txt", "expected": "contains:| alpha |"},
    {"input_file": "inputs/b.txt", "expected_file": "expected/b.md"},
    {"input_file": "inputs/c.txt", "expected": "contains:| gamma |"},
]


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(cwd), *args],
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("tool_e2e")
    project = tmp / "proj"

    # mini 上游:git 钉版(HostGuidedRunner 用 rev-parse HEAD 严校验)
    up = project / "upstream-cache" / "up_tmp"
    (up / "minilib").mkdir(parents=True)
    (up / "minilib" / "__init__.py").write_text(_MINILIB, encoding="utf-8")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t",
                  "commit", "-qm", "pin"]):
        _git(up, *args)
    head = _git(up, "rev-parse", "HEAD")
    up_pinned = up.parent / f"upstream-{head[:12]}"
    up.rename(up_pinned)

    src = tmp / "examples"
    (src / "inputs").mkdir(parents=True)
    (src / "expected").mkdir()
    (src / "inputs" / "a.txt").write_text("MINI\nalpha", encoding="utf-8")
    (src / "inputs" / "b.txt").write_text("MINI\nbeta", encoding="utf-8")
    (src / "inputs" / "c.txt").write_text("MINI\ngamma", encoding="utf-8")
    (src / "expected" / "b.md").write_text("| beta |\n", encoding="utf-8")

    info = assemble_tool_task(
        project, goal="把 minilib 的行表能力包装为本地 CLI 工具",
        repo_url="https://example.invalid/minilib", resolved_commit=head,
        distribution="minilib", import_module="minilib", license_id="MIT",
        tool=_SPEC, examples=_EXAMPLES, example_src_dir=src,
        reference_impl=_REFERENCE, input_ext=".txt")

    # setup = 内联 shim:.venv/bin/python → 仓 venv + PYTHONPATH(零网零 pip)
    snippet = (
        "import os, pathlib\n"
        "host = pathlib.Path(os.getcwd())\n"
        "b = host/'.venv'/'bin'; b.mkdir(parents=True, exist_ok=True)\n"
        "p = b/'python'\n"
        "p.write_text('#!/bin/bash\\n'\n"
        # 前置保留继承的 PYTHONPATH:M2-c 的 import-hook 目录由 harness 经
        # env 注入,shim 覆盖它 = 取证件在 E2E 全盲(实测预判的坑)
        # ${{PYTHONPATH:-}} 是 bash 运行时展开(hook env 在 oracle exec 才注入,
        # setup 时刻用 python 展开会写死成空 —— 实测断点)
        f"    'export PYTHONPATH=\"'+str(host/'src')+':{up_pinned}:{_REPO_SITE}:'+'${{PYTHONPATH:-}}\"\\n'\n"
        f"    'exec \"{_REPO_PY}\" \"$@\"\\n')\n"
        "p.chmod(0o755)\n"
        "print('fake venv ready')\n")
    setup = [[_REPO_PY, "-c", snippet]]

    contract = materialize_tool_task(
        project, project / "contracts" / f"{info['task_id']}.yaml",
        out_root=project / "tool_tasks", host_copy_root=tmp / "bench",
        setup_commands=setup)
    return {"project": project, "contract": contract,
            "task_id": info["task_id"],
            "wheelhouse": tmp / "bench" / info["task_id"] / "wheelhouse"}


def _run_fake(world, mode: str, monkeypatch, run_index: int) -> dict:
    from repoproof.agents.fake_model import FakeModel
    from repoproof.runner import host_guided
    from repoproof.harness import host_guard

    # 并行会话写本仓会打脏秒级指纹窗口(smoke 实测);指纹面自有专测。
    monkeypatch.setattr(host_guard, "DEFAULT_PROTECTED", ())
    monkeypatch.delenv("REPOPROOF_PROTECTED_DIRS", raising=False)

    runner = host_guided.HostGuidedRunner(
        world["contract"], world["project"], wheelhouse=world["wheelhouse"])
    runner._fake_mode = mode
    script = host_guided._fake_script(mode, runner)

    def factory(_totals):
        return FakeModel(script=script)

    return runner.run(None, None, model_factory=factory,
                      run_order=1, run_index=run_index,
                      batch="EXPLORATORY_UNPREREGISTERED")


@pytest.mark.slow
def test_fake_positive_reference_reaches_verified_tool_ready(world, monkeypatch, tmp_path):
    report = _run_fake(world, "positive", monkeypatch, 1)
    assert report["verdict"] == "PASS_ADAPTED", report.get("gate_reasons", report)
    assert report["verdict_public"] == "VERIFIED_TOOL_READY"
    # 决策表:终局 PASS 只能由 clean_adoption replay 撑起(gate 钉死);
    # report 里各验证器是 detail 字符串,结构化件在 run 目录 verification/。
    assert report["replay"], "PASS 必须带 replay detail"

    # ---- 导出链(tool_export):骨架+patch 确定性重建 + evidence 内嵌 ----
    from repoproof.runner.tool_export import export_verified_tool

    dest = export_verified_tool(
        world["project"] / "runs" / report["run_id"],
        host_contract_path=world["contract"],
        tool_contract_path=world["project"] / "contracts" / f"{world['task_id']}.yaml",
        dest_root=tmp_path / "tools")
    impl = (dest / "src" / "mini_tool" / "impl.py").read_text(encoding="utf-8")
    assert "import minilib" in impl, "导出树必须是补丁后的实现"
    mf = json.loads((dest / "tool.json").read_text(encoding="utf-8"))
    assert mf["verification"]["verdict"] == "VERIFIED_TOOL_READY"
    assert mf["verification"]["replay_mode"] == "clean_adoption"
    for rel in ("evidence/report.json", "evidence/provenance.json",
                "evidence/adaptation.patch", "build.sh", "bin/mini-tool"):
        assert (dest / rel).is_file(), f"导出缺 {rel}"
    assert not (dest / "public_tests").exists(), "公开测试属任务包,不进交付物"


@pytest.mark.slow
def test_fake_reimpl_green_oracle_but_dies_at_provenance(world, monkeypatch):
    """[D4] 弱档执法的全链自证:oracle 全绿也不放行零 import 交付。"""
    report = _run_fake(world, "control:negative_reimpl", monkeypatch, 2)
    assert report["verdict"] == "FAIL"
    assert "[tool-provenance]" in report["capability"]
    assert "failed_checks=0" in report["capability"], \
        "oracle 本身必须全绿(死因只在采纳层)"
    # failure_types 只进台账(report 无此键)——从事实源断言
    last = json.loads((world["project"] / "benchmarks" / "v2" / "runs.jsonl")
                      .read_text(encoding="utf-8").splitlines()[-1])
    assert last["run_id"] == report["run_id"]
    assert "UPSTREAM_CAPABILITY_REIMPLEMENTED" in last["failure_types"]


@pytest.mark.slow
def test_fake_hardcode_dies_on_held_out(world, monkeypatch):
    report = _run_fake(world, "control:negative_hardcode", monkeypatch, 3)
    assert report["verdict"] == "FAIL"
    cap = report["capability"]
    assert "test_held_example" in cap, f"held-out 必须在死因里:{cap}"
    assert "test_example_2" not in cap and "test_example_3" not in cap, \
        f"公开样例不该红:{cap}"


@pytest.mark.slow
def test_fake_noop_fails_honestly(world, monkeypatch, tmp_path):
    report = _run_fake(world, "noop", monkeypatch, 4)
    assert report["verdict"] == "FAIL"

    # FAIL 的证据留在 run 目录 —— 导出层必须拒绝(假成功的最后一道门)
    from repoproof.runner.tool_export import ToolExportError, export_verified_tool

    with pytest.raises(ToolExportError):
        export_verified_tool(
            world["project"] / "runs" / report["run_id"],
            host_contract_path=world["contract"],
            tool_contract_path=(world["project"] / "contracts"
                                / f"{world['task_id']}.yaml"),
            dest_root=tmp_path / "tools")


@pytest.mark.slow
def test_ledger_rows_written_with_tool_host_id(world):
    rows = [json.loads(l) for l in
            (world["project"] / "benchmarks" / "v2" / "runs.jsonl")
            .read_text(encoding="utf-8").splitlines()]
    assert len(rows) >= 4
    assert {r["host_id"] for r in rows} == {"local-tool/mini-tool"}
    assert all(r["model"].startswith("fake-scripted:") for r in rows)
