"""M3 三件的钉死:注册表 / MCP 机械转换 / 单命令旅程编排。

- 注册表是索引不是事实源:漂移如实标注(MISSING/UNVERIFIED),scan
  补录不伪造导出时间;
- MCP server 由 manifest 机械生成:协议三段(initialize/tools/list/
  tools/call)真子进程驱动;未验证工具拒生成;
- pipeline:合成 minilib 世界零网走到彩排门(REHEARSAL_PASS_ONLY),
  编排不吞错 —— confirm 失败原样传导(ConfirmError)。
"""

from __future__ import annotations

import json
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest
import yaml

from repoproof.runner.tool_mcp import write_mcp_server
from repoproof.runner.tool_registry import list_tools, register_tool
from repoproof.runner.tool_release import ACTIVE, append_release_decision

_REPO_PY = sys.executable
_REPO_SITE = sysconfig.get_paths()["purelib"]


def _fake_tool(dest: Path, name: str, *, verified: bool = True) -> Path:
    d = dest / name
    (d / "bin").mkdir(parents=True)
    (d / "evidence").mkdir()
    (d / "bin" / name).write_text(
        "#!/bin/bash\necho \"| ok |\"\n", encoding="utf-8")
    (d / "bin" / name).chmod(0o755)
    (d / "tool.json").write_text(json.dumps({
        "manifest_version": 1, "name": name, "version": "1.0.0",
        "summary": "假工具(测试)",
        "source": {"url": "u", "resolved_commit": "c", "license": "MIT",
                   "distribution": "d"},
        "interface": {"usage": f"{name} <in>",
                      "input": {"kind": "file", "format": "TXT"},
                      "output": {"kind": "stdout", "format": "TXT"},
                      "exit_codes": {"0": "s", "1": "u", "2": "i"}},
        "verification": ({"verdict": "VERIFIED_TOOL_READY", "run_id": "r-1",
                          "contract_sha256": "abc"} if verified else None),
    }, ensure_ascii=False), encoding="utf-8")
    (d / "evidence" / "provenance.json").write_text(
        json.dumps(
            {
                "tool": name,
                "task_id": f"tool-{name}-v1",
                "run_id": "r-1",
                "tool_contract_sha256": "abc",
            }
        ),
        encoding="utf-8",
    )
    return d


# ------------------------------------------------------------------ 注册表

def test_registry_register_list_and_drift(tmp_path):
    d = _fake_tool(tmp_path, "alpha")
    entry = register_tool(tmp_path, d, run_id="r-1", exported_at="2026-08-23T00:00:00Z")
    assert entry["task_id"] == "tool-alpha-v1"
    rows = list_tools(tmp_path)
    assert rows[0]["name"] == "alpha" and rows[0]["status"] == "OK"

    # 漂移:工具目录被删 → MISSING(如实标注,不静默剔除)
    import shutil

    shutil.rmtree(d)
    rows = list_tools(tmp_path)
    assert rows[0]["status"] == "MISSING"


def test_registry_scan_backfills_without_forging_time(tmp_path):
    _fake_tool(tmp_path, "beta")
    _fake_tool(tmp_path, "gamma", verified=False)
    rows = {r["name"]: r for r in list_tools(tmp_path, scan=True)}
    assert rows["beta"]["exported_at"] is None
    assert rows["beta"]["provenance"] == "scan"
    assert rows["beta"]["status"] == "OK"
    assert rows["gamma"]["status"] == "UNVERIFIED"


# ------------------------------------------------------------------ MCP

def test_mcp_refuses_unverified_tool(tmp_path):
    d = _fake_tool(tmp_path, "nover", verified=False)
    with pytest.raises(RuntimeError):
        write_mcp_server(d)


