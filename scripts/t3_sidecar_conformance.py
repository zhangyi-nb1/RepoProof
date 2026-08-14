#!/usr/bin/env python3
"""T3-SIDECAR v1 的**任务级**控制矩阵 —— 这道题可不可解、可不可判。

与前两个矩阵的分工:

    receipt_controls      回执机制不可伪造(上游 markdown-it-py)
    browser_conformance   这条拓扑在真上游上成立(browser-use + 封存 Chromium)
    **本脚本**            **这道题本身**可解且可判 —— 控制组是任务包里的
                          `controls/*/page_facts.py`,也就是将来真模型要写的
                          那个 Adapter 的位置

它回答的是 F0 的问题:**在跑任何模型之前,先证明这道题的判据不是墙、也不是
筛子。** 正控必须过(否则模型再好也过不了),四个负控必须各红各的位置(否则
分不清判据在判什么)。

零模型。控制组直接被 import 并调用其 `mount_page_facts`,跑在一个最小的
FastAPI 应用上 —— 不需要整个 OfferClaw 宿主,因为这道题的靶子是 Adapter,
不是宿主集成(那是 T3-INPROC 在考的)。
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
SUITE = REPO / "benchmarks" / "v2" / "sidecar_browser"
sys.path.insert(0, str(SUITE))
sys.path.insert(0, str(REPO / "benchmarks" / "v2" / "web_fixture"))
TASK = REPO / "benchmarks" / "v2" / "tasks" / "t3_sidecar_v1"

from repoproof.execution.upstream_sidecar import start_sidecar  # noqa: E402
from repoproof.receipts.ledger import LEDGER_NAME, new_key, new_nonce  # noqa: E402

EXPECT = {
    "positive": ("PASS", set()),
    "nc1_no_sidecar": ("FAIL", {"U3.coverage", "U4.adoption"}),
    "nc2_ignores_result": ("FAIL", {"U4.adoption"}),
    "nc3_one_call_for_all": ("FAIL", {"U3.coverage", "U4.adoption"}),
    "nc4_wrong_symbol": ("FAIL", {"U2.symbol", "U3.coverage", "U4.adoption"}),
}

_PROFILE = None


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _profile():
    """**只加载一次** —— 重载会重建 RuntimeProfile,触发注册表守卫。"""
    global _PROFILE
    if _PROFILE is None:
        _PROFILE = _load(SUITE / "profile.py", "t3s_profile")
    return _PROFILE


def _run_control(name: str, *, items: list[dict]) -> dict:
    """跑一个控制组:起 fixture + sidecar,让它处理这批项,取回交付。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from server import serve

    P = _profile()
    work = Path(tempfile.mkdtemp(prefix="rp-t3s-"))
    ledger = work / LEDGER_NAME
    key, nonce = new_key(), new_nonce()
    run_id = f"t3s-{name}"

    web = serve("t3-sidecar-fixture")
    base = f"http://127.0.0.1:{web.server_address[1]}/"
    jobs = [{"url": f"{base}?item={it['request_nonce']}",
             "request_nonce": it["request_nonce"]} for it in items]

    handle = start_sidecar(spec=P.SPEC, ledger_path=ledger, key=key, run_id=run_id,
                           run_nonce=nonce, token="tok-" + nonce[:8],
                           profile_id=P.PROFILE_ID, default_symbol=P.SYMBOL)
    env = handle.agent_env()
    # 控制组看到的**全部**东西:端点、令牌、要调的符号。没有台账路径、没有密钥。
    os.environ.update({"OFFERCLAW_PAGE_FACTS": "1",
                       "REPOPROOF_SIDECAR_URL": env["REPOPROOF_SIDECAR_URL"],
                       "REPOPROOF_SIDECAR_TOKEN": env["REPOPROOF_SIDECAR_TOKEN"],
                       "REPOPROOF_SIDECAR_SYMBOL": P.SYMBOL})
    try:
        ctl = _load(TASK / "controls" / name / "page_facts.py", f"t3s_ctl_{name}")
        app = FastAPI()
        ctl.mount_page_facts(app)
        with TestClient(app) as c:
            jid = c.post("/api/page-facts", json={"items": jobs}).json()["job_id"]
            import time

            for _ in range(240):
                st = c.get(f"/api/page-facts/{jid}").json()
                if st["state"] in {"done", "failed"}:
                    break
                time.sleep(0.5)
        delivery = st.get("facts") or []
        failure = st.get("failure", "")
    finally:
        written = handle.receipts_written()
        handle.shutdown()
        web.shutdown()
        for k in ("OFFERCLAW_PAGE_FACTS", "REPOPROOF_SIDECAR_URL",
                  "REPOPROOF_SIDECAR_TOKEN", "REPOPROOF_SIDECAR_SYMBOL"):
            os.environ.pop(k, None)

    ident = P.SPEC.identity()
    from verify_task_receipts import verify

    v = verify(ledger=ledger, key=key, run_id=run_id, run_nonce=nonce,
               items=jobs, delivery=delivery, receipts_written=written,
               required_symbols=set(P.PROFILE.required_symbols),
               required_upstream={"distribution": ident.distribution,
                                  "import_module": ident.import_module,
                                  "artifact_hash": ident.artifact_hash})

    exp, exp_red = EXPECT[name]
    return {"control": name, "expect": exp, "expect_red": sorted(exp_red),
            "actual": "PASS" if v.ok else "FAIL",
            "actual_red": sorted({f.check for f in v.failed()}),
            "job_state": st.get("state"), "failure": failure,
            "verdict": v.as_dict()}


