#!/usr/bin/env python3
"""Runtime Profile 晋级 —— 判 + 留痕。

判据在 `src/repoproof/execution/profile_promotion.py`(G1–G8,冻结)。
本脚本只做两件事:跑判据、把结论落成可复核的证据。

**晋级不是改个字段。** 一个 profile 的 lifecycle 是对外承诺(它决定别人
敢不敢拿它的发次当数),所以每一次变动都要留下:凭什么、依据哪份证据、
哪几条判据过了。没有这份留痕,"它是 candidate"就成了一句无从复核的自述。

用法::

    .venv/bin/python scripts/promote_profile.py --list
    .venv/bin/python scripts/promote_profile.py rt-sidecar-canary-v1
    .venv/bin/python scripts/promote_profile.py rt-sidecar-canary-v1 --to qualified
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "benchmarks" / "v2" / "sidecar_conformance"))
sys.path.insert(0, str(REPO / "benchmarks" / "v2" / "receipt_controls"))

from repoproof.execution.profile_promotion import evaluate_promotion  # noqa: E402
from repoproof.execution.runtime_profiles import known_profiles  # noqa: E402

LEDGER = REPO / "docs" / "evidence" / "profile_lifecycle" / "promotions.jsonl"


# 各 suite 的 profile 定义文件。**按路径列举,不按模块名 import** ——
# 多个 suite 都有 `profile.py`,裸 import 会被 sys.modules 里先到的赢走,
# 于是 `--list` 少列一个 profile 而毫无提示(实测在浏览器 suite 上发生过
# 同型问题:整张拓扑表报的是别的 suite 的)。
_SUITE_PROFILES = (
    ("benchmarks/v2/sidecar_conformance/profile.py", "suite_canary_profile"),
    ("benchmarks/v2/sidecar_browser/profile.py", "suite_browser_profile"),
    ("benchmarks/v2/receipt_controls/sidecar.py", "suite_mdit_profile"),
)


def _load_side_profiles() -> None:
    """把非内置的 profile 登记进来(它们随各自的使用者定义)。

    加载失败**要说出来**:一个 profile 没登记上,`--list` 就少一行,而少的
    那行看起来和"这个 profile 不存在"一模一样。
    """
    import importlib.util

    for rel, name in _SUITE_PROFILES:
        f = REPO / rel
        if not f.is_file():
            print(f"[warn] suite profile 不在:{rel}", file=sys.stderr)
            continue
        try:
            spec = importlib.util.spec_from_file_location(name, f)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
        except Exception as e:                               # noqa: BLE001
            print(f"[warn] 登记 {rel} 失败:{type(e).__name__}: {e}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("profile_id", nargs="?")
    ap.add_argument("--to", default=None, help="目标级别;默认为下一级")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--record", action="store_true",
                    help="判据全过时把晋级写进 promotions.jsonl")
    args = ap.parse_args()
    _load_side_profiles()

    if args.list or not args.profile_id:
        print(f"{'profile':30} {'拓扑':11} 生命周期")
        for pid, p in sorted(known_profiles().items()):
            print(f"  {pid:28} {p.topology:11} {p.lifecycle}")
        return 0

    v = evaluate_promotion(args.profile_id, repo=REPO, to=args.to)
    print(f"{v.profile_id}:{v.frm} → {v.to}")
    for c in v.checks:
        print(f"  {'✓' if c.ok else '✗'} {c.id:26} {c.detail}")
    if not v.machine_decidable:
        print("\n**这一级机器判不了。** 要走这一步,请人做决定并在 "
              "docs/RUNTIME-MODES.md 留痕 —— 凑几个数就自动放行,"
              "等于把一个取舍伪装成一个测量。")
        return 2
    if not v.ok:
        print(f"\n不予晋级:{len(v.failed())} 条判据未过。")
        return 1

    print("\n判据全过,可晋级。")
    if args.record:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(v.as_dict(), ensure_ascii=False) + "\n")
        print(f"已留痕:{LEDGER}")
        print("**记得同时改 RuntimeProfile 的 lifecycle 字段并提交** —— "
              "留痕与声明必须一致,由 tests/test_profile_promotion.py 钉死。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
