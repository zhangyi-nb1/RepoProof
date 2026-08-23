"""LOCAL-TOOL 确认流的钉死(M2-b · [G1] 人闸)。

正流:intake → draft 束 → 程序化"人补" → confirm → 冻结契约 + T 全绿。
D 系确认闸按纪律喂违反:骨架原样必须一次报全空缺;reference 缺真
import 必须单独抓(弱档执法的入口条件在确认期就挡,不等 fake 红)。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from repoproof.adoption.intake.tool_confirm import (
    ConfirmError,
    check_draft_complete,
    confirm_tool_draft,
    write_draft_bundle,
)
from repoproof.adoption.intake.tool_intake import run_tool_intake
from repoproof.domain.models import TaskContract


def _mini_repo(tmp: Path) -> Path:
    root = tmp / "repo"
    pkg = root / "src" / "acme_lib"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        "def shout(text):\n    return text.upper()\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "acme-lib"\nversion = "0.1.0"\n'
        'requires-python = ">=3.10"\ndependencies = []\n'
        "[build-system]\nrequires = [\"setuptools\"]\n"
        'build-backend = "setuptools.build_meta"\n', encoding="utf-8")
    (root / "LICENSE").write_text("MIT License", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("def test_ok():\n    assert True\n",
                                              encoding="utf-8")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "v"]):
        subprocess.run(["git", "-C", str(root), *args], check=True,
                       capture_output=True)
    return root


@pytest.fixture()
def draft_bundle(tmp_path):
    rep = run_tool_intake("https://github.com/a/acme-lib", "把 shout 做成工具",
                          cache_root=tmp_path / "cache",
                          local_path=_mini_repo(tmp_path))
    dest = write_draft_bundle(rep, tmp_path / "draft")
    return tmp_path, rep, dest


def _complete(dest: Path) -> None:
    """程序化扮演"人补缺":填 LLM/USER 字段、放样例、写真 reference。"""
    draft = yaml.safe_load((dest / "draft.yaml").read_text(encoding="utf-8"))
    draft["tool"]["summary"] = "文本大写工具"
    draft["tool"]["interface"]["input"]["format"] = "TXT"
    draft["tool"]["interface"]["output"]["format"] = "TXT"
    draft["capability"]["statement"] = (
        "把 acme_lib.shout 包装为本地 CLI:输入文本文件,输出其大写;"
        "空文件属用户错误(抛 UserInputError → exit 1)。")
    draft["capability"]["output_schema"] = "UppercasedText"
    (dest / "draft.yaml").write_text(
        yaml.safe_dump(draft, allow_unicode=True, sort_keys=False), encoding="utf-8")
    for n, text in (("a", "hello"), ("b", "world"), ("c", "gamma")):
        (dest / "examples" / f"{n}.txt").write_text(text, encoding="utf-8")
    (dest / "examples.yaml").write_text(yaml.safe_dump({"examples": [
        {"input": "--help", "expected": "contains:usage"},
        {"input_file": "a.txt", "expected": "contains:HELLO"},
        {"input_file": "b.txt", "expected": "contains:WORLD"},
        {"input_file": "c.txt", "expected": "contains:GAMMA"},
    ]}, allow_unicode=True), encoding="utf-8")
    (dest / "reference_impl.py").write_text(
        '"""reference:真调 acme_lib。"""\n'
        "from pathlib import Path\n\n"
        "import acme_lib\n\n\n"
        "class UserInputError(ValueError):\n    pass\n\n\n"
        "def extract(input_path: Path) -> str:\n"
        "    text = input_path.read_text(encoding=\"utf-8\")\n"
        "    if not text.strip():\n"
        "        raise UserInputError(\"empty input\")\n"
        "    return acme_lib.shout(text)\n", encoding="utf-8")


def test_bundle_layout_and_refuse_overwrite(draft_bundle):
    tmp, rep, dest = draft_bundle
    for rel in ("draft.yaml", "GAPS.md", "examples.yaml", "reference_impl.py"):
        assert (dest / rel).is_file(), f"draft 束缺 {rel}"
    assert (dest / "examples").is_dir()
    assert "owner=USER" in (dest / "GAPS.md").read_text(encoding="utf-8")
    with pytest.raises(ConfirmError):
        write_draft_bundle(rep, dest)          # 已存在 → 拒覆盖


def test_skeleton_draft_reports_all_gaps_at_once(draft_bundle):
    """骨架原样 confirm:一次报全,且点名 statement/summary/examples/reference。"""
    _, _rep, dest = draft_bundle
    draft = yaml.safe_load((dest / "draft.yaml").read_text(encoding="utf-8"))
    problems = check_draft_complete(draft, dest)
    joined = "\n".join(problems)
    for token in ("capability.statement", "tool.summary", "examples 仅 0 组",
                  "reference_impl 仍是骨架"):
        assert token in joined, f"未报 {token}:{problems}"


def test_reference_without_upstream_import_is_caught(draft_bundle):
    _, _rep, dest = draft_bundle
    _complete(dest)
    ref = dest / "reference_impl.py"
    ref.write_text(ref.read_text(encoding="utf-8").replace(
        "import acme_lib\n", "").replace("acme_lib.shout(text)", "text.upper()"),
        encoding="utf-8")
    draft = yaml.safe_load((dest / "draft.yaml").read_text(encoding="utf-8"))
    problems = check_draft_complete(draft, dest)
    assert any("未 import acme_lib" in p for p in problems), problems


def test_confirm_happy_path_freezes_contract(draft_bundle):
    tmp, _rep, dest = draft_bundle
    _complete(dest)
    project = tmp / "proj"
    project.mkdir()
    info = confirm_tool_draft(dest, project)
    assert info["task_id"] == "tool-acme-lib-v1"
    assert info["public"] == 3 and info["held"] == 1
    c, _ = TaskContract.load_frozen(
        project / "contracts" / f"{info['task_id']}.yaml", require_sidecar=True)
    assert c.task_family == "LOCAL-TOOL" and c.tool.name == "acme-lib"
    # held-out 文件本体只进 oracle(确认流传导装配器纪律)
    assert (project / "oracle" / info["task_id"] / "fixtures" / "c.txt").is_file()
    skel_pub = project / "fixtures" / "tool_skeleton_acme-lib" / "public_tests"
    assert not (skel_pub / "fixtures" / "c.txt").exists()


def test_confirm_refuses_incomplete_draft(draft_bundle):
    tmp, _rep, dest = draft_bundle
    with pytest.raises(ConfirmError) as e:
        confirm_tool_draft(dest, tmp / "proj2")
    assert any("statement" in p for p in e.value.problems)
