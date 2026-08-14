#!/usr/bin/env python3
"""`rt-sidecar-browser-v1` 的 conformance 矩阵 —— **真上游 + 真浏览器**。

与 `sidecar_conformance.py`(canary)的分工:那边用手造 fixture 上游证明
**机制**成立;这边换成真 browser-use 0.13.7 + 封存 Chromium,证明同一套机制
在真实上游上照样成立。

**为什么不改造 canary 那个脚本去复用**:M52b/M52c 两条变异按逐字节的 `old`
串守着它;一改就 STALE,闸门会当场把整批判成不可归因。判定逻辑
(`find_problems`)从那边**import** 过来,所以真正的判据只有一份 —— 重复的
只是编排。

零模型。浏览器起在死代理下(只放行 127.0.0.1),证明这一步不需要外网。
每条 adapter 要真起一次浏览器(~5s),全矩阵约一分钟 —— 慢,但**默认就跑**:
一条默认跳过的判据等于没有判据。
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
# 直接跑脚本时 `scripts/` 是 sys.path[0];被 pytest 按路径加载时不是 ——
# 而判定函数(`find_problems`)要从那边 import,少了就 ModuleNotFoundError。
sys.path.insert(0, str(REPO / "scripts"))
SUITE = REPO / "benchmarks" / "v2" / "sidecar_browser"
sys.path.insert(0, str(SUITE))
sys.path.insert(0, str(REPO / "benchmarks" / "v2" / "web_fixture"))
sys.path.insert(0, str(REPO / "benchmarks" / "v2" / "receipt_controls"))   # client

from repoproof.execution.upstream_sidecar import start_sidecar  # noqa: E402
from repoproof.receipts.ledger import LEDGER_NAME, new_key, new_nonce  # noqa: E402
from repoproof.receipts.model import CANON_JSON, CANON_TEXT_SQUASH, digest_of  # noqa: E402
from repoproof.receipts.verify import (  # noqa: E402
    digest_equality_predicate,
    register_adoption,
    verify_receipts,
)

TASK_ID = "browser-sidecar-conformance"
FIXTURE_NONCE = "rp-browser-fixture-nonce"

# 两份作业(不是三份):每条 adapter 要真起浏览器,时间是真的。两份已经足够
# 让"象征性调一次"抓得住(U3 的分母 ≥2),再多只是线性变慢。
_JOB_NONCES = ("rn-1", "rn-2")


def _load(path: Path, name: str | None = None):
    """按**路径**加载,模块名加前缀。

    两个 suite 都有 `profile.py` 与 `topology.py`。裸 `import topology` 会被
    `sys.modules` 里先到的那个赢走 —— 实测就发生了:浏览器矩阵报出来的拓扑
    是 **canary 的**(T2 说 "No module named 'canary_upstream'",T3 指着
    canary 的 fixture 目录)。那正是"拿别人的体检报告给自己"的现场版,而且
    整张表其余部分全绿,看起来毫无异样。
    """
    n = name or f"bconf_{path.stem}"
    spec = importlib.util.spec_from_file_location(n, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[n] = mod
    spec.loader.exec_module(mod)
    return mod


_PROFILE_MOD = None
_TOPOLOGY = None


def _suite_profile():
    """**只加载一次**。

    重复加载会重新构造 `RuntimeProfile`,而里面的 dispatch 是函数对象 ——
    新对象与旧对象不相等,`register_profile` 的"同 id 不同内容"守卫会当场
    报警。那个守卫是对的(id 是对外承诺的名字),该改的是我重复加载。
    """
    global _PROFILE_MOD
    if _PROFILE_MOD is None:
        _PROFILE_MOD = _load(SUITE / "profile.py", "bconf_profile")
    return _PROFILE_MOD


def _suite_topology():
    """同样只加载一次,且**做成可替换的函数** —— 钉死要能喂给它一份"别的
    suite 的拓扑报告",直接考那道守卫认不认得出(变异 M54a 的教训:钉死只读
    落盘证据时,把守卫整个掏掉也没人看得见)。"""
    global _TOPOLOGY
    if _TOPOLOGY is None:
        _TOPOLOGY = _load(SUITE / "topology.py", "bconf_topology").check_topology
    return _TOPOLOGY


def _jobs(url: str) -> list[dict]:
    # 两份作业指向同一页面但**带不同查询串** —— 于是 input digest 不同,
    # "拿一张回执顶两个单元"当场露馅;而页面内容(答案)仍由真渲染决定。
    return [{"request_nonce": n, "text": f"{url}?job={n}"} for n in _JOB_NONCES]


def _expected_units(jobs: list[dict]) -> list[dict]:
    return [{"request_nonce": j["request_nonce"],
             "input_digest": digest_of({"text": j["text"]}, canon=CANON_JSON)}
            for j in jobs]


def _register_predicate():
    register_adoption(TASK_ID, digest_equality_predicate(
        lambda dv: [digest_of(x, canon=CANON_TEXT_SQUASH) for x in (dv or [])]))


def run_one(adapter_path: Path, *, replay_source: Path | None = None,
            replay_key: bytes | None = None) -> dict:
    from client import Sidecar
    from server import serve

    P = _suite_profile()
    ad = _load(adapter_path)
    work = Path(tempfile.mkdtemp(prefix="rp-bconf-"))
    ledger = work / LEDGER_NAME
    key, nonce = new_key(), new_nonce()
    run_id = f"bconf-{adapter_path.stem}"

    if getattr(ad, "NEEDS_REPLAYED_LEDGER", False):
        if replay_source is None or not replay_source.is_file():
            raise SystemExit("a6 需要上一轮台账 —— 先跑正控")
        key = replay_key or key            # 沿用旧密钥,好把 nonce 单独考出来
        shutil.copy2(replay_source, ledger)
        os.environ["REPOPROOF_REPLAY_SOURCE"] = str(ledger)

    ident = P.SPEC.identity()
    if getattr(ad, "NEEDS_LEDGER_PATH", False):
        os.environ.update({
            "REPOPROOF_FORGE_TARGET": str(ledger),
            "REPOPROOF_FORGE_RUN_ID": run_id,
            "REPOPROOF_FORGE_RUN_NONCE": nonce,
            "REPOPROOF_FORGE_UPSTREAM": json.dumps({
                "distribution": ident.distribution, "version": ident.version,
                "artifact_hash": ident.artifact_hash,
                "import_module": ident.import_module, "symbol": P.SYMBOL})})

    web = serve(FIXTURE_NONCE)
    url = f"http://127.0.0.1:{web.server_address[1]}/"
    jobs = _jobs(url)
    handle = start_sidecar(spec=P.SPEC, ledger_path=ledger, key=key, run_id=run_id,
                           run_nonce=nonce, token="tok-" + nonce[:8],
                           profile_id=P.PROFILE_ID, default_symbol=P.SYMBOL)
    try:
        env = handle.agent_env()
        delivery = ad.run(Sidecar(env["REPOPROOF_SIDECAR_URL"],
                                  env["REPOPROOF_SIDECAR_TOKEN"],
                                  timeout=240.0), jobs)
    finally:
        written = handle.receipts_written()
        handle.shutdown()
        web.shutdown()
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
        expected_units=_expected_units(jobs), delivery=delivery,
        expected_receipt_count=written)

    return {"_key": key, "adapter": adapter_path.stem,
            "expect": getattr(ad, "EXPECT", "?"),
            "expect_red": sorted(getattr(ad, "EXPECT_RED", set())),
            "actual": "PASS" if v.ok else "FAIL",
            "actual_red": sorted({f.check for f in v.failed()}),
            "verdict": v.as_dict(), "ledger": str(ledger)}


def selfcheck() -> list[str]:
    """自证:换成"永远放行"的采纳谓词,a4 必须由 FAIL 变 PASS。"""
    bad = []
    from repoproof.receipts import verify as V

    _register_predicate()
    strict = run_one(SUITE / "adapters" / "a4_ignores_result.py")
    if strict["actual"] != "FAIL":
        bad.append("自证(1):严格谓词下 a4 竟然过了 —— 验证器根本没在验")
    V.register_adoption(TASK_ID, lambda r, d: (True, "自证用:永远放行"))
    loose = run_one(SUITE / "adapters" / "a4_ignores_result.py")
    if loose["actual"] != "PASS":
        bad.append(f"自证(2):放行谓词下 a4 仍未过,红在 {loose['actual_red']}")
    _register_predicate()
    return bad


def main() -> int:
    from sidecar_conformance import find_problems  # 判定只有一份

    P = _suite_profile()
    check_topology = _suite_topology()

    ok, why = P.available()
    if not ok:
        print(f"封存 runtime 不可用:{why}", file=sys.stderr)
        return 2

    topo = check_topology()
    names = {f["check"] for f in topo["findings"]}
    if "T5.seal_intact" not in names:
        print(f"拓扑报告不是本 suite 的(缺 T5.seal_intact):{sorted(names)} —— "
              "多半又撞了模块名。拒绝出数。", file=sys.stderr)
        return 2
    print("拓扑核验(A1 的地基,真上游版):")
    for f in topo["findings"]:
        print(f"  {'✓' if f['ok'] else '✗'} {f['check']:34} {f['detail'][:66]}")
    if not topo["ok"]:
        print("\n拓扑不成立 —— agent 够得到真上游,后面全是装饰。拒绝出数。",
              file=sys.stderr)
        return 2

    bad = selfcheck()
    if bad:
        print("\n自证不过,拒绝出数:", file=sys.stderr)
        for b in bad:
            print("  -", b, file=sys.stderr)
        return 3
    print("\n自证通过(2 条:严格谓词拦得住 a4,放行谓词放得过 a4)\n")

    rows = [run_one(SUITE / "adapters" / "a0_honest.py")]
    replay_source, replay_key = Path(rows[0]["ledger"]), rows[0].pop("_key")
    for p in sorted((SUITE / "adapters").glob("a[1-9]*.py")):
        rows.append(run_one(p, replay_source=replay_source, replay_key=replay_key))
    for r in rows:
        r.pop("_key", None)

    problems = find_problems(rows)

    families = ("U1", "U2", "U3", "U4")
    disc = {}
    for fam in families:
        red = [r["adapter"] for r in rows
               if any(c.startswith(fam + ".") for c in r["actual_red"])]
        green = [r["adapter"] for r in rows
                 if not any(c.startswith(fam + ".") for c in r["actual_red"])]
        disc[fam] = {"red_in": red, "green_in": green}
        if not red:
            problems.append(f"{fam}:没有任何 adapter 让它报红")
        if not green:
            problems.append(f"{fam}:在所有 adapter 上都红 —— 与'恒红'无从区分")

    w = max(len(r["adapter"]) for r in rows)
    print(f"{'adapter'.ljust(w)}  期望   实际   红在哪")
    for r in rows:
        print(f"{'✓' if r['actual'] == r['expect'] else '✗'} {r['adapter'].ljust(w)}  "
              f"{r['expect']:5}  {r['actual']:5}  {','.join(r['actual_red']) or '—'}")
    print("\n判别力(每族都得红过也绿过):")
    for fam, d in disc.items():
        print(f"  {fam}  红 {len(d['red_in'])} 个 {d['red_in']}")

    out = REPO / "docs" / "evidence" / "browser_conformance" / "matrix.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"_what": "rt-sidecar-browser-v1 的 conformance 矩阵(真上游 + 真浏览器)",
         "_not_a_benchmark": "F0 自检;不计模型能力,不进 runs.jsonl",
         "task_id": TASK_ID, "profile_id": P.PROFILE_ID,
         "topology": topo, "jobs": len(_JOB_NONCES), "rows": rows,
         "discrimination_by_family": disc, "problems": problems,
         "ok": not problems and topo["ok"]},
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
