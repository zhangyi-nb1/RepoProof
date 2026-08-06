import json
from pathlib import Path

from repoproof.harness.trace import TraceWriter, verify_chain


def _write_three(path: Path) -> None:
    tw = TraceWriter(path)
    tw.append("run.start", actor="runner", payload={"run_id": "t"})
    tw.append("action.end", actor="runner", payload={"exit_code": 0})
    tw.append("run.end", actor="runner")


def test_chain_verifies(tmp_path: Path) -> None:
    p = tmp_path / "trace.jsonl"
    _write_three(p)
    ok, n, err = verify_chain(p)
    assert ok and n == 3, err


def test_in_place_edit_detected(tmp_path: Path) -> None:
    p = tmp_path / "trace.jsonl"
    _write_three(p)
    lines = p.read_text().splitlines()
    row = json.loads(lines[1])
    row["payload"]["exit_code"] = 1  # falsify history
    lines[1] = json.dumps(row, ensure_ascii=False, sort_keys=True)
    p.write_text("\n".join(lines) + "\n")
    ok, at, err = verify_chain(p)
    assert not ok and at == 2 and "chain broken" in err


def test_deleted_line_detected(tmp_path: Path) -> None:
    p = tmp_path / "trace.jsonl"
    _write_three(p)
    lines = p.read_text().splitlines()
    p.write_text("\n".join([lines[0], lines[2]]) + "\n")
    ok, at, _ = verify_chain(p)
    assert not ok and at == 1


def test_append_resume_keeps_chain(tmp_path: Path) -> None:
    p = tmp_path / "trace.jsonl"
    _write_three(p)
    TraceWriter(p).append("late.event", actor="runner")
    ok, n, err = verify_chain(p)
    assert ok and n == 4, err
