#!/usr/bin/env python3
"""Sidecar Conformance / Runtime Canary —— A1 的第一个使用者。

**不是 benchmark,不计模型能力。** 它测的是 harness 自己那条链走不走得通
(F0 自检),证明的是这一串:

    Agent ──只能调 RPC──▶ Harness-owned Sidecar ──真执行钉版上游──▶ Receipt ──▶ Verifier

与第 6 步那套回执正负控矩阵的分工:

    receipt_controls   证明**回执机制**不可伪造。上游用 markdown-it-py ——
                       那是 agent venv 里装得到的包,于是"假包""导入真包却
                       用复制实现"两条只能靠约定成立。
    本脚本             证明**这条拓扑**成立。上游是 harness 独占的 fixture,
                       agent 想 import 都 import 不着 —— 靠拓扑成立,不靠约定。
                       并且现场核验这一点(`topology.py` 四条)。

零模型、零网络、完全确定性。上游 fixture 的能力**不可重实现**(盐只有它
知道),否则"自己重实现"那条会因为输出恰好相同而在 U4 上蒙混过去。

用法::

    .venv/bin/python scripts/sidecar_conformance.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
CONF_DIR = REPO / "benchmarks" / "v2" / "sidecar_conformance"
sys.path.insert(0, str(CONF_DIR))
sys.path.insert(0, str(REPO / "benchmarks" / "v2" / "receipt_controls"))   # 复用 client

from repoproof.execution.upstream_sidecar import start_sidecar  # noqa: E402
from repoproof.receipts.ledger import LEDGER_NAME, new_key, new_nonce  # noqa: E402
from repoproof.receipts.model import CANON_JSON, CANON_TEXT_SQUASH, digest_of  # noqa: E402
from repoproof.receipts.verify import (  # noqa: E402
    digest_equality_predicate,
    register_adoption,
    verify_receipts,
)

TASK_ID = "sidecar-conformance-canary"

# 三份作业。刻意带不规则空白与空行,让"规范化"这件事有实质内容 ——
# 若作业本身已经规范,诚实实现与什么都不做的实现输出相同,采纳判据就测不出东西。
JOBS = [
    {"request_nonce": "rn-1", "text": "  Alpha   line one \n\n  second   line  \n"},
    {"request_nonce": "rn-2", "text": "Beta\t\ttabbed\n   \n  trailing spaces   \n"},
    {"request_nonce": "rn-3", "text": "\n\nGamma only one line\n\n"},
]


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _expected_units() -> list[dict]:
    """U3 的分母 —— harness 侧独立算出,**不来自 adapter**。

    分母若由被测方提供,"象征性调一次"永远抓不住。"""
    return [{"request_nonce": j["request_nonce"],
             "input_digest": digest_of({"text": j["text"]}, canon=CANON_JSON)}
            for j in JOBS]


def _register_predicate():
    register_adoption(TASK_ID, digest_equality_predicate(
        lambda dv: [digest_of(x, canon=CANON_TEXT_SQUASH) for x in (dv or [])]))


def run_one(adapter_path: Path, *, replay_source: Path | None = None,
            replay_key: bytes | None = None) -> dict:
    import profile as P

    ad = _load(adapter_path)
    work = Path(tempfile.mkdtemp(prefix="rp-conf-"))
    ledger = work / LEDGER_NAME
    key, nonce = new_key(), new_nonce()
    run_id = f"conf-{adapter_path.stem}"

    if getattr(ad, "NEEDS_REPLAYED_LEDGER", False):
        if replay_source is None or not replay_source.is_file():
            raise SystemExit("a6 需要一本上一轮的台账,但没有 —— 先跑正控")
        # 沿用上一轮密钥:否则签名先挂,U1.run_nonce 那道走不到(第 6 步教训)
        key = replay_key or key
        shutil.copy2(replay_source, ledger)
        # 注意:本次 sidecar 一条都不会写,而台账里有上一轮的 N 条。
        # `U1.count` 因此也会红 —— 那是**真信号**(台账里有执行方没写过的
        # 东西),不是噪声。

        os.environ["REPOPROOF_REPLAY_SOURCE"] = str(ledger)

    ident = P.SPEC.identity()
    if getattr(ad, "NEEDS_LEDGER_PATH", False):
        # 故意把台账路径交给 a7/a8。现实里 agent 够不到 runs/,这里给它,
        # 是为了把"链"和"签名"两道单独拎出来考 —— 让篡改者/伪造者除那一道
        # 之外样样做对,看那一道自己站不站得住。
        os.environ.update({
            "REPOPROOF_FORGE_TARGET": str(ledger),
            "REPOPROOF_FORGE_RUN_ID": run_id,
            "REPOPROOF_FORGE_RUN_NONCE": nonce,
            "REPOPROOF_FORGE_UPSTREAM": json.dumps({
                "distribution": ident.distribution, "version": ident.version,
                "artifact_hash": ident.artifact_hash,
                "import_module": ident.import_module, "symbol": P.SYMBOL})})

    handle = start_sidecar(spec=P.SPEC, ledger_path=ledger, key=key, run_id=run_id,
                           run_nonce=nonce, token="tok-" + nonce[:8],
                           profile_id=P.PROFILE_ID, default_symbol=P.SYMBOL)
    try:
        from client import Sidecar

        env = handle.agent_env()           # adapter 拿到的**全部**东西
        delivery = ad.run(Sidecar(env["REPOPROOF_SIDECAR_URL"],
                                  env["REPOPROOF_SIDECAR_TOKEN"]), JOBS)
    finally:
        written = handle.receipts_written()
        handle.shutdown()
    for k in ("REPOPROOF_REPLAY_SOURCE", "REPOPROOF_FORGE_TARGET",
              "REPOPROOF_FORGE_RUN_ID", "REPOPROOF_FORGE_RUN_NONCE",
              "REPOPROOF_FORGE_UPSTREAM"):
        os.environ.pop(k, None)

    v = verify_receipts(
        ledger, key=key, run_id=run_id, run_nonce=nonce, task_id=TASK_ID,
        required_symbols=set(P.PROFILE.required_symbols),
        required_upstream={"distribution": ident.distribution,
                           "import_module": ident.import_module,
                           "artifact_hash": ident.artifact_hash},
        expected_units=_expected_units(), delivery=delivery,
        expected_receipt_count=written)

    return {"_key": key, "adapter": adapter_path.stem,
            "expect": getattr(ad, "EXPECT", "?"),
            "expect_red": sorted(getattr(ad, "EXPECT_RED", set())),
            "actual": "PASS" if v.ok else "FAIL",
            "actual_red": sorted({f.check for f in v.failed()}),
            "verdict": v.as_dict(), "ledger": str(ledger)}


def find_problems(rows: list[dict]) -> list[str]:
    """判定 —— 单独一个函数,好让钉死直接考它(第 6 步 M50a 的教训)。"""
    problems: list[str] = []
    for r in rows:
        if r["actual"] != r["expect"]:
            problems.append(f"{r['adapter']}:期望 {r['expect']},实际 {r['actual']}")
        elif r["expect"] == "FAIL" and set(r["actual_red"]) != set(r["expect_red"]):
            problems.append(f"{r['adapter']}:红的位置不对 —— 期望 {r['expect_red']},"
                            f"实际 {r['actual_red']}")
    return problems


def selfcheck() -> list[str]:
    """自证:把采纳谓词换成"永远放行",a4 必须由 FAIL 变 PASS。

    a4 是最好的探针 —— 它只在 U4 上红,换掉 U4 就该整个变绿。不做这一步,
    "八条攻击全被挡住"分不清是验证器真的挡住了,还是脚本在读自己的期望值。"""
    bad = []
    from repoproof.receipts import verify as V

    _register_predicate()
    strict = run_one(CONF_DIR / "adapters" / "a4_ignores_result.py")
    if strict["actual"] != "FAIL":
        bad.append("自证(1):严格谓词下 a4 竟然过了 —— 验证器根本没在验")

    V.register_adoption(TASK_ID, lambda receipts, delivery: (True, "自证用:永远放行"))
    loose = run_one(CONF_DIR / "adapters" / "a4_ignores_result.py")
    if loose["actual"] != "PASS":
        bad.append(f"自证(2):放行谓词下 a4 仍未过,红在 {loose['actual_red']} —— "
                   "脚本读的不是验证结果,或 U4 之外还有别的在拦它")
    _register_predicate()
    return bad


def main() -> int:
    # ---- 地基先查:上游若够得着,后面全是装饰 ------------------------
    from topology import check_topology

    topo = check_topology()
    print("拓扑核验(A1 的地基):")
    for f in topo["findings"]:
        print(f"  {'✓' if f['ok'] else '✗'} {f['check']:34} {f['detail'][:70]}")
    if not topo["ok"]:
        print("\n拓扑不成立 —— agent 够得到上游,后面的回执与负控全是装饰。拒绝出数。",
              file=sys.stderr)
        return 2

    bad = selfcheck()
    if bad:
        print("\n自证不过,拒绝出数:", file=sys.stderr)
        for b in bad:
            print("  -", b, file=sys.stderr)
        return 3
    print("\n自证通过(2 条:严格谓词拦得住 a4,放行谓词放得过 a4)\n")

    rows = [run_one(CONF_DIR / "adapters" / "a0_honest.py")]
    replay_source, replay_key = Path(rows[0]["ledger"]), rows[0].pop("_key")
    for p in sorted((CONF_DIR / "adapters").glob("a[1-9]*.py")):
        rows.append(run_one(p, replay_source=replay_source, replay_key=replay_key))
    for r in rows:
        r.pop("_key", None)

    problems = find_problems(rows)

    # 判别力:每族谓词都得红过也绿过 —— 恒红的判据不携带信息
    families = ("U1", "U2", "U3", "U4")
    disc = {}
    for fam in families:
        red = [r["adapter"] for r in rows
               if any(c.startswith(fam + ".") for c in r["actual_red"])]
        green = [r["adapter"] for r in rows
                 if not any(c.startswith(fam + ".") for c in r["actual_red"])]
        disc[fam] = {"red_in": red, "green_in": green}
        if not red:
            problems.append(f"{fam}:没有任何 adapter 让它报红 —— 这批攻击没考到它")
        if not green:
            problems.append(f"{fam}:在所有 adapter 上都红 —— 与'恒红'无从区分")

    all_checks = sorted({c["check"] for r in rows for c in r["verdict"]["findings"]})
    never_red = [c for c in all_checks if not any(c in r["actual_red"] for r in rows)]

    w = max(len(r["adapter"]) for r in rows)
    print(f"{'adapter'.ljust(w)}  期望   实际   红在哪")
    for r in rows:
        mark = "✓" if r["actual"] == r["expect"] else "✗"
        print(f"{mark} {r['adapter'].ljust(w)}  {r['expect']:5}  {r['actual']:5}  "
              f"{','.join(r['actual_red']) or '—'}")

    print("\n判别力(每族都得红过也绿过):")
    for fam, d in disc.items():
        print(f"  {fam}  红 {len(d['red_in'])} 个 {d['red_in']}")
    print(f"\n本批攻击没考到的子判据:{never_red or '无'}")

    out = REPO / "docs" / "evidence" / "sidecar_conformance" / "matrix.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"_what": "Sidecar Conformance / Runtime Canary —— A1 的第一个使用者",
         "_not_a_benchmark": "F0 自检;不计模型能力,不进 runs.jsonl,不影响任何闸门数字",
         "task_id": TASK_ID, "profile_id": "rt-sidecar-canary-v1",
         "topology": topo, "jobs": len(JOBS), "rows": rows,
         "discrimination_by_family": disc,
         "checks_never_exercised": never_red,
         "problems": problems, "ok": not problems and topo["ok"]},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if problems:
        print("\n不合格:")
        for p in problems:
            print("  -", p)
        print(f"\n证据:{out}")
        return 1
    print(f"\n1 正控 + {len(rows) - 1} 条攻击全部符合预期,且各红各的位置。\n证据:{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
