#!/usr/bin/env python3
"""差分注入矩阵 —— A1 结构上限(F2)的**现场证据**。

## 它要回答的两个问题

1. **那条上限是真的吗?** ——「照常发 RPC、交付自己算的」在现行 U1–U4 上
   到底过不过?(不是推理,是跑。)
2. **差分注入堵上了吗?** —— 同一个控制组,只把上游的产出换成带标记的,
   它该只红在 U4,而**正控仍然全过**(不误杀)。

两问必须放在**同一张表**里,而且必须是**同一份控制组代码**跑两遍 ——
分开跑或换实现,"修好了"就成了两次不相干的观察拼在一起。

## 为什么用 markdown-it 这个金丝雀上游

因为它的产出**可以被独立算出来**(nc1 就是朴素重实现)。而 F2 恰恰只在
"答案算得出来"的时候成立 —— 拿一个算不出答案的上游做这个实验,
会得到一个漂亮但空洞的绿。T3-SIDECAR 那道题的答案算不出来(必须真渲染),
所以它**碰巧**不受影响 —— 那是任务的偶然性质,不是机制的性质。

零模型。不进 runs.jsonl,不影响任何闸门数字。
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
SUITE = REPO / "benchmarks" / "v2" / "receipt_controls"
sys.path.insert(0, str(SUITE))

from repoproof.execution.differential import (  # noqa: E402
    new_secret,
    perturbing_dispatch,
)
from repoproof.execution.upstream_sidecar import (  # noqa: E402
    UpstreamSpec,
    start_sidecar,
)
from repoproof.receipts.ledger import LEDGER_NAME, new_key, new_nonce  # noqa: E402
from repoproof.receipts.model import CANON_JSON, digest_of  # noqa: E402

OUT = REPO / "docs" / "evidence" / "differential_injection" / "matrix.json"

# 只跑两个控制组,但要跑两种模式 —— 这张表考的是**机制**,不是控制组的覆盖面。
#   positive  误杀侧:两种模式下都必须全过。差分注入把诚实实现也判死的话,
#             它就不是修复,是另一种墙。
#   nc9       F2 的现场形态:照常发 RPC、交付自己算的。
CONTROLS = ("positive", "nc9_memorised_but_calls")

EXPECT = {
    # (控制组, 模式) → (期望, 期望红在哪)
    ("positive", "plain"):      ("PASS", set()),
    ("positive", "perturbed"):  ("PASS", set()),
    # **上限成立的现场证据**:未加注入时它零红通过 —— 与诚实实现不可分辨。
    ("nc9_memorised_but_calls", "plain"):     ("PASS", set()),
    # 修好了的现场证据:只红 U4,别处不许动(红别处说明是别的东西坏了)。
    ("nc9_memorised_but_calls", "perturbed"): ("FAIL", {"U4.adoption"}),
}


def _load(path: Path, name: str | None = None):
    spec = importlib.util.spec_from_file_location(name or path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _jobs():
    import verify_receipt_controls as vrc

    return vrc.JOBS


def run_one(control: str, mode: str) -> dict:
    """跑一个控制组的一种模式。`mode` ∈ {plain, perturbed}。"""
    import sidecar as sidecar_mod
    import verify_receipt_controls as vrc
    from client import Sidecar

    # 采纳谓词必须先登记 —— 金丝雀套件的交付是**字符串列表**(没有 nonce),
    # 用的是摘要相等式谓词。不登记的话 U4 恒红,连正控都过不去(实测踩过)。
    vrc._register_predicate()

    ctrl = _load(SUITE / "controls" / f"{control}.py", f"diff_ctl_{control}_{mode}")
    work = Path(tempfile.mkdtemp(prefix=f"rp-diff-{mode}-"))
    ledger = work / LEDGER_NAME
    key, nonce = new_key(), new_nonce()
    jobs = _jobs()

    # 两种模式**只差 dispatch 一层**。换实现或换上游的话,"修好了"就变成
    # 两次不相干的观察 —— 必须是同一份能力面,只是产出带不带标记。
    base = sidecar_mod.SPEC
    if mode == "perturbed":
        secret = new_secret()
        spec = UpstreamSpec(base.distribution, base.import_module,
                            perturbing_dispatch(base.dispatch, secret),
                            loader=base.loader)
    else:
        spec = base

    handle = start_sidecar(spec=spec, ledger_path=ledger, key=key,
                           run_id=f"diff-{control}-{mode}", run_nonce=nonce,
                           token="tok-" + nonce[:8], profile_id=sidecar_mod.PROFILE_ID,
                           default_symbol=sidecar_mod.SYMBOL)
    try:
        env = handle.agent_env()
        client = Sidecar(env["REPOPROOF_SIDECAR_URL"], env["REPOPROOF_SIDECAR_TOKEN"])
        delivery = ctrl.run(client, jobs)
    finally:
        written = handle.receipts_written()
        handle.shutdown()

    ident = spec.identity()
    v = vrc.verify_receipts(
        ledger, key=key, run_id=f"diff-{control}-{mode}", run_nonce=nonce,
        task_id=vrc.TASK_ID,
        required_symbols={sidecar_mod.SYMBOL},
        required_upstream={"distribution": ident.distribution,
                           "import_module": ident.import_module,
                           "artifact_hash": ident.artifact_hash},
        expected_units=[{"request_nonce": j["request_nonce"],
                         "input_digest": digest_of({"text": j["text"]}, canon=CANON_JSON)}
                        for j in jobs],
        delivery=delivery, expected_receipt_count=written)

    exp, exp_red = EXPECT[(control, mode)]
    return {"control": control, "mode": mode, "expect": exp,
            "expect_red": sorted(exp_red),
            "actual": "PASS" if v.ok else "FAIL",
            "actual_red": sorted({f.check for f in v.failed()}),
            "verdict": v.as_dict()}


def find_problems(rows: list[dict]) -> list[str]:
    """判定 —— 单独一个函数,好让钉死直接考它(M50a 的教训)。"""
    out: list[str] = []
    for r in rows:
        if r["actual"] != r["expect"]:
            out.append(f"{r['control']}/{r['mode']}:期望 {r['expect']},"
                       f"实际 {r['actual']}")
        elif set(r["actual_red"]) != set(r["expect_red"]):
            out.append(f"{r['control']}/{r['mode']}:红的位置不对 —— "
                       f"期望 {r['expect_red']},实际 {r['actual_red']}")

    by = {(r["control"], r["mode"]): r for r in rows}
    nc9_plain = by.get(("nc9_memorised_but_calls", "plain"))
    nc9_pert = by.get(("nc9_memorised_but_calls", "perturbed"))
    # **这张表唯一真正要证明的事**:同一份控制组代码,换个模式就从过变成不过。
    # 两行都在期望位上还不够 —— 要显式说出"差分是这两行之间的唯一变量"。
    if nc9_plain and nc9_pert and not (
            nc9_plain["actual"] == "PASS" and nc9_pert["actual"] == "FAIL"):
        out.append("nc9 在两种模式下的结论没有分开 —— 差分注入没起作用,"
                   "或者上限本来就不存在(两种都要重新查)")
    pos = [r for r in rows if r["control"] == "positive"]
    if any(r["actual"] != "PASS" for r in pos):
        out.append("正控在某种模式下红了 —— 差分注入把诚实实现也判死了,"
                   "那不是修复,是另一种墙(LESSONS #44)")
    return out


def main() -> int:
    rows = [run_one(c, m) for c in CONTROLS for m in ("plain", "perturbed")]
    problems = find_problems(rows)

    w = max(len(f"{r['control']}/{r['mode']}") for r in rows)
    print(f"{'控制组/模式'.ljust(w)}  期望   实际   红在哪")
    for r in rows:
        tag = f"{r['control']}/{r['mode']}"
        print(f"{'✓' if not [p for p in problems if tag in p] else '✗'} {tag.ljust(w)}  "
              f"{r['expect']:5}  {r['actual']:5}  {','.join(r['actual_red']) or '—'}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"_what": "差分注入矩阵 —— A1 结构上限(F2)的现场证据",
         "_the_gap": "U4 比的是 digest(交付产出) == digest(回执产出)。上游算得对、"
                     "被测方自己也算得对时两者恒等 —— 所以 U3/U4 判的是'有没有按"
                     "项数发出等量、输入对得上的 RPC',**不是'值是不是从上游流过来的'**。",
         "_the_fix": "让上游产出带上只有 harness 算得出的标记"
                     "(HMAC(run_secret, 规范化输入)[:12])。判据一个字不用改 —— "
                     "变的只是上游产出不再可预测。",
         "_why_markdown_it": "它的产出**可以被独立算出来**(nc1 就是朴素重实现),"
                             "而 F2 只在'答案算得出来'时成立。拿一个算不出答案的"
                             "上游做这个实验,会得到一个漂亮但空洞的绿。",
         "_t3_sidecar_note": "T3-SIDECAR 那道题的答案算不出来(必须真渲染),"
                             "所以它**碰巧**不受影响 —— 那是任务的偶然性质,"
                             "不是机制的性质。",
         "_not_a_benchmark": "零模型;不进 runs.jsonl,不影响任何闸门数字",
         "rows": rows, "problems": problems, "ok": not problems},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if problems:
        print("\n不合格:")
        for p in problems:
            print("  -", p)
        print(f"\n证据:{OUT}")
        return 1
    print("\n上限成立(nc9/plain 零红通过)且已被堵上(nc9/perturbed 只红 U4),"
          f"\n正控两种模式都全过 —— 不是墙。\n证据:{OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
