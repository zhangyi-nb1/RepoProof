"""smoke_command 的语义必须先教后杀(incident-smoke-command-semantics-untaught-*)。

现象:c6 `./run.sh` 在密封工作区里因"找不到 input 目录"非零退出;c7 v2 `./run.sh spec.json`
引用了不在工作区里的文件、v3 `./run.sh` 无参仍崩 —— 三个任务版本里模型都把 smoke 当成
"带候选输入跑一遍",而 Harness 是在**只有交付工作区自身**的目录里跑它。提示词从未说过。

不变量:
  I1 起草、reference 修复、合同修复三份提示词都写明:smoke 在交付工作区里单独运行,
     没有候选输入、没有外部文件,必须退出 0;
  I2 投影层把 smoke_command 里指向非合同成员的文件参数当表示层矛盾拒绝,并带字段 loc,
     而不是等到候选生成 / preflight 才用 stderr 说话;
  I3 纯旗标参数(--help)与合同成员路径不受影响。
"""

from __future__ import annotations

import copy

import pytest
from test_delivery_shape_contradiction import _GOAL, _WORKSPACE_DOC

from repoproof.adoption.intake import tool_drafter
from repoproof.adoption.intake.tool_drafter import (
    DraftProjectionError,
    normalize_draft_document,
    public_validation_diagnostics,
)


def _runnable_doc(smoke: list[str]) -> dict:
    doc = copy.deepcopy(_WORKSPACE_DOC)
    contract = doc["workspace_contract"]
    contract["rules"] = [
        {
            "path_pattern": "README.md",
            "role": "human documentation",
            "media_type": "text/markdown",
            "validation_profile": "text_utf8_v1",
        },
        {
            "path_pattern": "app.py",
            "role": "application",
            "media_type": "text/x-python",
            "validation_profile": "python_compile_v1",
        },
    ]
    contract["runnable"] = True
    contract["entrypoints"] = ["run.sh"]
    contract["smoke_command"] = smoke
    contract["require_offline_wheelhouse"] = True
    contract["runtime_python_entrypoint"] = "app.py"
    return doc


@pytest.mark.parametrize(
    "prompt_name",
    ["_SYSTEM", "_WORKSPACE_REFERENCE_REPAIR_SYSTEM", "_WORKSPACE_CONTRACT_REPAIR_SYSTEM"],
)
def test_prompts_state_that_smoke_runs_inside_the_workspace_alone(prompt_name: str) -> None:
    text = getattr(tool_drafter, prompt_name).lower()
    assert "smoke" in text
    assert "alone" in text and "no candidate input" in text, prompt_name
    assert "exit 0" in text, prompt_name


def test_smoke_argument_naming_a_non_member_file_is_a_named_projection_error() -> None:
    with pytest.raises(DraftProjectionError) as caught:
        normalize_draft_document(_runnable_doc(["./run.sh", "spec.json"]), capability_goal=_GOAL)
    assert str(caught.value) == "tool-draft:SMOKE_COMMAND_NON_MEMBER_ARGUMENT"
    rows = public_validation_diagnostics(caught.value)
    assert rows and rows[0]["loc"] == "workspace_contract.smoke_command.1"
    assert "spec.json" in rows[0]["msg"] and "alone" in rows[0]["msg"]


@pytest.mark.parametrize("smoke", [["./run.sh"], ["./run.sh", "--help"], ["./run.sh", "README.md"]])
def test_flags_and_member_paths_compile(smoke: list[str]) -> None:
    drafted = normalize_draft_document(_runnable_doc(smoke), capability_goal=_GOAL)
    assert drafted["workspace_contract"]["smoke_command"][0] == "./run.sh"
