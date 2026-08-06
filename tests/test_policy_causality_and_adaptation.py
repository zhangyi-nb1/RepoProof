"""Action-id causality rules + adaptation freezing/patch budgets."""

from pathlib import Path

import pytest

from repoproof.domain.models import Budgets
from repoproof.harness.adaptation import (
    PatchBudgetExceeded,
    freeze_adaptation,
    inventory,
    verify_frozen,
)
from repoproof.harness.policy import evaluate_argv
from repoproof.harness.trace import TraceWriter
from repoproof.verification.verifiers import check_action_causality


def _trace(tmp_path: Path) -> tuple[TraceWriter, Path]:
    p = tmp_path / "trace.jsonl"
    return TraceWriter(p), p


def _decision(tw: TraceWriter, aid: str, allowed: bool) -> None:
    tw.append("policy.decision", actor="harness", payload={"action_id": aid, "allowed": allowed})


def _start(tw: TraceWriter, aid: str) -> None:
    tw.append("action.start", actor="runner", payload={"action_id": aid})


def _end(tw: TraceWriter, aid: str) -> None:
    tw.append("action.end", actor="runner", payload={"action_id": aid, "exit_code": 0})


def test_wellformed_causality_passes(tmp_path: Path) -> None:
    tw, p = _trace(tmp_path)
    for aid in ("a1", "a2"):
        _decision(tw, aid, True)
        _start(tw, aid)
        _end(tw, aid)
    assert check_action_causality(p) == []


def test_start_without_allow_fails(tmp_path: Path) -> None:
    tw, p = _trace(tmp_path)
    _start(tw, "a1")
    _end(tw, "a1")
    problems = check_action_causality(p)
    assert any("expected exactly 1 ALLOW" in x for x in problems)


def test_denied_action_must_never_execute(tmp_path: Path) -> None:
    tw, p = _trace(tmp_path)
    _decision(tw, "a1", False)
    _start(tw, "a1")
    problems = check_action_causality(p)
    assert any("DENIED action has start/end" in x for x in problems)


def test_duplicate_start_and_wrong_order_fail(tmp_path: Path) -> None:
    tw, p = _trace(tmp_path)
    _decision(tw, "a1", True)
    _start(tw, "a1")
    _start(tw, "a1")
    problems = check_action_causality(p)
    assert any("duplicate starts" in x for x in problems)

    tw2, p2 = _trace(tmp_path / "sub")
    _start(tw2, "b1")  # start BEFORE its allow
    _decision(tw2, "b1", True)
    _end(tw2, "b1")
    problems2 = check_action_causality(p2)
    assert any("not earlier than start" in x for x in problems2)


def test_agent_never_inherits_shell_latitude() -> None:
    setup = evaluate_argv(["sh", "-c", "cp -r /a /b"], actor_kind="harness_setup")
    agent = evaluate_argv(["sh", "-c", "cp -r /a /b"], actor_kind="agent")
    assert setup.allowed and not agent.allowed
    assert any("agent_shell_string_forbidden" in r for r in agent.reasons)


# ---------------- adaptation freeze + patch budgets ----------------


def test_freeze_empty_zone_not_present(tmp_path: Path) -> None:
    zone = tmp_path / "adaptation"
    zone.mkdir()
    manifest = freeze_adaptation(zone, Budgets())
    assert manifest.frozen and manifest.total_files == 0 and not manifest.present


def test_max_patch_files_enforced(tmp_path: Path) -> None:
    zone = tmp_path / "adaptation"
    zone.mkdir()
    for i in range(9):  # budget default = 8
        (zone / f"f{i}.py").write_text("x = 1\n")
    with pytest.raises(PatchBudgetExceeded, match="max_patch_files"):
        freeze_adaptation(zone, Budgets())


def test_max_patch_lines_enforced(tmp_path: Path) -> None:
    zone = tmp_path / "adaptation"
    zone.mkdir()
    (zone / "big.py").write_text("\n".join(f"line{i}" for i in range(401)))
    with pytest.raises(PatchBudgetExceeded, match="max_patch_lines"):
        freeze_adaptation(zone, Budgets())


def test_frozen_zone_is_read_only_and_recheck_detects_change(tmp_path: Path) -> None:
    zone = tmp_path / "adaptation"
    zone.mkdir()
    target = zone / "adapter.py"
    target.write_text("def f():\n    return 1\n")
    manifest = freeze_adaptation(zone, Budgets())
    assert manifest.present and manifest.total_files == 1
    with pytest.raises(PermissionError):
        target.write_text("tampered")
    ok, _ = verify_frozen(zone, manifest)
    assert ok
    # force a change past the chmod, as root-level tampering would
    target.chmod(0o644)
    target.write_text("tampered\n")
    ok2, detail = verify_frozen(zone, manifest)
    assert not ok2 and "adaptation tree changed" in detail


def test_inventory_rejects_symlinks(tmp_path: Path) -> None:
    zone = tmp_path / "adaptation"
    zone.mkdir()
    (zone / "leak.py").symlink_to("/etc/hosts")
    with pytest.raises(PatchBudgetExceeded, match="symlink"):
        inventory(zone)
