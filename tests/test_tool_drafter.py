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

from repoproof.adoption.intake.intent_contract import new_intent_contract
from repoproof.adoption.intake.tool_confirm import (
    ConfirmError,
    confirm_tool_draft,
    confirm_tool_intent_file,
    write_draft_bundle,
)
from repoproof.adoption.intake.tool_drafter import (
    _REQUIREMENT_BRIEF_SCHEMA,
    _SUMMARY_SCHEMA,
    _SYSTEM,
    CodexDrafter,
    DeliveryAdmissionError,
    DraftError,
    DraftProjectionError,
    FakeDrafter,
    LiteLLMDrafter,
    _validate_fixture_builder_source,
    draft_into_bundle,
    normalize_draft_document,
    reference_source_policy_errors,
    validate_repo_summary_document,
)
from repoproof.adoption.intake.tool_intake import run_tool_intake


def test_draft_prompt_distinguishes_html_and_xhtml_media_types() -> None:
    assert "delivery_requirements" in _SYSTEM
    assert "product_support_profile" in _SYSTEM
    assert "media type" in _SYSTEM
    assert "HTML uses text/html" not in _SYSTEM


def test_reference_policy_rejects_broad_error_masking() -> None:
    broad = (
        "def extract(path):\n"
        "    try:\n"
        "        return upstream.convert(path.read_text())\n"
        "    except Exception as exc:\n"
        "        raise UserInputError('bad input') from exc\n"
    )
    explicit = (
        "def extract(path):\n"
        "    try:\n"
        "        return upstream.convert(path.read_text())\n"
        "    except (UnicodeDecodeError, ValueError) as exc:\n"
        "        raise UserInputError('bad input') from exc\n"
    )

    assert reference_source_policy_errors(broad) == [
        "REFERENCE_BROAD_EXCEPTION_MASKING"
    ]
    assert reference_source_policy_errors(explicit) == []


@pytest.mark.parametrize(
    "source",
    [
        (
            "from pathlib import Path\n"
            "def build(blueprint, output_path: Path):\n"
            "    output_path.write_text(blueprint.get('kind', 'text'))\n"
        ),
        (
            "from pathlib import Path\n"
            "def build(blueprint, output_path: Path):\n"
            "    output_path.mkdir()\n"
            "    for row in blueprint['pages']:\n"
            "        (output_path / row['name']).write_text(row['text'])\n"
        ),
    ],
)
def test_workspace_fixture_builder_binds_the_published_parameters_object(
    source: str,
) -> None:
    """Anonymous builders may not invent top-level scenario parameter fields."""

    with pytest.raises(
        DraftProjectionError,
        match="FIXTURE_BLUEPRINT_PARAMETER_BINDING_MISMATCH",
    ):
        _validate_fixture_builder_source(source)


@pytest.mark.parametrize(
    "parameter_expression",
    ["blueprint['parameters']", "blueprint.get('parameters', {})"],
)
def test_workspace_fixture_builder_accepts_explicit_parameter_binding(
    parameter_expression: str,
) -> None:
    source = (
        "from pathlib import Path\n"
        "def build(blueprint, output_path: Path):\n"
        f"    parameters = {parameter_expression}\n"
        "    output_path.write_text(str(parameters), encoding='utf-8')\n"
    )

    _validate_fixture_builder_source(source)


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
    assert meta["verifier_context_policy"] == "public-contract-only-v1"
    drafted = yaml.safe_load((dest / "draft.yaml").read_text(encoding="utf-8"))
    assert drafted["capability"]["output_schema"] == "DraftedOutput"
    assert drafted["tool"]["interface"]["output"]["contract"] == {
        "media_type": "text/plain",
        "root_type": "text",
        "required": {},
        "validation_profile": "plain_text_v1",
    }

    # 起草后:人要确认公开语义,并补样例真值。模型不能代替人闸。
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
    (dest / "reference.lock.txt").write_text("acme-lib==0.1.0\n", encoding="utf-8")
    confirm_tool_intent_file(dest)
    project = tmp / "proj"
    project.mkdir()
    # The offline fake verifier deliberately refuses to claim independent
    # semantic success.  Human examples alone must not turn that placeholder
    # into a confirmable task.
    with pytest.raises(ConfirmError) as raised:
        confirm_tool_draft(dest, project)
    assert "所有可见返回路径都固定为 ok=False" in str(raised.value)


