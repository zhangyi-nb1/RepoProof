"""T4 事务栈操作 CLI(feature_stack 的实验驱动面;全部操作可审计)。

默认栈/台账位置指向 RepoProofBench;实验在副本上跑时用 --stack/--ledger
显式改道。selective-rebuild 的全量验证经 --verify-cmd 外接(拿 scratch
路径作最后一个参数,exit 0 = 通过)。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

RP = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(RP / "src"))

from repoproof.adoption.delivery.feature_stack import (  # noqa: E402
    FeatureBundle,
    FeatureStack,
)

DEFAULT_STACK = Path.home() / "RepoProofBench/offerclaw-transaction-stack"
DEFAULT_LEDGER = Path.home() / "RepoProofBench/offerclaw-transaction-stack-ledger"


def _stack(args) -> FeatureStack:
    return FeatureStack.load(args.stack, args.ledger)


def cmd_init(args) -> int:
    st = FeatureStack.init(args.stack, args.ledger)
    print(json.dumps({"host_commit": st.ledger.host_commit,
                      "S0_tree": st.ledger.states[0].tree_sha}, indent=2))
    return 0


def cmd_status(args) -> int:
    st = _stack(args)
    led = st.ledger
    print(json.dumps({
        "active_state": led.active_state,
        "current_tree": st.tree_sha(),
        "recorded_tree": next(s.tree_sha for s in led.states
                              if s.state_id == led.active_state),
        "applied": [{ "tx": t, "feature": led.transactions[t].feature_id,
                      "requires": led.transactions[t].requires_features}
                    for t in led.applied_order],
        "states": [{"id": s.state_id, "tree": s.tree_sha[:12]} for s in led.states],
    }, indent=2, ensure_ascii=False))
    return 0


def cmd_apply(args) -> int:
    st = _stack(args)
    bundle = FeatureBundle.load(args.bundle)
    requires = args.requires.split(",") if args.requires else None
    tx = st.apply_feature(bundle, requires_features=requires)
    print(json.dumps({"transaction": tx.transaction_id,
                      "state": tx.result_state_id,
                      "tree": tx.result_tree_sha}, indent=2))
    return 0


def cmd_rollback_top(args) -> int:
    st = _stack(args)
    tx = st.rollback_top(expect_feature_id=args.expect or None)
    print(json.dumps({"rolled_back": tx.transaction_id,
                      "restored_state": tx.parent_state_id,
                      "tree": tx.parent_tree_sha,
                      "rollback_verified": tx.rollback_verified}, indent=2))
    return 0


def cmd_plan(args) -> int:
    st = _stack(args)
    print(json.dumps(st.removal_plan(args.feature), indent=2, ensure_ascii=False))
    return 0


def cmd_cascade(args) -> int:
    st = _stack(args)
    confirmed = args.confirm.split(",") if args.confirm else None
    plan = st.cascade_remove(args.feature, confirmed_features=confirmed)
    print(json.dumps({"executed": plan["cascade_order"],
                      "active_state": st.ledger.active_state}, indent=2))
    return 0


def cmd_rebuild(args) -> int:
    st = _stack(args)
    bundles = {}
    for d in args.bundles.split(","):
        b = FeatureBundle.load(d)
        bundles[b.feature_id] = b

    def verify(root: Path) -> bool:
        proc = subprocess.run([*args.verify_cmd.split(), str(root)])
        return proc.returncode == 0

    out = st.selective_rebuild(args.feature, bundles=bundles,
                               verify_fn=verify, scratch_dir=args.scratch)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_recover(args) -> int:
    st = _stack(args)
    print(json.dumps(st.recover_interrupted(), indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stack", type=Path, default=DEFAULT_STACK)
    ap.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    p = sub.add_parser("apply")
    p.add_argument("bundle")
    p.add_argument("--requires", default="")
    p.set_defaults(fn=cmd_apply)
    p = sub.add_parser("rollback-top")
    p.add_argument("--expect", default="")
    p.set_defaults(fn=cmd_rollback_top)
    p = sub.add_parser("plan")
    p.add_argument("feature")
    p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("cascade")
    p.add_argument("feature")
    p.add_argument("--confirm", default="")
    p.set_defaults(fn=cmd_cascade)
    p = sub.add_parser("rebuild")
    p.add_argument("feature")
    p.add_argument("--bundles", required=True)
    p.add_argument("--scratch", required=True)
    p.add_argument("--verify-cmd", required=True)
    p.set_defaults(fn=cmd_rebuild)
    sub.add_parser("recover").set_defaults(fn=cmd_recover)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