def test_mcp_server_protocol_and_call(tmp_path):
    d = _fake_tool(tmp_path, "echoer")
    append_release_decision(
        tmp_path,
        tool="echoer",
        task_id="tool-echoer-v1",
        run_id="r-1",
        decision=ACTIVE,
        reason_code="FRESH_INPUT_PASS",
        reason="test fresh-input audit passed",
        evidence_sha256="0" * 64,
        decided_at="2026-08-23T00:00:00Z",
        actor="operator",
    )
    server = write_mcp_server(d)
    inp = tmp_path / "in.jsonl"
    probe = tmp_path / "probe.txt"
    probe.write_text("x", encoding="utf-8")
    inp.write_text(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'
        '{"jsonrpc":"2.0","id":3,"method":"tools/call",'
        f'"params":{{"arguments":{{"input_path":"{probe}"}}}}}}\n'
        '{"jsonrpc":"2.0","id":4,"method":"bogus/xyz"}\n', encoding="utf-8")
    r = subprocess.run([sys.executable, str(server)],
                       stdin=inp.open(), capture_output=True, text=True,
                       timeout=120)
    lines = [json.loads(x) for x in r.stdout.splitlines() if x.strip()]
    assert len(lines) == 4, r.stdout          # 通知不回;四个带 id 的都回
    by_id = {d2["id"]: d2 for d2 in lines}
    assert by_id[1]["result"]["serverInfo"]["name"] == "echoer"
    tool = by_id[2]["result"]["tools"][0]
    assert tool["name"] == "echoer" and tool["inputSchema"]["required"] == ["input_path"]
    assert by_id[3]["result"]["content"][0]["text"].strip() == "| ok |"
    assert by_id[3]["result"]["isError"] is False
    assert by_id[4]["error"]["code"] == -32601


# ---------------------------------------- bench 规则准入(tool-* 两项制)

def test_bench_tool_prefix_rule_admission(tmp_path):
    """tool-* 条目免登记,但内部两项制强制:私货照报 stray(#29 兜底)。"""
    from repoproof.harness.host_guard import bench_root_strays

    (tmp_path / "tool-x-v1" / "host").mkdir(parents=True)
    (tmp_path / "tool-x-v1" / "wheelhouse").mkdir()
    assert bench_root_strays(tmp_path) == []
    (tmp_path / "tool-x-v1" / "answers").mkdir()          # 私货
    (tmp_path / "rogue-dir").mkdir()                       # 非 tool 前缀
    assert bench_root_strays(tmp_path) == ["rogue-dir", "tool-x-v1/answers"]


# ------------------------------------------------ pipeline(零网,到彩排门)

_MINILIB = ('MAGIC = "MINI\\n"\n\n\nclass FormatError(ValueError):\n    pass\n\n\n'
            'def rows_to_markdown(text):\n'
            '    if not text.startswith(MAGIC):\n'
            '        raise FormatError("missing MINI header")\n'
            '    rows = [l for l in text[len(MAGIC):].splitlines() if l.strip()]\n'
            '    return "\\n".join(f"| {r} |" for r in rows)\n')

_REFERENCE = ('"""reference:真调 minilib。"""\nfrom pathlib import Path\n\n'
              'import minilib\n\n\nclass UserInputError(ValueError):\n    pass\n\n\n'
              'def extract(input_path: Path) -> str:\n'
              '    try:\n'
              '        text = input_path.read_text(encoding="utf-8")\n'
              '    except UnicodeDecodeError as e:\n'
              '        raise UserInputError(str(e)) from e\n'
              '    try:\n'
              '        return minilib.rows_to_markdown(text)\n'
              '    except minilib.FormatError as e:\n'
              '        raise UserInputError(str(e)) from e\n')