def test_verifier_is_drafted_from_an_exact_public_context_only(world) -> None:
    _, rep, dest = world
    (dest / "examples" / "golden-secret.txt").write_text(
        "GOLDEN_BODY_MUST_NOT_REACH_VERIFIER",
        encoding="utf-8",
    )
    (dest / "held-out-secret.txt").write_text(
        "HELD_OUT_BODY_MUST_NOT_REACH_VERIFIER",
        encoding="utf-8",
    )

    class CapturingDrafter(FakeDrafter):
        def __init__(self) -> None:
            self.last_usage: dict = {}
            self.verifier_context: dict | None = None

        def draft(self, context: dict) -> dict:
            document = super().draft(context)
            document["reference_impl"] += "\n# PRIVATE_REFERENCE_SOURCE_MARKER\n"
            self.last_usage = {"stage": "proposal"}
            return document

        def draft_verifier(self, context: dict) -> dict[str, str]:
            self.verifier_context = context
            self.last_usage = {"stage": "verifier"}
            return super().draft_verifier(context)

    drafter = CapturingDrafter()
    draft_into_bundle(rep, dest, drafter)

    assert drafter.verifier_context is not None
    assert set(drafter.verifier_context) == {
        "capability_goal",
        "semantic_commitments",
        "artifact_protocol",
        "delivery_requirements",
        "delivery_profile",
        "input_format",
        "output_format_id",
        "output_format",
        "output_contract",
        "workspace_contract",
        "output_validation_profile_spec",
        "upstream_public_info",
    }
    assert set(drafter.verifier_context["upstream_public_info"]) == {
        "source_repo_url",
        "requested_revision",
        "resolved_commit",
        "distribution",
        "import_module",
        "public_api",
        "cli_entry_points",
        "capability_candidates",
        "tool_name",
    }
    serialised = json.dumps(drafter.verifier_context, ensure_ascii=False)
    assert drafter.verifier_context["artifact_protocol"]["observations"]
    assert "PRIVATE_REFERENCE_SOURCE_MARKER" not in serialised
    assert "GOLDEN_BODY_MUST_NOT_REACH_VERIFIER" not in serialised
    assert "HELD_OUT_BODY_MUST_NOT_REACH_VERIFIER" not in serialised
    meta = json.loads((dest / "draft_meta.json").read_text(encoding="utf-8"))
    assert meta["usage_by_stage"] == {
        "proposal_and_reference": {"stage": "proposal"},
        "semantic_verifier": {"stage": "verifier"},
    }


def test_current_product_draft_rejects_a_common_cause_verifier(world) -> None:
    _, rep, dest = world

    class CommonCauseDrafter(FakeDrafter):
        def draft(self, context: dict) -> dict:
            document = super().draft(context)
            document["semantic_verifier"] = "import acme_lib\n"
            return document

    with pytest.raises(
        DraftError,
        match="VERIFIER_MUST_USE_INDEPENDENT_CALL",
    ):
        draft_into_bundle(rep, dest, CommonCauseDrafter())


def test_current_product_draft_requires_an_independent_verifier_method(world) -> None:
    _, rep, dest = world

    class ProposalOnlyDrafter:
        name = "proposal-only"
        last_usage: dict = {}

        @staticmethod
        def draft(context: dict) -> dict:
            return FakeDrafter().draft(context)

    with pytest.raises(
        DraftError,
        match="INDEPENDENT_VERIFIER_DRAFTER_REQUIRED",
    ):
        draft_into_bundle(rep, dest, ProposalOnlyDrafter())


def test_typed_directory_need_compiles_a_v4_workspace_draft(world) -> None:
    _, report, destination = world

    class WorkspaceDrafter:
        name = "workspace-test-drafter"
        last_usage: dict = {}

        def draft(self, context: dict) -> dict:
            return normalize_draft_document(
                {
                    "summary": "生成离线研究工作区",
                    "delivery_requirements": {
                        "inputs": [{
                            "kind": "directory",
                            "location": "local",
                            "representation": "binary",
                            "format_label": "研究资料目录",
                            "role": "待整理资料",
                        }],
                        "outputs": [{
                            "kind": "directory",
                            "format_id": "workspace_bundle",
                            "format_label": "离线工作区",
                            "role": "可交接结果",
                        }],
                        "network": "offline",
                        "credentials": "none",
                        "lifecycle": "per_invocation",
                        "runtime": "local_cpu",
                        "browser": "none",
                        "external_side_effects": "none",
                    },
                    "output_required_fields": [],
                    "output_schema": "ResearchWorkspace",
                    "workspace_contract": {
                        "schema_version": 1,
                        "rules": [{
                            "path_pattern": "README.md",
                            "role": "human documentation",
                            "media_type": "text/markdown",
                            "validation_profile": "text_utf8_v1",
                        }],
                        "allow_extra_files": False,
                        "entrypoints": [],
                        "runnable": False,
                        "smoke_command": [],
                        "smoke_timeout_seconds": 30,
                        "require_offline_wheelhouse": False,
                    },
                    "fixture_builder": (
                        "from pathlib import Path\n"
                        "def build(blueprint, output_path: Path):\n"
                        "    output_path.mkdir(parents=True)\n"
                        "    (output_path / 'brief.txt').write_text(\n"
                        "        blueprint['parameters']['text'], encoding='utf-8')\n"
                    ),
                    "fixture_blueprints": [
                        {
                            "blueprint_id": f"study-{index}",
                            "title": f"研究场景 {index}",
                            "scenario": "一份需要整理的研究资料目录",
                            "input_kind": "directory",
                            "parameters_json": json.dumps(
                                {"text": f"experiment {index}"}
                            ),
                        }
                        for index in range(1, 4)
                    ],
                    "semantic_commitments": [{
                        "commitment_id": "workspace-summary",
                        "public_text": "README 总结输入目录里的资料。",
                        "rationale": "这是用户可核对的交付内容。",
                    }],
                    "artifact_protocol": {
                        "schema_version": 1,
                        "protocol_id": "workspace-summary-v1",
                        "observations": [{
                            "observation_id": "summary-body",
                            "commitment_ids": ["workspace-summary"],
                            "locator": "README.md 的完整 Markdown 正文",
                            "value_encoding": "UTF-8 Markdown 文本",
                        }],
                    },
                    "reference_impl": (
                        "from pathlib import Path\nimport acme_lib\n"
                        "class UserInputError(ValueError):\n    pass\n"
                        "def build_workspace(input_path: Path, output_dir: Path) -> None:\n"
                        "    value = str(acme_lib)\n"
                        "    (output_dir / 'README.md').write_text(value, encoding='utf-8')\n"
                    ),
                    "example_suggestions": [{
                        "description": "包含一份典型资料的目录",
                        "assertion_kind": "exact_file",
                    }],
                },
                capability_goal=context["capability_goal"],
            )

        def draft_verifier(self, context: dict) -> dict[str, str]:
            assert context["delivery_profile"] == "workspace_bundle_v1"
            assert context["workspace_contract"]["rules"]
            return {
                "semantic_verifier": (
                    "from pathlib import Path\nimport acme_lib\n"
                    "def verify(input_path: Path, artifact_dir: Path) -> dict:\n"
                    "    _ = acme_lib\n"
                    "    return {'ok': False, 'reason_codes': "
                    "['INDEPENDENT_REVIEW_REQUIRED'], "
                    "'checked_commitment_ids': ['workspace-summary']}\n"
                )
            }

    draft_into_bundle(report, destination, WorkspaceDrafter())
    document = yaml.safe_load(
        (destination / "draft.yaml").read_text(encoding="utf-8")
    )
    assert document["tool"]["schema_version"] == 4
    assert document["tool"]["delivery_profile_id"] == "workspace_bundle_v1"
    assert document["tool"]["interface"]["input"]["kind"] == "directory"
    assert document["tool"]["interface"]["output"]["kind"] == "directory"
    assert "contract" not in document["tool"]["interface"]["output"]
    assert (destination / "workspace_examples.yaml").is_file()
    assert (destination / "fixture_builder.py").is_file()
    assert (destination / "fixture_blueprints.json").is_file()


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


