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
    _SYSTEM,
    DraftError,
    FakeDrafter,
    LiteLLMDrafter,
    draft_into_bundle,
    validate_repo_summary_document,
)
from repoproof.adoption.intake.tool_intake import run_tool_intake


def test_draft_prompt_distinguishes_html_and_xhtml_media_types() -> None:
    assert "HTML uses text/html" in _SYSTEM
    assert "XHTML uses application/xhtml+xml" in _SYSTEM
    assert "XHTML/HTML uses text/html" not in _SYSTEM


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
    drafted = yaml.safe_load((dest / "draft.yaml").read_text(encoding="utf-8"))
    assert drafted["capability"]["output_schema"] == "DraftedOutput"
    assert drafted["tool"]["interface"]["output"]["contract"] == {
        "media_type": "text/plain", "root_type": "text", "required": {}}

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
                    "output_contract": {"media_type": "text/plain",
                                        "root_type": "text", "required": {}},
                    "statement": "题面", "reference_impl": "import acme_lib\n",
                    "example_suggestions": []})

_GOOD_REPO_ADVICE = {
    "summary": "这个仓库可以整理科研文本，具体边界仍需用户确认。",
    "requirement_briefs": [
        {
            "brief_id": "clean-ris",
            "title": "整理文献记录",
            "text": "把一份 RIS 文献记录整理成仍可导入文献软件的文件，不联网补资料。",
            "reason": "仓库说明提到可以读取和写出 RIS 文献记录。",
        },
        {
            "brief_id": "review-table",
            "title": "生成检查表",
            "text": "把文献记录整理成 CSV 表格，方便查看缺失内容。",
            "reason": "仓库说明展示了读取记录并查看字段的用法。",
        },
    ],
    "recommended_brief_id": "clean-ris",
}


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


def test_litellm_repo_advice_is_strict_json_and_repairs_once(monkeypatch):
    for key, value in (("REPOPROOF_DRAFTER_MODEL", "m"),
                       ("REPOPROOF_DRAFTER_BASE", "http://x"),
                       ("REPOPROOF_DRAFTER_KEY", "k")):
        monkeypatch.setenv(key, value)
    calls = _stub_litellm(
        monkeypatch,
        ["not json", json.dumps(_GOOD_REPO_ADVICE, ensure_ascii=False)],
    )

    assert LiteLLMDrafter().summarize_repo({"headline": "RIS tools"}) == _GOOD_REPO_ADVICE
    assert calls["n"] == 2


def test_repo_advice_requires_unique_ids_and_a_valid_recommendation() -> None:
    duplicate = json.loads(json.dumps(_GOOD_REPO_ADVICE))
    duplicate["requirement_briefs"][1]["brief_id"] = "clean-ris"
    with pytest.raises(DraftError, match="DUPLICATE_BRIEF_ID"):
        validate_repo_summary_document(duplicate)

    unknown = json.loads(json.dumps(_GOOD_REPO_ADVICE))
    unknown["recommended_brief_id"] = "not-returned"
    with pytest.raises(DraftError, match="UNKNOWN_RECOMMENDED_BRIEF"):
        validate_repo_summary_document(unknown)


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "调用 parse_file(...) 后生成报告。",
        "请 import rispy 并读取文件。",
        "从 src/rispy/parser.py 读取内容。",
        "运行 --output report.tsv。",
        "通过命令行参数选择保存位置。",
        "按 JSON schema 输出结果。",
        "同分时使用 tie-break rule。",
        "并列时按照名称决定顺序。",
        "调用函数名完成处理。",
        "从源码路径读取内容。",
        "使用 SeqIO.parse 读取 FASTQ 后生成报告。",
        "调用 networkx.read_graphml 处理关系数据。",
        "输出 sample_id/value/error_code 字段结构。",
        "把结果写成字段 schema。",
        "使用 `read_graphml` 读取输入。",
    ],
)
def test_repo_advice_rejects_engineering_language_but_allows_user_formats(
    unsafe_text: str,
) -> None:
    unsafe = json.loads(json.dumps(_GOOD_REPO_ADVICE))
    unsafe["requirement_briefs"][0]["text"] = unsafe_text
    with pytest.raises(DraftError, match="ENGINEERING_LANGUAGE"):
        validate_repo_summary_document(unsafe)

    safe = json.loads(json.dumps(_GOOD_REPO_ADVICE))
    safe["requirement_briefs"][0]["text"] = (
        "把 FASTQ 整理成 Markdown 报告，也保留一份 JSON 和 CSV 表格。"
    )
    assert validate_repo_summary_document(safe)["recommended_brief_id"] == "clean-ris"


