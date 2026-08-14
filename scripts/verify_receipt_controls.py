#!/usr/bin/env python3
"""回执不可伪造性的**零模型**证明 —— 第 6 步。

一个正控 + 七个负控,每个都是**能跑的实现**,不是桩。全程不调用任何模型:
sidecar 是真进程、上游是真包(`markdown-it-py`)、渲染是真执行、回执是真
签名。这样得出的结论不依赖任何模型的表现,也就不会被"这次模型比较笨"或
"这次模型特别会钻空子"污染。

**判定纪律(#43 定的,这里逐条执行)**:

1. 正控必须**全过**。一道诚实实现也过不了的判据不是判据,是墙。
2. 每个负控必须**红在它自己那一处**。红一片不算数 —— 那证明不了是哪道
   判据抓住了它,也就分不清"我有四道判据"和"我有一道判据起了四个名字"。
3. 脚本先**自证**:把验证器换成"永远放行",正控与负控必须一起变绿(说明
   本脚本确实在读验证结果,而不是在读自己的期望值)。

用法::

    .venv/bin/python scripts/verify_receipt_controls.py
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
CONTROLS_DIR = REPO / "benchmarks" / "v2" / "receipt_controls"
sys.path.insert(0, str(CONTROLS_DIR))

from repoproof.receipts.ledger import (  # noqa: E402
    LEDGER_NAME,
    new_key,
    new_nonce,
)
from repoproof.receipts.model import CANON_JSON, CANON_TEXT_SQUASH, digest_of  # noqa: E402
from repoproof.receipts.verify import (  # noqa: E402
    digest_equality_predicate,
    register_adoption,
    verify_receipts,
)

TASK_ID = "receipt-control-harness"

# 三份作业。刻意用真 Markdown 结构(标题/强调/代码/列表),让朴素重实现
# 得到"像但不一样"的输出 —— 如果作业简单到人人渲染结果都一致,采纳判据
# 就测不出任何东西。
JOBS = [
    {"request_nonce": "rn-1",
     "text": "# Title\n\nSome **bold** and `code`.\n\n- a\n- b\n"},
    {"request_nonce": "rn-2",
     "text": "## Second\n\nA [link](http://x) and *em*.\n\n1. one\n2. two\n"},
    {"request_nonce": "rn-3",
     "text": "Plain paragraph with a\nsoft break.\n\n> quote\n"},
]


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _expected_units(sidecar_mod) -> list[dict]:
    """harness 侧独立算出的待办清单 —— U3 的分母。

    注意它**不来自 adapter**:输入摘要由 harness 按自己知道的作业内容算,
    adapter 说什么都不影响。分母若由被测方提供,"象征性调一次"就永远抓不住。
    """
    return [{"request_nonce": j["request_nonce"],
             "input_digest": digest_of({"text": j["text"]}, canon=CANON_JSON)}
            for j in JOBS]


def run_one(control_path: Path, *, replay_source: Path | None = None,
            replay_key: bytes | None = None) -> dict:
    """跑一个控制组,返回它的四道谓词结果。"""
    import sidecar as sidecar_mod

    ctrl = _load(control_path)
    work = Path(tempfile.mkdtemp(prefix="rp-receipt-"))
    ledger = work / LEDGER_NAME
    key, nonce = new_key(), new_nonce()
    run_id = f"receipt-ctl-{control_path.stem}"

    needs_replay = getattr(ctrl, "NEEDS_REPLAYED_LEDGER", False)
    if needs_replay:
        if replay_source is None or not replay_source.is_file():
            raise SystemExit("nc5 需要一本上一轮的台账,但没有 —— 先跑正控")
        # 把上一轮的台账原样搬进本轮位置,并**沿用上一轮的密钥**。
        #
        # 为什么要沿用:密钥若每 run 现摇,重放的旧账在 `U1.signature` 就先
        # 挂了,`U1.run_nonce` 那道**根本走不到** —— 这条负控考的就变成了
        # 密钥轮换,不是 nonce 绑定(与 M46a 同型:考的是代码顺带处理的情形,
        # 不是判据真正管的情形)。沿用同一把密钥,才是把 nonce 单独拎出来
        # 考:签名完全有效、链完整、内容真实,唯一不对的是它不属于这一次运行。
        #
        # 现实里密钥也未必每 run 换 —— 若将来改成按会话或按 profile 持有,
        # 挡重放的就只剩 nonce 这一道。所以它必须自己站得住。
        key = replay_key or key
        shutil.copy2(replay_source, ledger)
        os.environ["REPOPROOF_REPLAY_SOURCE"] = str(ledger)

    if getattr(ctrl, "NEEDS_LEDGER_PATH", False):
        # 故意把台账路径与上游身份交给 nc8。现实里 agent 够不到 `runs/`,
        # 这里给它,是为了把**签名**这一道单独拎出来考 —— 让伪造者除签名外
        # 样样做对(链算对、身份填对、摘要对得上),看那一道自己站不站得住。
        ident = sidecar_mod._upstream_identity()
        os.environ.update({
            "REPOPROOF_FORGE_TARGET": str(ledger),
            "REPOPROOF_FORGE_RUN_ID": run_id,
            "REPOPROOF_FORGE_RUN_NONCE": nonce,
            "REPOPROOF_FORGE_UPSTREAM": json.dumps({
                "distribution": ident.distribution, "version": ident.version,
                "artifact_hash": ident.artifact_hash,
                "import_module": ident.import_module, "symbol": sidecar_mod.SYMBOL}),
        })

    handle = sidecar_mod.serve(ledger, key, run_id, nonce, token="tok-" + nonce[:8])
    try:
        from client import Sidecar

        # adapter 只拿到 `agent_env()` 给的东西:端点与令牌。台账路径、
        # 签名密钥、run_nonce 一概不给 —— 那是这套拓扑约束的全部力气所在。
        env = handle.agent_env()
        delivery = ctrl.run(Sidecar(env["REPOPROOF_SIDECAR_URL"],
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
        required_symbols={sidecar_mod.SYMBOL},
        required_upstream={"distribution": sidecar_mod.DISTRIBUTION,
                           "import_module": sidecar_mod.IMPORT_MODULE,
                           "artifact_hash": sidecar_mod._upstream_identity().artifact_hash},
        expected_units=_expected_units(sidecar_mod), delivery=delivery,
        expected_receipt_count=written)

    return {"_key": key,                     # 只在内存里传给 nc5,不落盘
            "control": control_path.stem,
            "expect": getattr(ctrl, "EXPECT", "?"),
            "expect_red": sorted(getattr(ctrl, "EXPECT_RED", set())),
            "actual": "PASS" if v.ok else "FAIL",
            "actual_red": sorted({f.check for f in v.failed()}),
            "verdict": v.as_dict(), "ledger": str(ledger)}


def find_problems(rows: list[dict]) -> list[str]:
    """纪律 1 与 2 的判定 —— **单独一个函数,好让钉死直接考它**。

    为什么要抽出来:它原本内联在 `main()` 里,于是钉死只能去读落盘证据。
    可落盘证据与这道检查是**互为冗余**的两条路 —— 只要现实里没有不匹配,
    把这道检查整个掏掉也没人看得出来(变异闸门 M50a 当场抓到了这一点)。
    抽出来之后,钉死可以喂它一行合成的错配,直接考它认不认得出。

    这与 `selfcheck()` 是同一条纪律的两半:自证管"验证器在不在验",
    本函数管"矩阵的判定在不在判"。
    """
    problems: list[str] = []
    for r in rows:
        if r["actual"] != r["expect"]:
            problems.append(f"{r['control']}:期望 {r['expect']},实际 {r['actual']}")
        elif r["expect"] == "FAIL":
            # 纪律 2:必须红在它自己那一处,红一片不算数
            if set(r["actual_red"]) != set(r["expect_red"]):
                problems.append(
                    f"{r['control']}:红的位置不对 —— 期望 {r['expect_red']},"
                    f"实际 {r['actual_red']}")
    return problems


def _register_predicate():
    register_adoption(TASK_ID, digest_equality_predicate(
        lambda dv: [digest_of(x, canon=CANON_TEXT_SQUASH) for x in (dv or [])]))


def selfcheck() -> list[str]:
    """自证:把采纳谓词换成"永远放行",负控 nc3 必须由 FAIL 变 PASS。

    不做这一步的话,本脚本报出来的"七个负控全被抓住"分不清是**验证器真的
    抓住了**,还是**脚本在读自己的期望值**。nc3 是最好的探针 —— 它只在 U4
    上红,换掉 U4 就该整个变绿。"""
    bad = []
    from repoproof.receipts import verify as V

    _register_predicate()
    strict = run_one(CONTROLS_DIR / "controls" / "nc3_ignores_return.py")
    if strict["actual"] != "FAIL":
        bad.append("自证(1):严格谓词下 nc3 竟然过了 —— 验证器根本没在验")

    V.register_adoption(TASK_ID, lambda receipts, delivery: (True, "自证用:永远放行"))
    loose = run_one(CONTROLS_DIR / "controls" / "nc3_ignores_return.py")
    if loose["actual"] != "PASS":
        bad.append(f"自证(2):放行谓词下 nc3 仍未过,红在 {loose['actual_red']} —— "
                   "说明脚本读的不是验证结果,或 U4 之外还有别的东西在拦它")
    _register_predicate()
    return bad


def main() -> int:
    bad = selfcheck()
    if bad:
        print("自证不过,拒绝出数:", file=sys.stderr)
        for b in bad:
            print("  -", b, file=sys.stderr)
        return 3
    print("自证通过(2 条:严格谓词拦得住 nc3,放行谓词放得过 nc3)\n")

    rows = [run_one(CONTROLS_DIR / "controls" / "positive.py")]
    replay_source = Path(rows[0]["ledger"])

    replay_key = rows[0].pop("_key")
    for p in sorted((CONTROLS_DIR / "controls").glob("nc*.py")):
        rows.append(run_one(p, replay_source=replay_source, replay_key=replay_key))
    for r in rows:
        r.pop("_key", None)          # 密钥绝不进证据文件

    problems = find_problems(rows)

    # 纪律 4:**每一族谓词都得红过也绿过**。一道在所有负控上都红的判据,
    # 与"恒红"无从区分,它在本实验里不携带任何信息;一道从不红的判据则
    # 根本没被这批负控考到 —— 两种都必须当场说出来,不许闷着。
    families = ("U1", "U2", "U3", "U4")
    discrimination = {}
    for fam in families:
        red_in = [r["control"] for r in rows
                  if any(c.startswith(fam + ".") for c in r["actual_red"])]
        green_in = [r["control"] for r in rows
                    if not any(c.startswith(fam + ".") for c in r["actual_red"])]
        discrimination[fam] = {"red_in": red_in, "green_in": green_in}
        if not red_in:
            problems.append(f"{fam}:没有任何控制组让它报红 —— 这批负控没考到它")
        if not green_in:
            problems.append(f"{fam}:在所有控制组上都红 —— 与'恒红'无从区分")

    # 逐个 check 的暴露情况(不作闸门,只作透明度:哪些子判据从没被考过)。
    # 光报一个名单会被读成"这里有缺口",所以同时说清它在哪儿被覆盖 ——
    # 有单元钉死覆盖的是**分工问题**(这批负控没考到),没有覆盖的才是缺口。
    all_checks = sorted({c["check"] for r in rows for c in r["verdict"]["findings"]})
    never_red = [c for c in all_checks
                 if not any(c in r["actual_red"] for r in rows)]
    COVERED_BY_UNIT_PIN = {
        "U1.chain": "tests/test_upstream_receipt.py::"
                    "test_hash_chain_detects_tampering_without_any_key / "
                    "test_deleting_a_line_breaks_the_chain",
        "U1.version": "tests/test_upstream_receipt.py::"
                      "(RECEIPT_VERSION 由 U1.version 判;无版本漂移的现实负控)",
        "U1.invocation_unique": "tests/test_upstream_receipt.py::"
                                "(_duplicates;本批负控不产生重复 id)",
        "U2.upstream_identity": "tests/test_upstream_receipt.py::"
                                "test_same_name_package_with_different_bytes_is_caught"
                                " —— 要在本矩阵里考它,得让 **sidecar 自己**加载假包,"
                                "而 sidecar 是 harness 拥有的,不在本轮威胁模型内",
    }
    uncovered = [c for c in never_red if c not in COVERED_BY_UNIT_PIN]

    w = max(len(r["control"]) for r in rows)
    print(f"{'控制组'.ljust(w)}  期望   实际   红在哪")
    for r in rows:
        mark = "✓" if r["actual"] == r["expect"] else "✗"
        print(f"{mark} {r['control'].ljust(w)}  {r['expect']:5}  {r['actual']:5}  "
              f"{','.join(r['actual_red']) or '—'}")

    out = REPO / "docs" / "evidence" / "receipt_controls" / "matrix.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"_what": "上游执行回执的零模型正负控矩阵(第 6 步)",
         "_discipline": ["正控必须全过", "每个负控必须红在它自己那一处",
                         "脚本先自证:放行谓词下 nc3 必须变绿"],
         "task_id": TASK_ID, "jobs": len(JOBS), "rows": rows,
         "discrimination_by_family": discrimination,
         "checks_never_exercised_by_any_control": never_red,
         "of_which_covered_by_unit_pins": {c: COVERED_BY_UNIT_PIN[c]
                                           for c in never_red if c in COVERED_BY_UNIT_PIN},
         "of_which_uncovered_anywhere": uncovered,
         "problems": problems, "ok": not problems},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if problems:
        print("\n不合格:")
        for p in problems:
            print("  -", p)
        print(f"\n证据:{out}")
        return 1
    print("\n判别力(每族都得红过也绿过):")
    for fam, d in discrimination.items():
        print(f"  {fam}  红 {len(d['red_in'])} 组 {d['red_in']}")
    if never_red:
        print(f"\n本批负控没考到的子判据:{never_red}")
        print(f"  其中有单元钉死覆盖的:{[c for c in never_red if c in COVERED_BY_UNIT_PIN]}")
        print(f"  **哪儿都没覆盖的(这才是缺口)**:{uncovered or '无'}")
    print(f"\n1 正控 + {len(rows) - 1} 负控全部符合预期,且各红各的位置。\n证据:{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