def find_problems(rows: list[dict]) -> list[str]:
    """判定 —— 单独一个函数,好让钉死直接考它(M50a 的教训)。"""
    out: list[str] = []
    for r in rows:
        if r["actual"] != r["expect"]:
            out.append(f"{r['control']}:期望 {r['expect']},实际 {r['actual']}"
                       f"{'(' + r['failure'] + ')' if r.get('failure') else ''}")
        elif r["expect"] == "FAIL" and set(r["actual_red"]) != set(r["expect_red"]):
            out.append(f"{r['control']}:红的位置不对 —— 期望 {r['expect_red']},"
                       f"实际 {r['actual_red']}")
    return out


def main() -> int:
    P = _profile()
    ok, why = P.available()
    if not ok:
        print(f"封存 runtime 不可用:{why}", file=sys.stderr)
        return 2

    # 两项:一项也能跑,但**抓不住"一次调用充抵所有项"** —— 分母必须 ≥2。
    items = [{"request_nonce": "item-1"}, {"request_nonce": "item-2"}]

    rows = [_run_control(n, items=items) for n in EXPECT]
    problems = find_problems(rows)

    families = ("U1", "U2", "U3", "U4")
    disc = {}
    for fam in families:
        red = [r["control"] for r in rows
               if any(c.startswith(fam + ".") for c in r["actual_red"])]
        green = [r["control"] for r in rows
                 if not any(c.startswith(fam + ".") for c in r["actual_red"])]
        disc[fam] = {"red_in": red, "green_in": green}
        if not green:
            problems.append(f"{fam}:在所有控制组上都红 —— 与'恒红'无从区分")
    # U1(台账完整性)在**本矩阵里不被攻击**,那是有意的:回执机制的伪造/
    # 重放/篡改由 receipt_controls 与 browser_conformance 两个矩阵专门考。
    # 这里考的是**这道题**——Adapter 会不会正确调用与采纳。如实写出来,
    # 免得"U1 红 0 个"被读成缺口。
    never = [f for f in families if not disc[f]["red_in"]]
    covered_elsewhere = {"U1": "receipt_controls / browser_conformance 两个矩阵"}
    uncovered = [f for f in never if f not in covered_elsewhere]
    if uncovered:
        problems.append(f"这些族本矩阵没考到、别处也没有:{uncovered}")

    w = max(len(r["control"]) for r in rows)
    print(f"{'控制组'.ljust(w)}  期望   实际   红在哪")
    for r in rows:
        print(f"{'✓' if r['actual'] == r['expect'] else '✗'} {r['control'].ljust(w)}  "
              f"{r['expect']:5}  {r['actual']:5}  {','.join(r['actual_red']) or '—'}")
    print("\n判别力:")
    for fam, d in disc.items():
        print(f"  {fam}  红 {len(d['red_in'])} 个 {d['red_in']}")
    if never:
        print(f"本矩阵未攻击的族:{never} —— "
              f"由 {[covered_elsewhere.get(f, '(无)') for f in never]} 覆盖")

    out = REPO / "docs" / "evidence" / "t3_sidecar_conformance" / "matrix.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"_what": "T3-SIDECAR v1 的任务级控制矩阵(F0:先证明判据不是墙也不是筛子)",
         "_not_a_benchmark": "零模型;不进 runs.jsonl,不影响任何闸门数字",
         "task_id": "t3-sidecar-page-facts-v1", "profile_id": P.PROFILE_ID,
         "items": len(items), "rows": rows, "discrimination_by_family": disc,
         "families_not_attacked_here": never,
         "of_which_covered_elsewhere": {f: covered_elsewhere[f]
                                        for f in never if f in covered_elsewhere},
         "problems": problems, "ok": not problems},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if problems:
        print("\n不合格:")
        for p in problems:
            print("  -", p)
        print(f"\n证据:{out}")
        return 1
    print(f"\n1 正控 + {len(rows) - 1} 负控全部符合预期。\n证据:{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
