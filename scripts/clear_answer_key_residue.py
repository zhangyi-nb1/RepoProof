#!/usr/bin/env python3
"""Move reachable answer-key residue out of the scan roots, before a batch.

This is the operator-side half of the H9-a gate's own remediation ("清掉或移出
本机后再开跑"), automated with the harness's own detector so there is no second
ruler: whatever ``reachable_answer_keys`` reports is exactly what gets moved.

Why it is needed at all: an agent that writes a CORRECT tool and then tests it
into a scratch directory emits bytes identical to the protected expected
fixtures, so a successful run blocks every later run on the same host.  That is
a mechanism defect (recorded as incident-agent-self-test-output-trips-residue-
gate-*), but it is not yet authorised for a mechanism change, so the operator
applies the sanctioned remediation instead of the harness silently ignoring it.

Nothing is deleted: each tree is moved under ~/.repoproof/quarantine/ with a
timestamp, outside the scan roots, so the bytes survive for inspection.
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from repoproof.runner.host_guided import reachable_answer_keys  # noqa: E402

QUARANTINE = Path.home() / ".repoproof" / "quarantine"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True, help="frozen task package directory")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    blind: list[str] = []
    residue = reachable_answer_keys(args.task_dir, blind=blind)
    if blind:
        print(f"scan blind spots (cannot certify a clean host): {blind[:5]}", file=sys.stderr)
        return 3
    if not residue:
        print("no reachable answer-key residue")
        return 0

    # Move whole trees, not single files: half a moved directory is still a hit.
    roots = sorted({_scratch_root(Path(path)) for path in residue})
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = QUARANTINE / f"answer-key-residue-{stamp}"
    print(f"residue files: {len(residue)}; trees: {[str(r) for r in roots]}")
    if args.dry_run:
        return 0
    destination.mkdir(parents=True, exist_ok=True)
    for root in roots:
        if not root.exists():
            continue
        target = destination / root.name
        shutil.move(str(root), str(target))
        print(f"moved {root} -> {target}")
    remaining = reachable_answer_keys(args.task_dir, blind=[])
    print(f"residue after move: {len(remaining)}")
    return 0 if not remaining else 3


def _scratch_root(path: Path) -> Path:
    """The outermost directory under /tmp (or another scan root) to move."""

    parts = path.resolve().parts
    for anchor in ("/private/tmp", "/tmp"):
        anchor_parts = Path(anchor).parts
        if parts[: len(anchor_parts)] == anchor_parts and len(parts) > len(anchor_parts):
            return Path(*parts[: len(anchor_parts) + 1])
    return path.parent


if __name__ == "__main__":
    raise SystemExit(main())
