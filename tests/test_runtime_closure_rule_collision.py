"""Core 拥有的 runtime 闭包路径不许被模型规则重复声明
(incident-selfcheck-contract-defect-misrouted-xlsx-v1)。

不变量:`_compile_workspace_runtime_closure` 之后,每个 runtime-owned 代表路径
(run.sh / requirements.lock.txt / THIRD_PARTY_NOTICES.md / vendor/wheels/*.whl)
恰好被一条规则匹配,且是 Core 的定义——模型写的同名或覆盖它们的通配规则是
表示噪声,编译时归一,不能留到候选生成阶段变成 WORKSPACE_RULE_OVERLAP。
"""

from __future__ import annotations

from repoproof.adoption.intake.tool_drafter import _compile_workspace_runtime_closure
from repoproof.execution.workspace_bundle import workspace_path_matches

_REPRESENTATIVES = (
    "run.sh",
    "requirements.lock.txt",
    "THIRD_PARTY_NOTICES.md",
    "vendor/wheels/demo-1.0-py3-none-any.whl",
)


def _model_contract() -> dict:
    return {
        "schema_version": 1,
        "runnable": True,
        "runtime_python_entrypoint": "app.py",
        "rules": [
            {
                "path_pattern": "app.py",
                "role": "application",
                "media_type": "text/x-python",
                "validation_profile": "python_compile_v1",
            },
            {
                "path_pattern": "report.xlsx",
                "role": "workbook",
                "media_type": "application/vnd.ms-excel",
                "validation_profile": "xlsx_v1",
            },
            {
                "path_pattern": "vendor/wheels/*",
                "role": "wheels",
                "media_type": "application/zip",
                "validation_profile": "wheel_v1",
                "max_count": 64,
            },
            {
                "path_pattern": "run.sh",
                "role": "launcher",
                "media_type": "text/plain",
                "validation_profile": "text_utf8_v1",
                "executable": False,
            },
        ],
        "limits": {
            "max_files": 10,
            "max_total_bytes": 1000,
            "max_file_bytes": 500,
            "max_depth": 2,
            "max_path_bytes": 80,
        },
    }


def test_runtime_owned_paths_match_exactly_one_core_rule() -> None:
    compiled = _compile_workspace_runtime_closure(_model_contract())
    rules = compiled["rules"]
    for representative in _REPRESENTATIVES:
        matching = [rule for rule in rules if workspace_path_matches(str(rule["path_pattern"]), representative)]
        assert len(matching) == 1, (representative, [r["path_pattern"] for r in matching])
    launcher = next(rule for rule in rules if rule["path_pattern"] == "run.sh")
    assert launcher["executable"] is True and launcher["validation_profile"] == "shell_v1"
    wheels = next(rule for rule in rules if workspace_path_matches(str(rule["path_pattern"]), _REPRESENTATIVES[3]))
    assert wheels["path_pattern"] == "vendor/wheels/*.whl" and wheels["validation_profile"] == "wheel_v1"


def test_model_domain_rules_survive_normalisation() -> None:
    compiled = _compile_workspace_runtime_closure(_model_contract())
    patterns = [rule["path_pattern"] for rule in compiled["rules"]]
    assert "app.py" in patterns and "report.xlsx" in patterns
