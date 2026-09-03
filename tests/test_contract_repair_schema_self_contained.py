"""合同结构修复的结构化输出 schema 必须自包含(incident-structured-schema-dangling-defs-mkdocs-v1)。"""

from __future__ import annotations

import jsonschema

from repoproof.adoption.intake.tool_drafter import (
    _WORKSPACE_CONTRACT_REPAIR_SCHEMA,
    strict_structured_output_schema,
)


def _refs(node, acc: list[str]) -> list[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref":
                acc.append(str(value))
            _refs(value, acc)
    elif isinstance(node, list):
        for item in node:
            _refs(item, acc)
    return acc


def test_repair_schema_resolves_every_ref_locally() -> None:
    strict = strict_structured_output_schema(_WORKSPACE_CONTRACT_REPAIR_SCHEMA)
    defs = strict.get("$defs") or {}
    for ref in _refs(strict, []):
        assert ref.startswith("#/$defs/") and ref.split("/")[-1] in defs, ref
    jsonschema.Draft202012Validator.check_schema(strict)
    instance = {
        "workspace_contract": {
            "schema_version": 1,
            "rules": [
                {
                    "path_pattern": "README.md",
                    "role": "guide",
                    "media_type": "text/markdown",
                    "validation_profile": "text_utf8_v1",
                    "min_count": 1,
                    "max_count": 1,
                    "executable": False,
                }
            ],
            "allow_extra_files": False,
            "entrypoints": [],
            "runnable": False,
            "smoke_command": [],
            "smoke_timeout_seconds": 5,
            "require_offline_wheelhouse": False,
            "runtime_python_entrypoint": None,
            "directory_profiles": [],
            "limits": {
                "max_files": 8,
                "max_total_bytes": 4096,
                "max_file_bytes": 2048,
                "max_depth": 3,
                "max_path_bytes": 120,
            },
        }
    }
    jsonschema.Draft202012Validator(strict).validate(instance)
