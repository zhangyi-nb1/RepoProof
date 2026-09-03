"""参考实现的运行时归属筛查:一把尺、只认路径、点名字面量(incident-reference-ownership-policy-second-ruler-*)。

现象:两个仓库(账单域 'vendor' 列名、对账域 'vendor' 列名)上,reference 修复每次都被
`WORKSPACE_REFERENCE_RUNTIME_OWNERSHIP_VIOLATION` 回滚且无诊断——修复路径独有的静态筛查把裸目录名
`vendor` 当保留字,而起草路径从不跑这道筛查;真正的保护是密封期的 `WORKSPACE_RUNTIME_OWNED_PATH_COLLISION`。

不变量:
  I1 只有带路径形态的字面量才被筛(`run.sh`、`requirements.lock.txt`、`THIRD_PARTY_NOTICES.md`、
     `vendor/...`);裸的域词 `vendor` 不算;
  I2 命中时给出诊断行(字面量 + 行号),修复被拒时这些行进 DraftError.diagnostics;
  I3 起草路径与修复路径跑同一把尺:起草时同样的字面量同样被拒(带 loc `reference_impl`),
     同样的裸 `vendor` 同样放行。
"""

from __future__ import annotations

import copy

import pytest
from test_delivery_shape_contradiction import _GOAL, _WORKSPACE_DOC

from repoproof.adoption.intake.tool_drafter import (
    DraftProjectionError,
    normalize_draft_document,
    public_validation_diagnostics,
    workspace_reference_runtime_ownership_diagnostics,
    workspace_reference_runtime_ownership_policy_errors,
)

_CLOSURE = {"require_offline_wheelhouse": True}

_DOMAIN_WORD = (
    "from pathlib import Path\n"
    "import acme_lib\n"
    "class UserInputError(ValueError):\n"
    "    pass\n"
    "def build_workspace(input_path: Path, output_dir: Path) -> None:\n"
    "    output_dir.mkdir()\n"
    "    rows = acme_lib.rows(input_path)\n"
    "    (output_dir / 'app.py').write_text('print(1)\\n', encoding='utf-8')\n"
    "    (output_dir / 'README.md').write_text(', '.join(r['vendor'] for r in rows), encoding='utf-8')\n"
)

_OWNED_PATH = _DOMAIN_WORD + "    (output_dir / 'vendor/wheels/x.whl').write_bytes(b'PK')\n"
_LAUNCHER = _DOMAIN_WORD + "    (output_dir / 'run.sh').write_text('#!/bin/sh\\n', encoding='utf-8')\n"


def test_bare_domain_word_is_not_a_reserved_path() -> None:
    assert workspace_reference_runtime_ownership_policy_errors(_DOMAIN_WORD, _CLOSURE) == []
    assert workspace_reference_runtime_ownership_diagnostics(_DOMAIN_WORD, _CLOSURE) == []


@pytest.mark.parametrize("source, literal", [(_OWNED_PATH, "vendor/wheels/x.whl"), (_LAUNCHER, "run.sh")])
def test_owned_path_literals_are_named_with_their_line(source: str, literal: str) -> None:
    assert workspace_reference_runtime_ownership_policy_errors(source, _CLOSURE) == [
        "WORKSPACE_REFERENCE_RUNTIME_OWNERSHIP_VIOLATION"
    ]
    rows = workspace_reference_runtime_ownership_diagnostics(source, _CLOSURE)
    assert rows and literal in rows[0]["msg"] and rows[0]["loc"].startswith("reference_impl")


def test_bare_directory_name_used_as_a_path_segment_is_still_reserved() -> None:
    segment = _DOMAIN_WORD + "    (output_dir / 'vendor' / 'wheels').mkdir(parents=True)\n"
    rows = workspace_reference_runtime_ownership_diagnostics(segment, _CLOSURE)
    assert rows and "'vendor'" in rows[0]["msg"]
    assert workspace_reference_runtime_ownership_policy_errors(segment, _CLOSURE) == [
        "WORKSPACE_REFERENCE_RUNTIME_OWNERSHIP_VIOLATION"
    ]


def _runnable_doc(reference: str) -> dict:
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
    contract.update(
        {
            "runnable": True,
            "entrypoints": ["run.sh"],
            "smoke_command": ["./run.sh"],
            "require_offline_wheelhouse": True,
            "runtime_python_entrypoint": "app.py",
        }
    )
    doc["reference_impl"] = reference
    return doc


def test_drafting_path_runs_the_same_ruler() -> None:
    drafted = normalize_draft_document(_runnable_doc(_DOMAIN_WORD), capability_goal=_GOAL)
    assert drafted["reference_impl"]
    with pytest.raises(DraftProjectionError) as caught:
        normalize_draft_document(_runnable_doc(_LAUNCHER), capability_goal=_GOAL)
    assert "WORKSPACE_REFERENCE_RUNTIME_OWNERSHIP_VIOLATION" in str(caught.value)
    rows = public_validation_diagnostics(caught.value)
    assert rows and rows[0]["loc"].startswith("reference_impl") and "run.sh" in rows[0]["msg"]
