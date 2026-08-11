"""R-E 崩溃实验驱动(只对 /tmp 副本操作;OfferClaw 主目录硬护栏不变)。

子命令:
  crash-apply    <stack> <ledger> <bundle> [--nth N]
      施加中第 N+1 笔写抛 KeyboardInterrupt(BaseException,绕过
      except Exception,与 kill 同构)→ 打印 journal 实况。
  crash-rollback <stack> <ledger> [--nth N]
      回滚相同理。
  slow-apply     <stack> <ledger> <bundle> [--delay S]
      每笔写前 sleep S 秒——供外部 kill -9 命中写回中段。
  try-op         <stack> <ledger> <bundle>
      施加尝试;期望 StackJournalPending 拒绝。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

RP = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(RP / "src"))

import repoproof.adoption.delivery.apply as apply_mod  # noqa: E402
from repoproof.adoption.delivery.feature_stack import (  # noqa: E402
    FeatureBundle,
    FeatureStack,
    StackJournalPending,
)


def _patch_boom(nth: int) -> None:
    real = apply_mod._atomic_write
    count = {"v": 0}

    def wrapper(target, data, **kw):
        count["v"] += 1
        if count["v"] > nth:
            raise KeyboardInterrupt(f"模拟进程死亡(第 {count['v']} 笔写)")
        real(target, data, **kw)

    apply_mod._atomic_write = wrapper


def _patch_slow(delay: float) -> None:
    real = apply_mod._atomic_write

    def wrapper(target, data, **kw):
        time.sleep(delay)
        real(target, data, **kw)

    apply_mod._atomic_write = wrapper


def _journal_state(ledger: Path) -> dict:
    j = ledger / "journal.json"
    if not j.exists():
        return {"journal": None}
    d = json.loads(j.read_text(encoding="utf-8"))
    return {"journal": {"phase": d["phase"], "transaction_id": d["transaction_id"],
                        "parent_tree_sha": d["parent_tree_sha"]}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["crash-apply", "crash-rollback",
                                    "slow-apply", "try-op"])
    ap.add_argument("stack", type=Path)
    ap.add_argument("ledger", type=Path)
    ap.add_argument("bundle", nargs="?", type=Path)
    ap.add_argument("--nth", type=int, default=1)
    ap.add_argument("--delay", type=float, default=0.6)
    args = ap.parse_args()

    st = FeatureStack.load(args.stack, args.ledger)

    if args.cmd == "crash-apply":
        _patch_boom(args.nth)
        try:
            st.apply_feature(FeatureBundle.load(args.bundle))
            print(json.dumps({"outcome": "NO_CRASH(异常:未按预期中断)"}))
            return 1
        except KeyboardInterrupt:
            out = {"outcome": "CRASHED_MID_APPLY", **_journal_state(args.ledger)}
            print(json.dumps(out, ensure_ascii=False))
            return 0

    if args.cmd == "crash-rollback":
        _patch_boom(args.nth)
        try:
            st.rollback_top()
            print(json.dumps({"outcome": "NO_CRASH(异常:未按预期中断)"}))
            return 1
        except KeyboardInterrupt:
            out = {"outcome": "CRASHED_MID_ROLLBACK", **_journal_state(args.ledger)}
            print(json.dumps(out, ensure_ascii=False))
            return 0

    if args.cmd == "slow-apply":
        _patch_slow(args.delay)
        tx = st.apply_feature(FeatureBundle.load(args.bundle))
        print(json.dumps({"outcome": "APPLIED(外部未杀到?)",
                          "state": tx.result_state_id}))
        return 1  # 本命令的预期归宿是被 kill -9,能走到这说明实验失败

    if args.cmd == "try-op":
        try:
            st.apply_feature(FeatureBundle.load(args.bundle))
            print(json.dumps({"outcome": "APPLIED(异常:journal 未拦截)"}))
            return 1
        except StackJournalPending as e:
            print(json.dumps({"outcome": "REFUSED_JOURNAL_PENDING",
                              "message": str(e)[:100]}, ensure_ascii=False))
            return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
