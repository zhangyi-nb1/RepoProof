"""DIRECT_WRAP 确定性快路径 · Gate 3 关闭条件的钉死。

- 受信模板:同 spec 重复编译逐字节一致;非法 locator/异常名在模型层拒;
- 全链:合成 minilib 世界 + 已确认 DIRECT_WRAP plan → tool_build 零模型
  拿 **PASS_DIRECT**(零 diff + oracle/held-out/provenance/replay 全门),
  agent_invoked=false,产品投影 NO_REPAIR_NEEDED;
- 负控:wrong-symbol 计划 → 全链 FAIL,且**不自动切 AGENT_ADAPT**
  (无彩排/真发段,带 failure_assessment);
- never-call / call-ignore-result 由装配器既有控制矩阵与 provenance/
  import-hook 层负责(E2E 已钉),此处不重复建第二套。
"""

from __future__ import annotations

import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest
import yaml

from repoproof.adoption.delivery.direct_adapter import (
    DirectAdapterError,
    DirectAdapterSpec,
    compile_direct_adapter,
    derive_adapter_spec,
)
from repoproof.adoption.planning.capability_plan import (
    CapabilityPlanV1,
    DetectedSurface,
    confirm_plan,
)

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

_REFERENCE = '''"""reference:真调 pinned minilib(出题人提供,绝不交付)。"""
from pathlib import Path

import minilib


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        text = input_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise UserInputError(str(e)) from e
    try:
        return minilib.rows_to_markdown(text)
    except minilib.FormatError as e:
        raise UserInputError(str(e)) from e
'''


def _mk_plan(locator: str) -> CapabilityPlanV1:
    plan = CapabilityPlanV1(
        source={"url": "file://minilib", "commit": "x" * 40},
        capability_goal="MINI 文本转 Markdown 行表",
        detected_surfaces=[DetectedSurface(
            kind="python_callable", locator=locator,
            signature="(text)", evidence=["minilib/__init__.py:8"],
            confidence="HIGH")],
        support_status="SUPPORTED",
        implementation_route="DIRECT_WRAP",
        reason_codes=["PINNED_PUBLIC_PYTHON", "SINGLE_CALLABLE_MAPPED"],
    ).seal()
    return confirm_plan(plan, acks=list(plan.human_confirmations))


# ------------------------------------------------------------------ 单元层

def test_template_is_deterministic_and_calls_upstream():
    spec = DirectAdapterSpec(locator="minilib:rows_to_markdown",
                             upstream_exceptions=["minilib.FormatError"])
    a = compile_direct_adapter(spec)
    b = compile_direct_adapter(spec)
    assert a == b                                  # 受信模板逐字节确定
    assert "import minilib" in a
    assert "minilib.rows_to_markdown(arg)" in a
    assert "UserInputError" in a


def test_spec_rejects_illegal_locator_and_exception():
    with pytest.raises(ValueError):
        DirectAdapterSpec(locator="minilib; rm -rf /:boom")
    with pytest.raises(ValueError):
        DirectAdapterSpec(locator="minilib:fn",
                          upstream_exceptions=["x; import os"])


def test_derive_requires_confirmed_single_high_callable():
    plan = _mk_plan("minilib:rows_to_markdown")
    spec = derive_adapter_spec(plan)
    assert spec.locator == "minilib:rows_to_markdown"
    assert spec.input_mode == "text"               # 签名 (text) → 读文本传入
    plan2 = plan.model_copy(deep=True)
    plan2.implementation_route = "AGENT_ADAPT"
    with pytest.raises(DirectAdapterError):
        derive_adapter_spec(plan2)


# ------------------------------------------------------------------ 全链层

def _world(tmp_path, monkeypatch, *, locator: str):
    from repoproof.adoption.intake.tool_confirm import write_draft_bundle
    from repoproof.adoption.intake.tool_intake import run_tool_intake
    from repoproof.harness import host_guard

    monkeypatch.setattr(host_guard, "DEFAULT_PROTECTED", ())
    monkeypatch.delenv("REPOPROOF_PROTECTED_DIRS", raising=False)

    project = tmp_path / "proj"
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
    # DIRECT_WRAP 计划(已确认)入束 —— 路由的唯一驱动源
    (dest / "plan.yaml").write_text(
        yaml.safe_dump(_mk_plan(locator).model_dump(), allow_unicode=True,
                       sort_keys=False), encoding="utf-8")

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
    return project, dest, [[_REPO_PY, "-c", shim]]


@pytest.mark.slow
def test_direct_wrap_full_chain_reaches_pass_direct(tmp_path, monkeypatch):
    from repoproof.runner.tool_pipeline import tool_build

    project, dest, setup = _world(tmp_path, monkeypatch,
                                  locator="minilib:rows_to_markdown")
    out = tool_build(dest, project, bench_root=tmp_path / "bench",
                     dest_root=tmp_path / "tools", run_real=True,
                     setup_commands=setup, wheelhouse_cmd=["true"])
    assert out["stages"]["route"]["route"] == "DIRECT_WRAP"
    assert out["stages"]["route"]["agent_invoked"] is False
    d = out["stages"]["direct"]
    assert d["verdict"] == "PASS_DIRECT", out["stages"]
    assert d["product_stop_code"] == "NO_REPAIR_NEEDED"
    assert "rehearsal" not in out["stages"]        # 快路径不烧彩排/真发
    assert "real" not in out["stages"]
    assert out["exported"], out
    impl = (Path(out["exported"]) / "src" / "minilib_tool" / "impl.py")
    assert "DIRECT_WRAP 受信模板生成" in impl.read_text(encoding="utf-8")


@pytest.mark.slow
def test_direct_wrap_wrong_symbol_fails_without_agent_fallback(tmp_path, monkeypatch):
    from repoproof.runner.tool_pipeline import tool_build

    project, dest, setup = _world(tmp_path, monkeypatch,
                                  locator="minilib:no_such_fn")
    out = tool_build(dest, project, bench_root=tmp_path / "bench",
                     dest_root=tmp_path / "tools", run_real=True,
                     setup_commands=setup, wheelhouse_cmd=["true"])
    assert out["exported"] is None
    assert out["verdict"] not in ("PASS_DIRECT", "PASS_ADAPTED")
    # 失败不得自动切 AGENT_ADAPT:无彩排/真发段,产品投影在案
    assert "rehearsal" not in out["stages"]
    assert "real" not in out["stages"]
    assert "failure_assessment" in out["stages"]["direct"]