@pytest.mark.slow
def test_pipeline_runs_to_rehearsal_gate_offline(tmp_path, monkeypatch):
    from repoproof.adoption.intake.tool_confirm import (
        ConfirmError,
        confirm_tool_draft,
        write_draft_bundle,
    )
    from repoproof.adoption.intake.tool_intake import run_tool_intake
    from repoproof.harness import host_guard
    from repoproof.runner.tool_pipeline import tool_build

    monkeypatch.setattr(host_guard, "DEFAULT_PROTECTED", ())
    monkeypatch.delenv("REPOPROOF_PROTECTED_DIRS", raising=False)

    project = tmp_path / "proj"
    # 合成 minilib 上游(git)+ 直接落 pinned 位(ensure 走"已存在"分支,零网)
    up_src = tmp_path / "up"
    (up_src / "minilib").mkdir(parents=True)
    (up_src / "minilib" / "__init__.py").write_text(_MINILIB, encoding="utf-8")
    (up_src / "pyproject.toml").write_text(
        '[project]\nname = "minilib"\nversion = "0.1.0"\n'
        'requires-python = ">=3.10"\ndependencies = []\n'
        '[build-system]\nrequires = ["setuptools"]\n'
        'build-backend = "setuptools.build_meta"\n', encoding="utf-8")
    (up_src / "LICENSE").write_text("MIT License", encoding="utf-8")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t",
                  "commit", "-qm", "pin"]):
        subprocess.run(["git", "-C", str(up_src), *args], check=True,
                       capture_output=True)
    head = subprocess.run(["git", "-C", str(up_src), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    pinned = project / "upstream-cache" / f"upstream-{head[:12]}"
    pinned.parent.mkdir(parents=True)
    import shutil

    shutil.copytree(up_src, pinned)

    # intake → draft 束 → 程序化人补(minilib 语义)
    rep = run_tool_intake("file://minilib", "MINI 文本转 Markdown",
                          cache_root=tmp_path / "cache", local_path=pinned)
    dest = write_draft_bundle(rep, tmp_path / "draft")
    doc = yaml.safe_load((dest / "draft.yaml").read_text(encoding="utf-8"))
    doc["source_repo"]["url"] = "file://minilib"
    doc["source_repo"]["resolved_commit"] = head
    doc["tool"]["summary"] = "MINI→MD"
    doc["tool"]["interface"]["input"]["format"] = "TXT"
    doc["tool"]["interface"]["output"]["format"] = "markdown-table"
    doc["tool"]["interface"]["output"]["contract"] = {
        "media_type": "text/markdown", "root_type": "text", "required": {}}
    doc["capability"]["statement"] = "MINI 文本转 Markdown 行表;坏输入 UserInputError。"
    doc["capability"]["output_schema"] = "MdRows"
    (dest / "draft.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    for n, txt in (("a", "MINI\nalpha"), ("b", "MINI\nbeta"), ("c", "MINI\ngamma")):
        (dest / "examples" / f"{n}.txt").write_text(txt, encoding="utf-8")
    (dest / "examples.yaml").write_text(yaml.safe_dump({"examples": [
        {"input": "--help", "expected": "contains:usage"},
        {"input_file": "a.txt", "expected": "contains:| alpha |"},
        {"input_file": "b.txt", "expected": "contains:| beta |"},
        {"input_file": "c.txt", "expected": "contains:| gamma |"},
    ]}, allow_unicode=True), encoding="utf-8")
    (dest / "reference_impl.py").write_text(_REFERENCE, encoding="utf-8")

    shim = (
        "import os, pathlib\n"
        "host = pathlib.Path(os.getcwd())\n"
        "b = host/'.venv'/'bin'; b.mkdir(parents=True, exist_ok=True)\n"
        "p = b/'python'\n"
        "p.write_text('#!/bin/bash\\n'\n"
        f"    'export PYTHONPATH=\"'+str(host/'src')+':{pinned}:{_REPO_SITE}:'"
        "+'${PYTHONPATH:-}\"\\n'\n"
        f"    'exec \"{_REPO_PY}\" \"$@\"\\n')\n"
        "p.chmod(0o755)\nprint('shim ready')\n")

    out = tool_build(
        dest, project, bench_root=tmp_path / "bench",
        dest_root=tmp_path / "tools", run_real=False,
        setup_commands=[[_REPO_PY, "-c", shim]],
        wheelhouse_cmd=["true"])
    assert out["verdict"] == "REHEARSAL_PASS_ONLY", out["stages"]
    assert out["stages"]["rehearsal"]["verdict"] == "PASS_ADAPTED"
    assert out["stages"]["confirm"]["held"] == 1
    # conformance:minilib 无 tests 目录 → 空选取如实
    assert out["stages"]["conformance_selected"] == []
    # draft 束已归档(移出 H9-a 扫描面),原位不再存在
    archived = Path(out["stages"]["draft_archived"])
    assert archived.is_dir() and (archived / "draft.yaml").is_file()
    assert not dest.exists()
    shutil.copytree(archived, dest)      # 拷回供后续负例断言使用

    # 重复 build 不撞车 —— 装配器版本自增是设计(改题面 → 新版本号);
    # "物化目标已存在"分支防的是外部产生的同 id:预建目录触发之。
    from repoproof.runner.tool_pipeline import PipelineError

    v2_dir = project / "tool_tasks" / "tool-minilib-tool-v2"
    v2_dir.mkdir(parents=True)
    with pytest.raises(PipelineError):
        tool_build(dest, project, bench_root=tmp_path / "bench",
                   dest_root=tmp_path / "tools", run_real=False,
                   setup_commands=[[_REPO_PY, "-c", shim]],
                   wheelhouse_cmd=["true"])
    # 编排不吞错:confirm 失败原样传导
    (dest / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    with pytest.raises(ConfirmError):
        confirm_tool_draft(dest, project)
