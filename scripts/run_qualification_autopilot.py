"""Drive one qualification protocol through the journey autopilot, case by case.

Phase 1 (``--phase 1``): every case runs ``tool autopilot --until rehearsal``
(N0-type cases with ``kind: expected_rejection`` run with
``--expect-admission-rejection``).  No Agent is invoked in phase 1, so all
wheelhouses are frozen before the protocol is frozen.  Phase 2 resumes each
case from its phase-1 task id (``--resume-task-id``) through the real build,
fresh audit and registry recomputation.

Every autopilot report lands append-only under
``runs/<planning-dir>/<case_id>/`` next to a batch log line.  The driver never
edits contracts, runs, ledgers or the protocol; it only sequences the CLI.
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]


def _run(argv: list[str]) -> dict:
    process = subprocess.run(
        [sys.executable, "-m", "repoproof.cli", *argv],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=6 * 3600,
        check=False,
    )
    out = process.stdout
    start, end = out.find("{"), out.rfind("}")
    if start < 0 or end < start:
        return {"ok": False, "status": "CLI_PAYLOAD_MISSING", "stderr_tail": process.stderr[-800:]}
    return json.loads(out[start : end + 1])



def _latest_phase1_report(record_dir: Path) -> Path:
    """Newest phase-1 report: attempt-N/ (highest N) wins over the first attempt at top level."""

    candidates = [record_dir / "autopilot-report.json"]
    def _attempt_number(item: Path) -> int:
        suffix = item.name.split("-")[-1]
        return int(suffix) if suffix.isdigit() else 0

    for child in sorted(record_dir.glob("attempt-*"), key=_attempt_number):
        candidates.append(child / "autopilot-report.json")
    existing = [path for path in candidates if path.is_file()]
    return existing[-1] if existing else candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--planning-dir", type=Path, required=True)
    parser.add_argument("--phase", type=int, choices=[1, 2], required=True)
    parser.add_argument("--cases", default="", help="comma-separated case ids; default all")
    parser.add_argument("--batch", default="EXPLORATORY_UNPREREGISTERED")
    parser.add_argument("--dest-root", type=Path, default=Path("~/tools").expanduser())
    args = parser.parse_args()

    protocol = yaml.safe_load(args.protocol.read_text(encoding="utf-8"))
    wanted = {item.strip() for item in args.cases.split(",") if item.strip()}
    log_path = args.planning_dir / f"batch-phase{args.phase}.log.jsonl"
    args.planning_dir.mkdir(parents=True, exist_ok=True)
    exit_code = 0
    for case in protocol["cases"]:
        case_id = str(case["case_id"])
        if wanted and case_id not in wanted:
            continue
        case_dir = args.planning_dir / case_id
        record_dir = case_dir
        if args.phase == 1 and (case_dir / "autopilot-report.json").is_file():
            # Append-only: a phase-1 re-run never overwrites an earlier attempt's report.
            attempt = 2
            while (case_dir / f"attempt-{attempt}").exists():
                attempt += 1
            record_dir = case_dir / f"attempt-{attempt}"
        elif args.phase == 2:
            # Phase 2 gets its own append-only directory; the phase-1 reports stay untouched.
            attempt = 1
            while (case_dir / f"phase2-attempt-{attempt}").exists():
                attempt += 1
            record_dir = case_dir / f"phase2-attempt-{attempt}"
        started = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
        if args.phase == 1:
            argv = [
                "tool",
                "autopilot",
                "--repo",
                str(case["repository"]),
                "--capability",
                str(case["initial_user_request"]),
                "--until",
                "rehearsal",
                "--batch",
                args.batch,
                "--dest-root",
                str(args.dest_root),
                "--record-dir",
                str(record_dir),
            ]
            if case.get("revision"):
                argv += ["--revision", str(case["revision"])]
            if case.get("kind") == "expected_rejection":
                argv.append("--expect-admission-rejection")
        else:
            previous = _latest_phase1_report(case_dir)
            if not previous.is_file():
                row = {
                    "case_id": case_id,
                    "phase": 2,
                    "ok": False,
                    "status": "PHASE1_REPORT_MISSING",
                    "started_at": started,
                }
                log_path.open("a", encoding="utf-8").write(json.dumps(row, ensure_ascii=False) + "\n")
                exit_code = 3
                continue
            report = json.loads(previous.read_text(encoding="utf-8"))
            if report.get("final_status") == "EXPECTED_REJECTION":
                continue
            if not report.get("task_id"):
                row = {
                    "case_id": case_id,
                    "phase": 2,
                    "ok": False,
                    "status": "PHASE1_NOT_REHEARSED",
                    "started_at": started,
                }
                log_path.open("a", encoding="utf-8").write(json.dumps(row, ensure_ascii=False) + "\n")
                exit_code = 3
                continue
            record_dir.mkdir(parents=True, exist_ok=True)
            (record_dir / "phase1-autopilot-report.json").write_bytes(previous.read_bytes())
            argv = [
                "tool",
                "autopilot",
                "--repo",
                str(case["repository"]),
                "--capability",
                str(case["initial_user_request"]),
                "--resume-task-id",
                str(report["task_id"]),
                "--resume-tool-name",
                str(report.get("tool_name") or ""),
                "--batch",
                args.batch,
                "--dest-root",
                str(args.dest_root),
                "--record-dir",
                str(record_dir),
            ]
        outcome = _run(argv)
        row = {
            "case_id": case_id,
            "phase": args.phase,
            "ok": bool(outcome.get("ok")),
            "status": outcome.get("status"),
            "started_at": started,
            "finished_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "stop_stage": (outcome.get("report") or {}).get("stop_stage"),
            "stop_reason_codes": (outcome.get("report") or {}).get("stop_reason_codes"),
            "task_id": (outcome.get("report") or {}).get("task_id"),
        }
        log_path.open("a", encoding="utf-8").write(json.dumps(row, ensure_ascii=False) + "\n")
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if not row["ok"]:
            exit_code = 3
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
