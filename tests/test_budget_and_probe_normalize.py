import pytest

from repoproof.domain.models import Budgets
from repoproof.harness.budget import BudgetExceeded, BudgetMeter
from repoproof.runner.baseline import _normalize_probe


def test_step_budget_enforced() -> None:
    meter = BudgetMeter(Budgets(max_agent_steps=2))
    meter.note_step("a")
    meter.note_step("b")
    with pytest.raises(BudgetExceeded):
        meter.note_step("c")


def test_command_timeout_derived_from_contract() -> None:
    meter = BudgetMeter(Budgets(max_command_minutes=5))
    assert meter.command_timeout_seconds == 300


def test_probe_normalization_strips_uuid4_only() -> None:
    payload = {
        "id": "9f1c2d3e-aaaa-4bbb-8ccc-121212121212",
        "text": "stable",
        "nested": [{"id": "x", "value": "b3b0c44e-1111-4222-9333-444444444444"}],
    }
    norm = _normalize_probe(payload)
    assert "id" not in norm
    assert norm["text"] == "stable"
    assert "id" not in norm["nested"][0]
    assert norm["nested"][0]["value"] == "<uuid4-stripped>"