def test_repo_advice_may_quote_public_api_evidence_outside_adopted_text() -> None:
    """Only adoptable text is a requirement boundary; evidence may name an API."""
    advice = json.loads(json.dumps(_GOOD_REPO_ADVICE))
    advice["requirement_briefs"][0]["title"] = "Excel (or CSV) report"
    advice["requirement_briefs"][0]["reason"] = (
        "README shows load() and src/rispy/parser.py as public evidence."
    )
    validated = validate_repo_summary_document(advice)
    assert validated["requirement_briefs"][0]["text"] == _GOOD_REPO_ADVICE[
        "requirement_briefs"
    ][0]["text"]


def test_fake_drafter_returns_structured_compatible_advice() -> None:
    advice = FakeDrafter().summarize_repo(
        {"headline": "demo", "surfaces": ["read", "write"], "capability_goal": "--json"}
    )
    assert len(advice["requirement_briefs"]) == 2
    assert advice["recommended_brief_id"] == "keep-goal"


def test_unconfigured_channel_raises_not_silently_degrades(monkeypatch):
    for k in ("REPOPROOF_DRAFTER_MODEL", "REPOPROOF_DRAFTER_BASE",
              "REPOPROOF_DRAFTER_KEY", "REPOPROOF_MODEL",
              "REPOPROOF_API_BASE", "REPOPROOF_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(DraftError):
        LiteLLMDrafter()


# ---------------------------------- 通道不可用时要**指路**(2026-08-28 实测)

def test_gateway_unconfigured_label_points_at_the_working_channel(monkeypatch):
    """网关没配、而本机 Codex 就绪时,提示必须说出"手边有一条通的"。

    纪律边界:**不替人换通道**(换通道 = 换计费主体/模型身份/可复现性,
    必须是操作员的显式决定,见 2ab838f 恢复网关默认);但也不能让人对着
    一句"API provider 未配置"干瞪眼 —— 用户实测就是被这句挡住,而 Codex
    订阅一直就绪。所以:不自动换,但要指路。
    """
    from repoproof.adoption.intake import tool_drafter as td

    monkeypatch.delenv("REPOPROOF_DRAFTER_BACKEND", raising=False)
    monkeypatch.setattr(td, "_litellm_ready", lambda: False)
    monkeypatch.setattr(td, "_codex_ready", lambda: True)

    st = td.online_drafter_status()
    assert st["backend"] == "litellm" and not st["ready"]      # 默认没被偷换
    assert "run_ui_codex.sh" in str(st["label"])               # 但指了路


# --------------- temperature 降级(2026-08-28:同一模型时通时不通) ---------------

def test_temperature_is_dropped_only_when_the_model_rejects_it():
    """先要确定性,模型不收就**显式降级**重试一次,并记下这个事实。

    实录:同一台机器、同一个模型(openai/gpt-5.6-terra),起草一会儿能通、
    一会儿抛 `UnsupportedParamsError: gpt-5 models don't support
    temperature=0` —— litellm 的模型能力表是联网拉取的,拉不到就回落本地
    备份,而本地备份把 gpt-5.* 一律按"只收 temperature=1"处理。**能不能
    起草竟取决于此刻能不能连上 GitHub**,这种脆弱性不能留。
    """
    from repoproof.adoption.intake.tool_drafter import (
        _completion_with_temperature_fallback,
    )

    calls: list[dict] = []

    class _Picky:
        @staticmethod
        def completion(**kwargs):
            calls.append(kwargs)
            if "temperature" in kwargs:
                raise RuntimeError(
                    "UnsupportedParamsError: gpt-5 models don't support temperature=0")
            return "ok"

    resp, dropped = _completion_with_temperature_fallback(_Picky, model="m")
    assert resp == "ok" and dropped is True
    assert "temperature" in calls[0] and "temperature" not in calls[1]  # 先试后降


def test_temperature_kept_when_supported_and_other_errors_still_raise():
    """正控 + 负控:支持就保留;**别的错误照旧抛**,不许被降级逻辑吞掉。"""
    from repoproof.adoption.intake.tool_drafter import (
        _completion_with_temperature_fallback,
    )

    class _Fine:
        @staticmethod
        def completion(**kwargs):
            assert kwargs.get("temperature") == 0
            return "ok"

    assert _completion_with_temperature_fallback(_Fine, model="m") == ("ok", False)

    class _Broken:
        @staticmethod
        def completion(**kwargs):
            raise RuntimeError("AuthenticationError: bad key")

    with pytest.raises(RuntimeError, match="AuthenticationError"):
        _completion_with_temperature_fallback(_Broken, model="m")
