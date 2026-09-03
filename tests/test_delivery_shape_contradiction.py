"""模型文档内部自相矛盾的交付形态必须被点名、可修,而不是当作"用户需求不受支持"
(incident-delivery-shape-self-contradiction-*)。

不变量:
  I1 文档里带 workspace 成员(workspace_contract / fixture_builder / fixture_blueprints /
     outputs.format_id=workspace_bundle)而 outputs[*].kind 不是 directory → 这是表示层
     矛盾,投影为 DraftProjectionError(可做一次有据修复),不是 DeliveryAdmissionError;
  I2 公开诊断必须点名矛盾的字段(loc 指向 delivery_requirements.outputs.N.kind)并说出
     它与哪个成员冲突;
  I3 真正的单文件 cli 需求(无任何 workspace 成员)照旧走 cli_v2,不受影响。
"""

from __future__ import annotations

import copy
import json

import pytest

from repoproof.adoption.intake.tool_drafter import (
    DeliveryAdmissionError,
    DraftError,
    DraftProjectionError,
    normalize_draft_document,
    public_validation_diagnostics,
)

_GOAL = "生成匿名离线工作区"

_WORKSPACE_DOC = {
    "summary": "生成离线工作区",
    "delivery_requirements": {
        "inputs": [
            {
                "kind": "directory",
                "location": "local",
                "representation": "binary",
                "format_label": "资料目录",
                "role": "待整理资料",
            }
        ],
        "outputs": [
            {
                "kind": "directory",
                "format_id": "workspace_bundle",
                "format_label": "离线工作区",
                "role": "可交接结果",
            }
        ],
        "network": "offline",
        "credentials": "none",
        "lifecycle": "per_invocation",
        "runtime": "local_cpu",
        "browser": "none",
        "external_side_effects": "none",
    },
    "output_required_fields": [],
    "output_schema": "AnonWorkspace",
    "workspace_contract": {
        "schema_version": 1,
        "rules": [
            {
                "path_pattern": "README.md",
                "role": "human documentation",
                "media_type": "text/markdown",
                "validation_profile": "text_utf8_v1",
            }
        ],
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
        "    (output_path / 'brief.txt').write_text(blueprint['parameters']['text'], encoding='utf-8')\n"
    ),
    "fixture_blueprints": [
        {
            "blueprint_id": f"study-{index}",
            "title": f"场景 {index}",
            "scenario": "一份资料目录",
            "input_kind": "directory",
            "parameters_json": json.dumps({"text": f"experiment {index}"}),
        }
        for index in range(1, 4)
    ],
    "semantic_commitments": [
        {
            "commitment_id": "workspace-summary",
            "public_text": "README 总结输入目录里的资料。",
            "rationale": "用户可核对。",
        }
    ],
    "artifact_protocol": {
        "schema_version": 1,
        "protocol_id": "anon-v1",
        "observations": [
            {
                "observation_id": "summary-body",
                "commitment_ids": ["workspace-summary"],
                "locator": "README.md 正文",
                "value_encoding": "UTF-8 Markdown",
            }
        ],
    },
    "reference_impl": (
        "from pathlib import Path\n"
        "import acme_lib\n"
        "class UserInputError(ValueError):\n"
        "    pass\n"
        "def build_workspace(input_path: Path, output_dir: Path) -> None:\n"
        "    output_dir.mkdir()\n"
        "    (output_dir / 'README.md').write_text(acme_lib.summarize(input_path), encoding='utf-8')\n"
    ),
    "example_suggestions": [],
}


def _doc() -> dict:
    return copy.deepcopy(_WORKSPACE_DOC)


def _with_output(kind: str, format_id: str) -> dict:
    doc = _doc()
    doc["delivery_requirements"]["outputs"][0].update({"kind": kind, "format_id": format_id})
    return doc


def test_workspace_format_with_text_kind_is_a_named_projection_error() -> None:
    with pytest.raises(DraftProjectionError) as caught:
        normalize_draft_document(_with_output("text_artifact", "workspace_bundle"), capability_goal=_GOAL)
    assert not isinstance(caught.value, DeliveryAdmissionError)
    assert str(caught.value) == "tool-draft:DELIVERY_SHAPE_SELF_CONTRADICTION"
    rows = public_validation_diagnostics(caught.value)
    assert rows and rows[0]["loc"] == "delivery_requirements.outputs.0.kind"
    assert "directory" in rows[0]["msg"] and "workspace_bundle" in rows[0]["msg"]


def test_workspace_members_with_cli_shape_is_the_same_named_projection_error() -> None:
    with pytest.raises(DraftProjectionError) as caught:
        normalize_draft_document(_with_output("text_artifact", "markdown_report"), capability_goal=_GOAL)
    assert str(caught.value) == "tool-draft:DELIVERY_SHAPE_SELF_CONTRADICTION"
    rows = public_validation_diagnostics(caught.value)
    assert rows[0]["loc"] == "delivery_requirements.outputs.0.kind"
    assert "workspace_contract" in rows[0]["msg"] or "fixture_builder" in rows[0]["msg"]


def test_consistent_workspace_document_still_compiles() -> None:
    drafted = normalize_draft_document(_doc(), capability_goal=_GOAL)
    assert drafted["workspace_contract"] is not None


def test_genuine_cli_document_is_not_touched() -> None:
    doc = _with_output("text_artifact", "markdown_report")
    doc["workspace_contract"] = None
    doc["fixture_builder"] = None
    doc["fixture_blueprints"] = []
    doc["output_required_fields"] = []
    doc["reference_impl"] = (
        "import acme_lib\n"
        "class UserInputError(ValueError):\n"
        "    pass\n"
        "def extract(path):\n"
        "    return {'title': acme_lib.title(path)}\n"
    )
    try:
        normalize_draft_document(doc, capability_goal="生成匿名单文件报告")
    except DraftError as exc:  # any other shape complaint is fine; the contradiction code is not
        assert "DELIVERY_SHAPE_SELF_CONTRADICTION" not in str(exc)
