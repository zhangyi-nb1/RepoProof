"""自检的第四个修复位:合同结构表示(incident-selfcheck-contract-defect-misrouted-*)。

不变量:WORKSPACE_REFERENCE_CONTRACT_FAILED 且诊断为合同结构码(规则重叠、
限额)时,修的是 draft.yaml 里的 workspace_contract 表示——角色集合、交付
需求、承诺一个不变;角色被增删即回滚;修复上下文带当前合同与公开结构诊断。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml

from repoproof.adoption.intake.draft_selfcheck import read_draft_self_check
from repoproof.ui.services import product_jobs

_spec = importlib.util.spec_from_file_location(
    "_selfcheck_fixtures", Path(__file__).with_name("test_draft_selfcheck_service.py")
)
_fixtures = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_fixtures)

_CONTRACT = {
    "schema_version": 1,
    "rules": [
        {
            "path_pattern": "README.md",
            "role": "guide",
            "media_type": "text/markdown",
            "validation_profile": "text_utf8_v1",
        },
        {
            "path_pattern": "site/**/*.html",
            "role": "pages",
            "media_type": "text/html",
            "validation_profile": "html_v1",
            "max_count": 64,
        },
    ],
    "require_offline_wheelhouse": False,
    "limits": {
        "max_files": 64,
        "max_total_bytes": 1_000_000,
        "max_file_bytes": 200_000,
        "max_depth": 3,
        "max_path_bytes": 160,
    },
}


def _draft_with_contract(tmp_path: Path, monkeypatch) -> Path:
    draft_dir = _fixtures._draft(tmp_path, monkeypatch)
    doc = yaml.safe_load((draft_dir / "draft.yaml").read_text(encoding="utf-8"))
    doc["tool"]["workspace_contract"] = json.loads(json.dumps(_CONTRACT))
    (draft_dir / "draft.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return draft_dir


class _ContractDrafter:
    name = "scripted-drafter"

    def __init__(self, repaired: dict):
        self.calls: list[tuple[str, dict]] = []
        self._repaired = repaired

    def repair_workspace_contract(self, context):
        self.calls.append(("contract", context))
        return {"workspace_contract": json.loads(json.dumps(self._repaired))}

    def repair_workspace_reference(self, context):
        # On a repeated structural failure the loop alternates to the producer;
        # this drafter has nothing to offer there, so the attempt rolls back.
        from repoproof.adoption.intake.tool_drafter import DraftError

        raise DraftError("workspace-reference-repair:NO_PRODUCER_CHANGE_IN_THIS_TEST")


def test_structural_defect_repairs_contract_representation_and_preserves_roles(tmp_path: Path, monkeypatch) -> None:
    draft_dir = _draft_with_contract(tmp_path, monkeypatch)
    calls = _fixtures._scripted_candidates(
        monkeypatch,
        [
            {
                "ok": False,
                "reason_codes": ["WORKSPACE_REFERENCE_CONTRACT_FAILED"],
                "diagnostics": ["WORKSPACE_PATH_TOO_DEEP"],
                "failure_owner": "CONTRACT",
            },
            {"ok": True, "candidates": [{}, {}, {}]},
        ],
    )
    repaired = json.loads(json.dumps(_CONTRACT))
    repaired["limits"]["max_depth"] = 6
    drafter = _ContractDrafter(repaired)
    before_reference = (draft_dir / "reference_impl.py").read_bytes()

    result = product_jobs.run_draft_self_check(draft_dir, repair=True, drafter=drafter)

    assert result["ok"] is True and len(calls) == 2
    assert [name for name, _ in drafter.calls] == ["contract"]
    context = drafter.calls[0][1]
    assert context["current_workspace_contract"]["limits"]["max_depth"] == 3
    assert "WORKSPACE_PATH_TOO_DEEP" in context["self_check_failure"]["diagnostics"]
    assert context["preserved_roles"] == ["guide", "pages"]
    doc = yaml.safe_load((draft_dir / "draft.yaml").read_text(encoding="utf-8"))
    assert doc["tool"]["workspace_contract"]["limits"]["max_depth"] == 6
    assert [r["role"] for r in doc["tool"]["workspace_contract"]["rules"]] == ["guide", "pages"]
    assert (draft_dir / "reference_impl.py").read_bytes() == before_reference
    report = read_draft_self_check(draft_dir)
    assert report is not None and report.ok is True
    assert report.rounds[0].repair is not None and report.rounds[0].repair.target == "contract"
    assert report.rounds[0].repair.outcome == "APPLIED"
    assert report.bound.semantics_sha256 is not None
    assert not (draft_dir / product_jobs._CONTROL_REPAIR_MARKER).exists()


def test_contract_repair_that_changes_roles_is_rolled_back(tmp_path: Path, monkeypatch) -> None:
    draft_dir = _draft_with_contract(tmp_path, monkeypatch)
    failure = {
        "ok": False,
        "reason_codes": ["WORKSPACE_REFERENCE_CONTRACT_FAILED"],
        "diagnostics": ["WORKSPACE_RULE_OVERLAP"],
        "failure_owner": "CONTRACT",
    }
    _fixtures._scripted_candidates(monkeypatch, [failure, failure])
    repaired = json.loads(json.dumps(_CONTRACT))
    repaired["rules"] = repaired["rules"][:1]
    drafter = _ContractDrafter(repaired)
    before = (draft_dir / "draft.yaml").read_bytes()

    result = product_jobs.run_draft_self_check(draft_dir, repair=True, max_repair_rounds=1, drafter=drafter)

    assert result["ok"] is False
    assert (draft_dir / "draft.yaml").read_bytes() == before
    report = read_draft_self_check(draft_dir)
    assert report is not None and report.rounds[0].repair is not None
    assert report.rounds[0].repair.target == "contract" and report.rounds[0].repair.outcome == "ROLLED_BACK"
    assert not (draft_dir / product_jobs._CONTROL_REPAIR_MARKER).exists()
