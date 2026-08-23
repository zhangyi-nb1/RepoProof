"""LLM 起草层的钉死(M2-d · [G1] LLM 限草稿层)。

- fake 起草器与真 LLM 同接口同落笔路径 —— 全流用 fake 钉:起草后
  D 闸剩余缺口只剩人的活(样例真值),补样例即 confirm 通过;
- 人已写的字段一个字不覆盖(summary 人版保留 / reference 人写 skipped);
- LiteLLM 解析回路用打桩喂:坏 JSON 首发→重试成功;两发都坏→如实抛;
  通道未配置→如实抛(不静默降级到 fake —— 降级要显式)。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from repoproof.adoption.intake.tool_confirm import (
    confirm_tool_draft,
    write_draft_bundle,
)
from repoproof.adoption.intake.tool_drafter import (
    DraftError,
    FakeDrafter,
    LiteLLMDrafter,
    draft_into_bundle,
)
from repoproof.adoption.intake.tool_intake import run_tool_intake


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
def world(tmp_path):
    rep = run_tool_intake("https://github.com/a/acme-lib", "把 shout 做成工具",
                          cache_root=tmp_path / "cache",
                          local_path=_mini_repo(tmp_path))
    dest = write_draft_bundle(rep, tmp_path / "draft")
    return tmp_path, rep, dest


def test_fake_draft_fills_llm_gaps_then_human_only_examples_remain(world):
    tmp, rep, dest = world
    out = draft_into_bundle(rep, dest, FakeDrafter())
    assert "capability.statement" in out["fields_drafted"]
    assert "reference_impl" in out["fields_drafted"]
    meta = json.loads((dest / "draft_meta.json").read_text(encoding="utf-8"))
    assert meta["drafter"] == "fake-drafter"

    # 起草后:补人的活(样例真值)即可 confirm 通过 —— [G1] 分工闭环
    for n, text in (("a", "x"), ("b", "y"), ("c", "z")):
        (dest / "examples" / f"{n}.txt").write_text(text, encoding="utf-8")
    ex = dest / "examples.yaml"
    ex.write_text(ex.read_text(encoding="utf-8").replace(
        "examples: []",
        "examples:\n"
        "  - {input: '--help', expected: 'contains:usage'}\n"
        "  - {input_file: a.txt, expected: 'contains:acme'}\n"
        "  - {input_file: b.txt, expected: 'contains:acme'}\n"
        "  - {input_file: c.txt, expected: 'contains:acme'}\n"), encoding="utf-8")
    project = tmp / "proj"
    project.mkdir()
    info = confirm_tool_draft(dest, project)
    assert info["task_id"].startswith("tool-acme-lib")


def test_human_written_fields_are_never_overwritten(world):
    _, rep, dest = world
    doc = yaml.safe_load((dest / "draft.yaml").read_text(encoding="utf-8"))
    doc["tool"]["summary"] = "人写的摘要"
    (dest / "draft.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (dest / "reference_impl.py").write_text(
        "import acme_lib\n\ndef extract(p):\n    return acme_lib.shout('x')\n",
        encoding="utf-8")
    out = draft_into_bundle(rep, dest, FakeDrafter())
    doc2 = yaml.safe_load((dest / "draft.yaml").read_text(encoding="utf-8"))
    assert doc2["tool"]["summary"] == "人写的摘要"
    assert "tool.summary" not in out["fields_drafted"]
    assert any("reference_impl" in s for s in out["skipped"])
    assert "acme_lib.shout('x')" in (dest / "reference_impl.py").read_text(
        encoding="utf-8")


def _stub_litellm(monkeypatch, replies: list[str]):
    calls = {"n": 0}

    class _Msg:
        def __init__(self, c): self.content = c

    class _Choice:
        def __init__(self, c): self.message = _Msg(c)

    class _Resp:
        def __init__(self, c):
            self.choices = [_Choice(c)]
            self.usage = None

    import litellm

    def fake_completion(**kw):
        i = min(calls["n"], len(replies) - 1)
        calls["n"] += 1
        return _Resp(replies[i])

    monkeypatch.setattr(litellm, "completion", fake_completion)
    return calls


_GOOD = json.dumps({"summary": "s", "input_format": "TXT",
                    "output_format": "TXT", "output_schema": "Out",
                    "statement": "题面", "reference_impl": "import acme_lib\n",
                    "example_suggestions": []})


def test_litellm_retry_then_parse(monkeypatch, world):
    _, rep, dest = world
    for k, v in (("REPOPROOF_DRAFTER_MODEL", "m"),
                 ("REPOPROOF_DRAFTER_BASE", "http://x"),
                 ("REPOPROOF_DRAFTER_KEY", "k")):
        monkeypatch.setenv(k, v)
    calls = _stub_litellm(monkeypatch, ["not json at all", _GOOD])
    out = draft_into_bundle(rep, dest, LiteLLMDrafter())
    assert calls["n"] == 2 and "capability.statement" in out["fields_drafted"]


def test_litellm_double_garbage_raises(monkeypatch, world):
    _, rep, dest = world
    for k, v in (("REPOPROOF_DRAFTER_MODEL", "m"),
                 ("REPOPROOF_DRAFTER_BASE", "http://x"),
                 ("REPOPROOF_DRAFTER_KEY", "k")):
        monkeypatch.setenv(k, v)
    _stub_litellm(monkeypatch, ["garbage", "still garbage"])
    with pytest.raises(DraftError):
        draft_into_bundle(rep, dest, LiteLLMDrafter())


def test_unconfigured_channel_raises_not_silently_degrades(monkeypatch):
    for k in ("REPOPROOF_DRAFTER_MODEL", "REPOPROOF_DRAFTER_BASE",
              "REPOPROOF_DRAFTER_KEY", "REPOPROOF_MODEL",
              "REPOPROOF_API_BASE", "REPOPROOF_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(DraftError):
        LiteLLMDrafter()