def test_drafter_refuses_a_draft_whose_traced_goal_changed(world):
    _, rep, dest = world
    doc = yaml.safe_load((dest / "draft.yaml").read_text(encoding="utf-8"))
    doc["_intent_contract"] = new_intent_contract("另一个没有经过重新 intake 的目标")
    (dest / "draft.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(DraftError, match="INTENT_USER_GOAL_MISMATCH"):
        draft_into_bundle(rep, dest, FakeDrafter())


def _stub_litellm(monkeypatch, replies: list[str]):
    calls = {"n": 0, "kwargs": []}

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
        calls["kwargs"].append(kw)
        return _Resp(replies[i])

    monkeypatch.setattr(litellm, "completion", fake_completion)
    return calls


def _delivery(input_format: str, output_format_id: str) -> dict:
    return {
        "inputs": [{
            "kind": "file", "location": "local",
            "representation": "utf8_text",
            "format_label": input_format, "role": "待处理内容",
        }],
        "outputs": [{
            "kind": "text_artifact", "format_id": output_format_id,
            "format_label": output_format_id, "role": "用户产物",
        }],
        "network": "offline",
        "credentials": "none",
        "lifecycle": "per_invocation",
        "runtime": "local_cpu",
        "browser": "none",
        "external_side_effects": "none",
    }


_GOOD = json.dumps({"summary": "s", "delivery_requirements": _delivery("TXT", "plain_text"),
                    "output_required_fields": [], "output_schema": "Out",
                    "semantic_commitments": [{
                        "commitment_id": "convert-input",
                        "public_text": "使用固定版本上游转换输入文本。",
                        "rationale": "用户需要这项转换能力。",
                    }],
                    "artifact_protocol": {
                        "schema_version": 1,
                        "protocol_id": "converted-text-v1",
                        "observations": [{
                            "observation_id": "converted-body",
                            "commitment_ids": ["convert-input"],
                            "locator": "完整 UTF-8 文本正文",
                            "value_encoding": "固定版本上游返回的 UTF-8 文本",
                        }],
                    }, "reference_impl": (
                        "from pathlib import Path\n"
                        "import acme_lib\n\n"
                        "class UserInputError(ValueError):\n    pass\n\n"
                        "def extract(input_path: Path) -> str:\n"
                        "    return acme_lib.shout("
                        "input_path.read_text(encoding='utf-8'))\n"
                    ),
                    "example_suggestions": []})

_GOOD_VERIFIER = json.dumps({
    "semantic_verifier": (
        "from pathlib import Path\n"
        "import acme_lib\n"
        "def verify(input_path: Path, artifact_path: Path) -> dict:\n"
        "    acme_lib.shout(input_path.read_text())\n"
        "    return {'ok': artifact_path.is_file(), 'reason_codes': []}\n"
    ),
})

_GOOD_REPO_ADVICE = {
    "summary": "这个仓库可以整理科研文本，具体边界仍需用户确认。",
    "requirement_briefs": [
        {
            "brief_id": "clean-ris",
            "title": "整理文献记录",
            "scenario": "把不同来源的文献记录整理后继续使用。",
            "delivery_requirements": _delivery("RIS", "ris"),
            "boundary": "不补充外部书目信息",
            "reason": "仓库说明提到可以读取和写出 RIS 文献记录。",
        },
        {
            "brief_id": "review-table",
            "title": "生成检查表",
            "scenario": "把文献记录整理后查看缺失内容。",
            "delivery_requirements": _delivery("RIS", "csv"),
            "boundary": "无法判断的字段保持原样",
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
    calls = _stub_litellm(
        monkeypatch,
        ["not json at all", _GOOD, _GOOD_VERIFIER],
    )
    out = draft_into_bundle(rep, dest, LiteLLMDrafter())
    assert calls["n"] == 3 and "capability.statement" in out["fields_drafted"]
    assert "semantic_verifier" not in calls["kwargs"][1]["messages"][0]["content"]
    verifier_call = calls["kwargs"][2]
    assert "independent semantic verifier" in verifier_call["messages"][0]["content"]
    verifier_context = verifier_call["messages"][1]["content"]
    assert "reference_impl" not in verifier_context
    assert "golden" not in verifier_context.lower()
    assert "held-out" not in verifier_context.lower()


def _valid_projection_document(*, format_id: str, required_fields: list[dict]) -> dict:
    document = json.loads(_GOOD)
    document["delivery_requirements"] = _delivery("实验记录表格", format_id)
    document["output_required_fields"] = required_fields
    document["reference_impl"] = (
        "from pathlib import Path\n"
        "import acme_lib\n\n"
        "class UserInputError(ValueError):\n    pass\n\n"
        "def extract(input_path: Path) -> str:\n"
        "    return acme_lib.shout(input_path.read_text(encoding='utf-8'))\n"
    )
    return document


def _workspace_projection_document() -> dict:
    document = json.loads(_GOOD)
    document["delivery_requirements"] = {
        "inputs": [{
            "kind": "directory",
            "location": "local",
            "representation": "binary",
            "format_label": "本地项目目录",
            "role": "待分析项目",
        }],
        "outputs": [{
            "kind": "directory",
            "format_id": "workspace_bundle",
            "format_label": "离线工作区",
            "role": "可交接结果",
        }],
        "network": "offline",
        "credentials": "none",
        "lifecycle": "per_invocation",
        "runtime": "local_cpu",
        "browser": "none",
        "external_side_effects": "none",
    }
    document["output_required_fields"] = []
    document["output_schema"] = "OfflineWorkspace"
    document["workspace_contract"] = {
        "schema_version": 1,
        "rules": [
            {
                "path_pattern": "README.md",
                "role": "使用说明",
                "media_type": "text/markdown",
                "validation_profile": "text_utf8_v1",
            },
            {
                "path_pattern": "data/result.tsv",
                "role": "结果表",
                "media_type": "text/tab-separated-values",
                "validation_profile": "tsv_v1",
            },
        ],
        "allow_extra_files": False,
        "entrypoints": [],
        "runnable": False,
        "smoke_command": [],
        "smoke_timeout_seconds": 30,
        "require_offline_wheelhouse": False,
        "limits": {
            "max_files": 1,
            "max_total_bytes": 4096,
            "max_file_bytes": 2048,
            "max_depth": 1,
            "max_path_bytes": 8,
        },
    }
    document["fixture_builder"] = (
        "from pathlib import Path\n\n"
        "def build(blueprint: dict, output_path: Path) -> None:\n"
        "    output_path.mkdir(parents=True)\n"
        "    (output_path / 'input.txt').write_text(\n"
        "        str(blueprint['parameters']['text']), encoding='utf-8')\n"
    )
    document["fixture_blueprints"] = [
        {
            "blueprint_id": f"case-{index}",
            "title": f"场景 {index}",
            "scenario": "匿名项目输入",
            "input_kind": "directory",
            "parameters_json": json.dumps({"text": f"value-{index}"}),
        }
        for index in range(1, 4)
    ]
    document["reference_impl"] = (
        "from pathlib import Path\n"
        "import acme_lib\n\n"
        "def build_workspace(input_path: Path, output_dir: Path) -> None:\n"
        "    output_dir.mkdir(parents=True)\n"
        "    value = acme_lib.shout('ok')\n"
        "    (output_dir / 'README.md').write_text(value, encoding='utf-8')\n"
        "    (output_dir / 'data').mkdir()\n"
        "    (output_dir / 'data/result.tsv').write_text(\n"
        "        'value\\n' + value + '\\n', encoding='utf-8')\n"
    )
    return document


def test_workspace_projection_compiles_minimum_satisfiable_resource_limits() -> None:
    """Pre-freeze numeric caps cannot contradict required literal artifacts."""

    drafted = normalize_draft_document(
        _workspace_projection_document(),
        capability_goal="生成匿名离线工作区",
    )

    limits = drafted["workspace_contract"]["limits"]
    assert limits["max_files"] == 2
    assert limits["max_depth"] == 2
    assert limits["max_path_bytes"] == len(b"data/result.tsv")


def test_litellm_preserves_sanitized_second_projection_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bounded failed repair keeps a stable public reason, never raw output."""

    for key, value in (
        ("REPOPROOF_DRAFTER_MODEL", "m"),
        ("REPOPROOF_DRAFTER_BASE", "http://gateway.invalid"),
        ("REPOPROOF_DRAFTER_KEY", "k"),
    ):
        monkeypatch.setenv(key, value)
    rejected = _valid_projection_document(
        format_id="tsv",
        required_fields=[{"name": "sample", "type": "string"}],
    )
    _stub_litellm(
        monkeypatch,
        [json.dumps(rejected, ensure_ascii=False)] * 2,
    )

    with pytest.raises(
        DraftError,
        match=(
            "tool-draft:INVALID_MODEL_OUTPUT:"
            "OUTPUT_REQUIRED_FIELDS_NOT_SUPPORTED"
        ),
    ):
        LiteLLMDrafter().draft({"capability_goal": "整理匿名表格"})


def test_litellm_repairs_contract_projection_without_hiding_delivery_need(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in (
        ("REPOPROOF_DRAFTER_MODEL", "m"),
        ("REPOPROOF_DRAFTER_BASE", "http://gateway.invalid"),
        ("REPOPROOF_DRAFTER_KEY", "k"),
    ):
        monkeypatch.setenv(key, value)
    fields = [
        {"name": "sample", "type": "string"},
        {"name": "converted_value", "type": "number"},
    ]
    rejected = _valid_projection_document(format_id="tsv", required_fields=fields)
    corrected = _valid_projection_document(format_id="tsv", required_fields=[])
    corrected["semantic_commitments"].append({
        "commitment_id": "stable-table-columns",
        "public_text": "输出表格保留样本列并给出换算结果列。",
        "rationale": "文本表格的列是公开语义，不是 JSON object required 字段。",
    })
    corrected["artifact_protocol"]["observations"].append({
        "observation_id": "stable-table-columns",
        "commitment_ids": ["stable-table-columns"],
        "locator": "TSV 首行表头及后续数据行",
        "value_encoding": "固定列顺序的制表符分隔 UTF-8 文本",
    })
    calls = _stub_litellm(
        monkeypatch,
        [json.dumps(rejected, ensure_ascii=False), json.dumps(corrected, ensure_ascii=False)],
    )

    drafted = LiteLLMDrafter().draft({"capability_goal": "整理实验记录"})

    assert calls["n"] == 2
    assert drafted["delivery_requirements"] == corrected["delivery_requirements"]
    assert drafted["output_format"] == "TSV"
    assert drafted["output_contract"]["required"] == {}
    assert drafted["output_contract"]["validation_profile"] == "tsv_table_v1"
    repair_prompt = calls["kwargs"][1]["messages"][1]["content"]
    assert "OUTPUT_REQUIRED_FIELDS_NOT_SUPPORTED" in repair_prompt
    assert '"allows_required_fields": false' in repair_prompt
    assert '"format_id": "tsv"' in repair_prompt


def test_codex_repairs_contract_projection_with_same_bounded_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fields = [{"name": "sample", "type": "string"}]
    rejected = _valid_projection_document(format_id="markdown", required_fields=fields)
    corrected = _valid_projection_document(format_id="markdown", required_fields=[])
    replies = [rejected, corrected]
    calls: list[dict] = []
    drafter = object.__new__(CodexDrafter)
    drafter.last_usage = {}

    def fake_structured(**kwargs):
        calls.append(kwargs)
        return replies[len(calls) - 1]

    monkeypatch.setattr(drafter, "_structured", fake_structured)

    drafted = drafter.draft({"capability_goal": "整理项目记录"})

    assert [row["purpose"] for row in calls] == [
        "tool-draft",
        "tool-draft-projection-repair",
    ]
    repair = calls[1]["context"]["core_projection_repair"]
    assert repair["reason_code"] == "OUTPUT_REQUIRED_FIELDS_NOT_SUPPORTED"
    assert repair["selected_artifact"] == {
        "profile_id": "cli_v2",
        "format_id": "markdown",
        "root_type": "text",
        "allows_required_fields": False,
    }
    assert repair["preserve_delivery_requirements"] == rejected[
        "delivery_requirements"
    ]
    assert drafted["output_contract"]["required"] == {}


def test_codex_compiles_human_confirmed_delivery_instead_of_model_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model cannot redefine an already confirmed delivery topology."""

    authoritative = _delivery("TXT", "plain_text")
    echoed = _valid_projection_document(format_id="plain_text", required_fields=[])
    echoed["delivery_requirements"]["lifecycle"] = "long_running"
    drafter = object.__new__(CodexDrafter)
    drafter.last_usage = {}
    calls: list[dict] = []

    def fake_structured(**kwargs):
        calls.append(kwargs)
        return echoed

    monkeypatch.setattr(drafter, "_structured", fake_structured)

    drafted = drafter.draft({
        "capability_goal": "把本地输入整理成一次性生成的离线产物",
        "authoritative_delivery_requirements": authoritative,
    })

    assert len(calls) == 1
    assert drafted["delivery_requirements"] == authoritative
    assert drafted["delivery_profile"] == "cli_v2"


def test_litellm_compiles_human_confirmed_delivery_instead_of_model_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in (
        ("REPOPROOF_DRAFTER_MODEL", "m"),
        ("REPOPROOF_DRAFTER_BASE", "http://gateway.invalid"),
        ("REPOPROOF_DRAFTER_KEY", "k"),
    ):
        monkeypatch.setenv(key, value)
    authoritative = _delivery("TXT", "plain_text")
    echoed = _valid_projection_document(format_id="plain_text", required_fields=[])
    echoed["delivery_requirements"]["external_side_effects"] = "reversible"
    calls = _stub_litellm(
        monkeypatch,
        [json.dumps(echoed, ensure_ascii=False)],
    )

    drafted = LiteLLMDrafter().draft({
        "capability_goal": "把本地输入整理成一次性生成的离线产物",
        "authoritative_delivery_requirements": authoritative,
    })

    assert calls["n"] == 1
    assert drafted["delivery_requirements"] == authoritative
    assert "authoritative_delivery_requirements" in calls["kwargs"][0]["messages"][1]["content"]


def test_confirmed_unsupported_delivery_stops_before_drafter_call(world) -> None:
    _, report, destination = world
    unsupported = _delivery("TXT", "plain_text")
    unsupported["credentials"] = "required"
    calls = 0

    class NeverCalledDrafter:
        def draft(self, _context: dict) -> dict:
            nonlocal calls
            calls += 1
            raise AssertionError("drafter must not run for unsupported delivery")

    with pytest.raises(DeliveryAdmissionError, match="CREDENTIAL_MODE_MISMATCH"):
        draft_into_bundle(
            report,
            destination,
            NeverCalledDrafter(),
            authoritative_delivery_requirements=unsupported,
        )

    assert calls == 0


def test_litellm_gateway_calls_have_bounded_timeout_and_no_implicit_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in (
        ("REPOPROOF_DRAFTER_MODEL", "m"),
        ("REPOPROOF_DRAFTER_BASE", "http://gateway.invalid"),
        ("REPOPROOF_DRAFTER_KEY", "k"),
        ("REPOPROOF_DRAFTER_TIMEOUT_SECONDS", "17"),
    ):
        monkeypatch.setenv(key, value)
    calls = _stub_litellm(
        monkeypatch,
        [json.dumps(_GOOD_REPO_ADVICE, ensure_ascii=False)],
    )

    LiteLLMDrafter().summarize_repo({"headline": "RIS"})

    assert calls["kwargs"][0]["timeout"] == 17.0
    assert calls["kwargs"][0]["max_retries"] == 0
    response_format = calls["kwargs"][0]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "repo_summary"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"] == _SUMMARY_SCHEMA


def test_long_form_request_allows_anonymous_slow_structured_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Long strict schemas receive the full bounded budget, without retries.

    This is an anonymous transport control rather than a repository fixture:
    short structured replies are available immediately, while a response with
    the shape and size of a complete contract is only available when the
    caller grants the already-admitted maximum request budget.
    """

    for key, value in (
        ("REPOPROOF_DRAFTER_MODEL", "m"),
        ("REPOPROOF_DRAFTER_BASE", "http://gateway.invalid"),
        ("REPOPROOF_DRAFTER_KEY", "k"),
    ):
        monkeypatch.setenv(key, value)
    import litellm

    calls: list[dict] = []

    class _Message:
        content = _GOOD

    class _Choice:
        message = _Message()

    class _Response:
        choices = [_Choice()]
        usage = None

    def slow_structured_completion(**kwargs):
        calls.append(kwargs)
        if float(kwargs["timeout"]) < 300.0:
            raise TimeoutError("anonymous long-form response exceeded request budget")
        return _Response()

    monkeypatch.setattr(litellm, "completion", slow_structured_completion)

    assert LiteLLMDrafter()._once("{}") == _GOOD
    assert len(calls) == 1
    assert calls[0]["timeout"] == 300.0
    assert calls[0]["max_retries"] == 0


def test_litellm_all_assistant_actions_use_their_machine_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in (
        ("REPOPROOF_DRAFTER_MODEL", "m"),
        ("REPOPROOF_DRAFTER_BASE", "http://gateway.invalid"),
        ("REPOPROOF_DRAFTER_KEY", "k"),
    ):
        monkeypatch.setenv(key, value)
    calls = _stub_litellm(
        monkeypatch,
        [
            _GOOD,
            _GOOD_VERIFIER,
            json.dumps(_GOOD_REPO_ADVICE, ensure_ascii=False),
            json.dumps({
                "inputs": [
                    {"input_name": "one.txt", "input_text": "x", "why": "覆盖输入"},
                    {"input_name": "two.txt", "input_text": "y", "why": "覆盖边界"},
                ]
            }, ensure_ascii=False),
        ],
    )
    drafter = LiteLLMDrafter()
    drafter.draft({"capability_goal": "处理一个本地文件"})
    drafter.draft_verifier({"capability_goal": "处理一个本地文件"})
    drafter.summarize_repo({"headline": "Local tool"})
    drafter.propose_example_inputs({"how_many": 2})

    formats = [call["response_format"]["json_schema"] for call in calls["kwargs"]]
    assert [item["name"] for item in formats] == [
        "tool_draft",
        "semantic_verifier",
        "repo_summary",
        "example_inputs",
    ]
    assert all(item["strict"] is True for item in formats)

    def assert_every_object_property_is_required(value: object) -> None:
        if isinstance(value, list):
            for item in value:
                assert_every_object_property_is_required(item)
            return
        if not isinstance(value, dict):
            return
        properties = value.get("properties")
        if value.get("type") == "object" and isinstance(properties, dict):
            assert value.get("additionalProperties") is False
            assert value.get("required") == list(properties)
        for item in value.values():
            assert_every_object_property_is_required(item)

    for item in formats:
        assert_every_object_property_is_required(item["schema"])
    assert [call["timeout"] for call in calls["kwargs"]] == [
        300.0,
        300.0,
        60.0,
        60.0,
    ]
    input_schema = formats[-1]["schema"]["properties"]["inputs"]
    assert input_schema["minItems"] == input_schema["maxItems"] == 2


def test_litellm_timeout_is_classified_without_echoing_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in (
        ("REPOPROOF_DRAFTER_MODEL", "m"),
        ("REPOPROOF_DRAFTER_BASE", "http://gateway.invalid"),
        ("REPOPROOF_DRAFTER_KEY", "k"),
    ):
        monkeypatch.setenv(key, value)
    import litellm

    def timeout(**_kwargs):
        raise TimeoutError("private gateway /Users/alice/secret timed out")

    monkeypatch.setattr(litellm, "completion", timeout)
    with pytest.raises(DraftError, match="^DRAFTER_TIMEOUT$") as raised:
        LiteLLMDrafter().summarize_repo({"headline": "RIS"})
    assert "/Users" not in str(raised.value)


@pytest.mark.parametrize("value", ["abc", "0", "4.9", "301"])
def test_litellm_rejects_invalid_timeout_before_network(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    for key, configured in (
        ("REPOPROOF_DRAFTER_MODEL", "m"),
        ("REPOPROOF_DRAFTER_BASE", "http://gateway.invalid"),
        ("REPOPROOF_DRAFTER_KEY", "k"),
        ("REPOPROOF_DRAFTER_TIMEOUT_SECONDS", value),
    ):
        monkeypatch.setenv(key, configured)
    import litellm

    called = False

    def should_not_call(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("network should not run")

    monkeypatch.setattr(litellm, "completion", should_not_call)
    with pytest.raises(DraftError, match="^DRAFTER_TIMEOUT_CONFIG_INVALID$"):
        LiteLLMDrafter().summarize_repo({"headline": "RIS"})
    assert called is False


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

    result = LiteLLMDrafter().summarize_repo({"headline": "RIS tools"})
    assert result == validate_repo_summary_document(_GOOD_REPO_ADVICE)
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
    "technical_text",
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
def test_repo_advice_admission_does_not_depend_on_wording_keywords(
    technical_text: str,
) -> None:
    advice = json.loads(json.dumps(_GOOD_REPO_ADVICE))
    advice["requirement_briefs"][0]["boundary"] = technical_text
    projected = validate_repo_summary_document(advice)
    technical = projected["requirement_briefs"][0]
    # Delivery support remains purely topology-driven.  A separate UX status
    # prevents code-like prose from entering the one-click user wording path;
    # it does not reinterpret or silently repair the requested task.
    assert technical["support_status"] == "SUPPORTED"
    assert technical["support_reason_codes"] == []
    assert technical["adoption_status"] == "REVIEW_REQUIRED"
    assert technical["adoption_reason_codes"]
    assert technical_text.rstrip("。.;；") in technical["text"]

    safe = json.loads(json.dumps(_GOOD_REPO_ADVICE))
    safe["requirement_briefs"][0]["delivery_requirements"] = _delivery("FASTQ", "html")
    safe["requirement_briefs"][0]["boundary"] = "只使用文件里已有的数据"
    accepted = validate_repo_summary_document(safe)
    assert accepted["recommended_brief_id"] == "clean-ris"
    assert accepted["requirement_briefs"][0]["adoption_status"] == "ADOPTABLE"
    assert accepted["recommended_brief_adoption_status"] == "ADOPTABLE"


def test_repo_advice_shape_is_compiled_from_profile_not_model_prose() -> None:
    assert "text" not in _REQUIREMENT_BRIEF_SCHEMA["properties"]
    delivery_schema = _REQUIREMENT_BRIEF_SCHEMA["properties"]["delivery_requirements"]
    assert delivery_schema["properties"]["outputs"]["type"] == "array"

    advice = json.loads(json.dumps(_GOOD_REPO_ADVICE))
    projected = validate_repo_summary_document(advice)
    brief = projected["requirement_briefs"][0]

    assert brief["delivery_shape"] == {
        "profile_id": "cli_v2",
        "input_kind": "file",
        "input_cardinality": 1,
        "input_representation": "utf8_text",
        "output_kind": "stdout",
        "output_cardinality": 1,
        "output_format_id": "ris",
        "output_extension": ".ris",
        "output_media_type": "application/x-research-info-systems",
        "network": "offline",
        "lifecycle": "per_invocation",
    }
    assert "输出一份RIS 文献文件（.ris）" in brief["text"]


def test_drafter_defines_text_representation_by_bytes_not_file_topology() -> None:
    from repoproof.adoption.intake.tool_drafter import _SUMMARY_SYSTEM, _SYSTEM

    for prompt in (_SUMMARY_SYSTEM, _SYSTEM):
        assert "File delivery alone never implies binary" in prompt
        assert "meaningful Unicode text serialization" in prompt


def test_repo_advice_preserves_but_does_not_adopt_output_outside_profile() -> None:
    advice = json.loads(json.dumps(_GOOD_REPO_ADVICE))
    advice["requirement_briefs"][0]["delivery_requirements"]["outputs"][0][
        "format_id"
    ] = "pdf"

    result = validate_repo_summary_document(advice)
    unsupported = result["requirement_briefs"][0]

    assert unsupported["support_status"] == "UNSUPPORTED"
    assert unsupported["support_reason_codes"] == ["OUTPUT_FORMAT_NOT_IN_PROFILE"]
    assert unsupported["text"] is None
    assert unsupported["delivery_shape"] is None
    assert unsupported["adoption_status"] == "UNAVAILABLE"
    assert unsupported["adoption_reason_codes"] == ["DELIVERY_UNSUPPORTED"]
    assert result["recommended_brief_id"] == unsupported["brief_id"]
    assert result["recommended_brief_support_status"] == "UNSUPPORTED"
    assert result["recommended_brief_adoption_status"] == "UNAVAILABLE"


def test_summary_does_not_repair_a_truthful_unsupported_topology(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in (
        ("REPOPROOF_DRAFTER_MODEL", "m"),
        ("REPOPROOF_DRAFTER_BASE", "http://gateway.invalid"),
        ("REPOPROOF_DRAFTER_KEY", "k"),
    ):
        monkeypatch.setenv(key, value)
    advice = json.loads(json.dumps(_GOOD_REPO_ADVICE))
    advice["requirement_briefs"][0]["delivery_requirements"]["outputs"].append({
        "kind": "text_artifact",
        "format_id": "plain_text",
        "format_label": "Secondary",
        "role": "second user-facing result",
    })
    calls = _stub_litellm(
        monkeypatch,
        [json.dumps(advice, ensure_ascii=False)],
    )

    result = LiteLLMDrafter().summarize_repo({"headline": "anonymous utility"})

    assert calls["n"] == 1
    first = result["requirement_briefs"][0]
    assert first["support_status"] == "UNSUPPORTED"
    assert first["support_reason_codes"] == ["OUTPUT_CARDINALITY_MISMATCH"]


def test_draft_does_not_repair_a_truthful_unsupported_topology(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in (
        ("REPOPROOF_DRAFTER_MODEL", "m"),
        ("REPOPROOF_DRAFTER_BASE", "http://gateway.invalid"),
        ("REPOPROOF_DRAFTER_KEY", "k"),
    ):
        monkeypatch.setenv(key, value)
    document = json.loads(_GOOD)
    document["delivery_requirements"]["outputs"].append({
        "kind": "text_artifact",
        "format_id": "markdown",
        "format_label": "Secondary",
        "role": "second user-facing result",
    })
    calls = _stub_litellm(
        monkeypatch,
        [json.dumps(document, ensure_ascii=False)],
    )

    with pytest.raises(
        DeliveryAdmissionError,
        match="OUTPUT_CARDINALITY_MISMATCH",
    ):
        LiteLLMDrafter().draft({"capability_goal": "process one local input"})
    assert calls["n"] == 1


def test_drafter_context_keeps_bounded_readme_evidence_when_scan_is_truncated() -> None:
    from repoproof.adoption.intake.tool_drafter import _drafter_context

    context = _drafter_context(
        {
            "capability_goal": "turn a local project into a handoff workspace",
            "repo": {
                "repository": "https://example.invalid/anonymous/project",
                "readme_excerpt": "Graph analysis and reporting. " * 100,
                "quickstart": {
                    "value": "from anonymous import Graph",
                    "provenance": "FACT",
                },
                "scan_stats": {"truncated": True},
                "public_api": [],
                "cli_entry_points": [],
                "capability_candidates": [],
            },
            "draft": {"source_repo": {}, "tool": {"name": "project-tool"}},
        }
    )

    assert context["readme_excerpt"].startswith("Graph analysis")
    assert len(context["readme_excerpt"]) == 1200
    assert context["quickstart"] == "from anonymous import Graph"
    assert context["scan_incomplete"] is True


def test_projected_repo_advice_cannot_override_machine_owned_shape() -> None:
    projected = validate_repo_summary_document(_GOOD_REPO_ADVICE)
    projected["requirement_briefs"][0]["delivery_shape"]["output_cardinality"] = 2

    with pytest.raises(DraftError, match="PROJECTED_FIELDS_MISMATCH"):
        validate_repo_summary_document(projected, allow_projected=True)


def test_repo_advice_may_quote_public_api_evidence_outside_adopted_text() -> None:
    """Only adoptable text is a requirement boundary; evidence may name an API."""
    advice = json.loads(json.dumps(_GOOD_REPO_ADVICE))
    advice["requirement_briefs"][0]["title"] = "Excel (or CSV) report"
    advice["requirement_briefs"][0]["reason"] = (
        "README shows load() and src/rispy/parser.py as public evidence."
    )
    validated = validate_repo_summary_document(advice)
    expected = validate_repo_summary_document(_GOOD_REPO_ADVICE)
    assert validated["requirement_briefs"][0]["text"] == expected[
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
