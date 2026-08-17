"""WH-PILOT-1 批判据检查器(预注册 §5 的机器判;2026-08-17)。

**逐发归因不在这里重写**:直接复用 `hb_batch_criteria` 的 `classify_run`
与 `_facts_of` —— 同一批发次跑在同一族任务上,归因语义必须逐字同一份。
抄一份过来 = 两份判据慢慢分叉,而分叉那天没人会发现(#43 同型)。
本脚本只加 WH 独有的那一层:**臂间比较**。

判据(预注册 §5,冻结):
  护栏(先判,任一破即整批 INVALID):假 PASS 不增、回归破坏不增、
  策略违规不增、隐藏面被动(INSTRUMENT_TAMPERED)恒 0;
  GAIN            H2 比 H0 多 ≥1 个有效 PASS;
  ADVERSE         H0 严格优于 H2(PASS 数更多,或逐发 delta ≥2/3 更优);
  WEAK_GAIN       H2 逐发 delta 严格优于 H0 且 ≥2/3 成立(D7 批准的替代
                  判据 —— 原文"Public Test 正向增量"在 HB 族上不可测:
                  公开面 = 宿主回归套件,基线即全绿,没有正向增量的余地);
  NO_GAIN_IN_PILOT 其余。**措辞铁律**:它不得被写成"harness 无增益"
                  (n=3、单题、低于方案文档 §7.3 最小规模)。

**配对规则(附录一第 1 条,开跑前记)**:预注册写的是"逐发",实现为
**按臂内执行序配对**(guided 第 k 发 vs minimal 第 k 发)。配对本身是
任意的 —— 两臂的发次相互独立,不存在天然对子 —— 所以规则必须在开跑前
写死,否则事后按最有利的配法排一遍就是 p-hacking。

自证(与 C0/C1 金丝雀同纪律):`--selftest` 吃同批 F0 电池的**两臂各四
形态**,任一形态判错即自宣无效退出 2;外加合成臂级分支活检。

用法:
  .venv/bin/python scripts/wh_batch_criteria.py <batch> [--json] [--selftest]
  .venv/bin/python scripts/wh_batch_criteria.py <batch> --f0-batch WH-PILOT1-F0 --selftest
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hb_batch_criteria import (  # noqa: E402 — 复用而非复制(见模块头)
    RUNS_LEDGER,
    RUNS_DIR,
    _delta_nodes_of,
    _facts_of,
    classify_run,
)

ARMS = ("guided", "minimal")
GAIN, WEAK_GAIN, NO_GAIN, ADVERSE, INVALID = (
    "GAIN", "WEAK_GAIN", "NO_GAIN_IN_PILOT", "ADVERSE", "INVALID")

HOST_EVIDENCE = (Path(__file__).resolve().parents[1]
                 / "docs" / "evidence" / "hb1_hosts" / "prepare-hb1.json")


def leak_guardrail(task_key: str = "sqlglot-8042") -> dict:
    """§5 第四条护栏:隐藏泄漏 = 0。

    这条**不是逐发量**,别的三条是 —— 泄漏与否取决于交付树里有没有答案
    指纹,是建包时的结构性事实。正因如此它最容易退化成散文承诺:证据躺在
    一份 json 里,出判决时没人重读。所以出判决必须重验两件:

      ① 建包时的扫描结论(且扫描器**自证有牙** —— 种进去的答案要报中,
         干净树要零命中;拔光牙的扫描器也报"零命中");
      ② 部署树至今**逐字节未变** —— 否则那份结论说的是另一棵树。

    量法复用原件(`blind_attack_admission._digest_tree`,同 prepare_hb1_hosts):
    重算一份会在原件改动后静默漂移(M58a 钉的就是这条)。
    """
    checked: dict = {"task_key": task_key}
    bad: list[str] = []
    try:
        hosts = json.loads(HOST_EVIDENCE.read_text(encoding="utf-8"))["hosts"]
    except (OSError, KeyError, json.JSONDecodeError) as e:
        return {"breaches": [f"读不到建包证据 {HOST_EVIDENCE}:{e}"], "checked": checked}
    if task_key not in hosts:
        # 认不出的任务不许判"没泄漏" —— 没证据 ≠ 有证据说没有
        return {"breaches": [f"建包证据里没有 {task_key},泄漏护栏无从重验"],
                "checked": checked}

    h = hosts[task_key]
    leak = h.get("leak") or {}
    checked.update(hits=len(leak.get("hits") or []),
                   effective_fingerprints=leak.get("effective"),
                   clean_zero=leak.get("clean_zero"),
                   planted_detected=leak.get("planted_detected"),
                   selfcheck_ok=leak.get("selfcheck_ok"))
    if checked["hits"]:
        bad.append(f"部署树命中答案指纹 ×{checked['hits']}")
    if not leak.get("clean_zero"):
        bad.append("建包扫描未报干净树零命中")
    if not (leak.get("planted_detected") and leak.get("selfcheck_ok")):
        bad.append("泄漏扫描器未自证有牙(种植件未报中)—— 零命中不可采信")
    if not checked["effective_fingerprints"]:
        bad.append("有效指纹数为 0 —— 等于没扫")

    import blind_attack_admission as _baa   # 原件量法,不复制
    bench = Path(h["bench_dir"])
    now = _baa._digest_tree(bench / "host")
    checked["digest_match"] = (now == h.get("host_digest"))
    if not checked["digest_match"]:
        bad.append("部署树摘要与建包时不符 —— 那份泄漏结论说的是另一棵树")
    return {"breaches": bad, "checked": checked}


def _guardrail_breaches(per_arm: dict) -> list[str]:
    """护栏 = 方案文档 §7.5 的"同时必须满足"四条。

    方向都是"**不增**"而不是"为零":回归破坏在两臂都可能自然发生,
    要判的是引导有没有**换来更多**破坏。假 PASS 与隐藏面被动是绝对线
    —— 它们一旦非零,这一批的读数就不可信,与增益无关。
    """
    g, m = per_arm["guided"], per_arm["minimal"]
    bad = []
    for arm in ARMS:
        if per_arm[arm]["false_pass"]:
            bad.append(f"{arm} 臂出现假 PASS ×{per_arm[arm]['false_pass']}")
        if per_arm[arm]["instrument_tampered"]:
            bad.append(f"{arm} 臂出现量具被动 ×{per_arm[arm]['instrument_tampered']}")
    if g["regression_broken"] > m["regression_broken"]:
        bad.append(f"引导臂回归破坏更多({g['regression_broken']}>"
                   f"{m['regression_broken']})—— 增益不许拿回归换")
    if g["denied"] > m["denied"]:
        bad.append(f"引导臂策略违规更多({g['denied']}>{m['denied']})")
    return bad


def judge_arms(runs: list[dict], *, extra_breaches: list[str] | None = None) -> dict:
    """臂间比较(纯函数)。runs 每项:arm/order/verdict/j3/delta_green/…

    与 IO 分离,钉死直接喂事实字典 —— 判据的每一支都必须能被单独考。
    `extra_breaches` 是逐发读数以外的护栏(泄漏那条),由 IO 侧算好传入:
    它照样先于增益判,纯函数这边不为它开后门。
    """
    per_arm = {a: {"n": 0, "passes": 0, "delta": [], "false_pass": 0,
                   "regression_broken": 0, "denied": 0, "instrument_tampered": 0}
               for a in ARMS}
    for r in runs:
        arm = r["arm"]
        if arm not in per_arm:
            return {"verdict": INVALID, "reasons": [f"未知臂:{arm!r}"],
                    "per_arm": per_arm, "pairs": []}
        s = per_arm[arm]
        s["n"] += 1
        s["passes"] += int(bool(r["is_pass"]))
        s["delta"].append((r["order"], r["delta_green"]))
        s["false_pass"] += int(bool(r.get("false_pass")))
        s["denied"] += int(r.get("denied") or 0)
        s["regression_broken"] += int(r["j3"] == "REGRESSION_BROKEN")
        s["instrument_tampered"] += int(r["j3"] == "INSTRUMENT_TAMPERED")

    reasons: list[str] = []
    if per_arm["guided"]["n"] != per_arm["minimal"]["n"] or per_arm["guided"]["n"] == 0:
        return {"verdict": INVALID,
                "reasons": [f"两臂发次数不等或为零:"
                            f"guided={per_arm['guided']['n']} "
                            f"minimal={per_arm['minimal']['n']}"],
                "per_arm": per_arm, "pairs": []}

    breaches = _guardrail_breaches(per_arm) + list(extra_breaches or [])
    # 配对:臂内按执行序排位,第 k 位对第 k 位(规则见模块头,开跑前冻结)
    gd = [d for _, d in sorted(per_arm["guided"]["delta"])]
    md = [d for _, d in sorted(per_arm["minimal"]["delta"])]
    pairs = [{"k": k + 1, "guided": a, "minimal": b,
              "winner": "guided" if a > b else "minimal" if b > a else "tie"}
             for k, (a, b) in enumerate(zip(gd, md))]
    g_wins = sum(1 for p in pairs if p["winner"] == "guided")
    m_wins = sum(1 for p in pairs if p["winner"] == "minimal")
    need = (2 * len(pairs) + 2) // 3          # ≥2/3 向上取整(n=3 → 2)

    out = {"per_arm": per_arm, "pairs": pairs, "pair_wins":
           {"guided": g_wins, "minimal": m_wins, "needed": need},
           "guardrail_breaches": breaches}
    if breaches:
        out.update(verdict=INVALID, reasons=breaches)
        return out

    gp, mp = per_arm["guided"]["passes"], per_arm["minimal"]["passes"]
    if gp > mp:
        reasons.append(f"引导臂有效 PASS 多 {gp - mp} 个({gp} vs {mp})")
        out.update(verdict=GAIN, reasons=reasons)
        return out
    if mp > gp:
        reasons.append(f"最小臂有效 PASS 反而多 {mp - gp} 个({mp} vs {gp})")
        out.update(verdict=ADVERSE, reasons=reasons)
        return out
    if m_wins >= need:
        reasons.append(f"最小臂逐发 delta 更优 {m_wins}/{len(pairs)}(需 {need})")
        out.update(verdict=ADVERSE, reasons=reasons)
        return out
    if g_wins >= need:
        reasons.append(f"引导臂逐发 delta 更优 {g_wins}/{len(pairs)}(需 {need})")
        out.update(verdict=WEAK_GAIN, reasons=reasons)
        return out
    reasons.append(f"PASS 数相同({gp}={mp}),逐发 delta 无一方达 {need}/"
                   f"{len(pairs)}(引导 {g_wins} / 最小 {m_wins})")
    reasons.append("措辞铁律:本判决不得写成「harness 无增益」—— n=3、单题、"
                   "低于方案文档 §7.3 最小规模")
    out.update(verdict=NO_GAIN, reasons=reasons)
    return out


# ------------------------------------------------------------------ IO 侧

def _rows_of(batch: str) -> list[dict]:
    rows = [json.loads(ln) for ln in RUNS_LEDGER.read_text().splitlines() if ln]
    return [r for r in rows if r.get("batch") == batch]


def _entry(r: dict) -> dict:
    facts = _facts_of(r["run_id"], _delta_nodes_of(r["task_id"]))
    cls = classify_run(facts)
    rd = RUNS_DIR / r["run_id"]
    report = json.loads((rd / "report.json").read_text(encoding="utf-8"))
    replay_ok = "status=PASS" in (report.get("replay") or "")
    is_pass = facts["verdict"] == "PASS_ADAPTED" and replay_ok
    return {
        "run_id": r["run_id"], "model": r.get("model"),
        # 臂只认台账里落的**生效值**,不认环境变量或人工记忆
        "arm": r.get("harness_mode"), "order": int(r.get("run_order") or 0),
        "verdict": facts["verdict"], "j3": cls["j3"],
        "delta_green": cls["delta_green"], "delta_total": cls["delta_total"],
        "is_pass": is_pass,
        # 假 PASS = 判了 PASS 却过不了干净重放,或与 cap 红名单自相矛盾
        "false_pass": (facts["verdict"] == "PASS_ADAPTED"
                       and (not replay_ok or cls["j3"] == "HARNESS_FAILURE")),
        "denied": (report.get("agent") or {}).get("denied") or 0,
        "rounds_used": (report.get("repair") or {}).get("rounds_run"),
    }


def is_smoke_model(model: object) -> bool:
    """脚本模型判别 —— **计分池与自证池的分界线,一份实现两处调用**。

    取值**宁宽勿窄**,因为两个方向的代价不对称:
      · 漏判一发假发次 → 脚本 fake-positive 进计分池,直接造出假 GAIN,
        而它看起来和真 PASS 一模一样,没有任何下游检查会响;
      · 多判一发真发次 → 两臂发次数不等 → INVALID,当场就响。
    故不用 `startswith("fake")`(判别名一改就漏),改为子串命中。
    """
    m = str(model or "").strip().lower()
    if not m:
        # 缺 model 的台账行两个池都不该进:计分要它是真模型,自证要它是脚本,
        # 而这一行两样都说不出。静默归入任一池都是替它编一个身份 —— 炸。
        raise ValueError("台账行缺 model —— 既不能计分也不能当自证素材")
    return "fake" in m or "scripted" in m


def adjudicate(batch: str) -> dict:
    rows = _rows_of(batch)
    if not rows:
        raise SystemExit(f"台账里没有批 {batch} 的发次")
    scored = [_entry(r) for r in rows if not is_smoke_model(r.get("model"))]
    smoke = [_entry(r) for r in rows if is_smoke_model(r.get("model"))]
    out = {"batch": batch, "runs": scored, "smoke_controls": smoke}
    # 泄漏护栏在**每次出判决时**重验(见 leak_guardrail 的理由);任务键
    # 由台账 task_id 去掉 hb 前缀得到,认不出就让护栏自己报"无从重验",
    # 不在这里替它猜一个。
    tids = {r.get("task_id") for r in rows}
    leak = leak_guardrail(sorted(tids)[0].removeprefix("hb1-") if len(tids) == 1
                          else "<多任务批,泄漏护栏需逐任务重验>")
    out["leak_guardrail"] = leak
    out["arm_judgement"] = (
        judge_arms(scored, extra_breaches=leak["breaches"]) if scored else
        {"verdict": "NO_SCORED_RUNS", "reasons": leak["breaches"],
         "per_arm": {}, "pairs": []})
    return out


# 臂级分支活检:活体发次覆盖不到的支(GAIN/ADVERSE/INVALID)用合成事实钉。
def _r(arm, order, delta, *, is_pass=False, j3="DESIGN_MISMATCH", **kw):
    return {"arm": arm, "order": order, "delta_green": delta, "is_pass": is_pass,
            "j3": j3, "verdict": "PASS_ADAPTED" if is_pass else "FAIL", **kw}


SYNTHETIC_ARM_BRANCHES: list[tuple[str, list[dict]]] = [
    (GAIN, [_r("guided", 1, 5, is_pass=True), _r("minimal", 1, 0)]),
    (ADVERSE, [_r("guided", 1, 0), _r("minimal", 1, 5, is_pass=True)]),
    (WEAK_GAIN, [_r("guided", 1, 3), _r("guided", 2, 2), _r("guided", 3, 0),
                 _r("minimal", 1, 1), _r("minimal", 2, 0), _r("minimal", 3, 0)]),
    (ADVERSE, [_r("guided", 1, 0), _r("guided", 2, 0), _r("guided", 3, 1),
               _r("minimal", 1, 2), _r("minimal", 2, 3), _r("minimal", 3, 1)]),
    (NO_GAIN, [_r("guided", 1, 0), _r("guided", 2, 0), _r("guided", 3, 0),
               _r("minimal", 1, 0), _r("minimal", 2, 0), _r("minimal", 3, 0)]),
    # 1/3 达不到 2/3 的线 —— 边界必须钉,否则"多赢一发"会被读成 WEAK_GAIN
    (NO_GAIN, [_r("guided", 1, 3), _r("guided", 2, 0), _r("guided", 3, 0),
               _r("minimal", 1, 0), _r("minimal", 2, 0), _r("minimal", 3, 0)]),
    (INVALID, [_r("guided", 1, 5, is_pass=True, false_pass=True),
               _r("minimal", 1, 0)]),
    (INVALID, [_r("guided", 1, 0, j3="INSTRUMENT_TAMPERED"), _r("minimal", 1, 0)]),
    (INVALID, [_r("guided", 1, 0, j3="REGRESSION_BROKEN"), _r("minimal", 1, 0)]),
    (INVALID, [_r("guided", 1, 0, denied=3), _r("minimal", 1, 0, denied=0)]),
    (INVALID, [_r("guided", 1, 0), _r("guided", 2, 0), _r("minimal", 1, 0)]),
]

F0_EXPECT = {
    "fake-scripted:positive": (None, "PASS_ADAPTED"),
    "fake-scripted:control:nc_null_submission": ("IMPL_INCOMPLETE", "FAIL"),
    "fake-scripted:control:nc_regression_break": ("REGRESSION_BROKEN", "FAIL"),
    "fake-scripted:control:nc_instrument_tamper": ("INSTRUMENT_TAMPERED", "FAIL"),
}


def selftest(smoke: list[dict]) -> list[str]:
    """自证:F0 电池**两臂各四形态**各归各位 + 合成臂级分支活检。

    两臂都要考 —— 最小臂是新执行路径,只在引导臂上自证过的检查器,对最小
    臂等于没自证过(这正是 §8 前置要求两臂各跑一遍电池的理由)。
    """
    bad: list[str] = []
    for arm in ARMS:
        seen = set()
        for e in [s for s in smoke if s["arm"] == arm]:
            want = F0_EXPECT.get(e["model"])
            if not want:
                continue
            seen.add(e["model"])
            if (e["j3"], e["verdict"]) != want:
                bad.append(f"[{arm}] {e['run_id']}: 判成 ({e['j3']},{e['verdict']}),"
                           f"期望 {want}")
        for m in F0_EXPECT:
            if m not in seen:
                bad.append(f"[{arm}] 自证素材缺席:该臂没有 {m} 的 F0 发次")
    for want, runs in SYNTHETIC_ARM_BRANCHES:
        got = judge_arms(runs)["verdict"]
        if got != want:
            bad.append(f"合成臂级分支判错:期望 {want},判成 {got}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch")
    ap.add_argument("--f0-batch", default=None,
                    help="F0 电池所在批(自证素材;缺省 = 与计分批同批)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    result = adjudicate(a.batch)
    if a.selftest:
        smoke = result["smoke_controls"]
        if a.f0_batch:
            smoke = [_entry(r) for r in _rows_of(a.f0_batch)
                     if is_smoke_model(r.get("model"))]
        bad = selftest(smoke)
        if bad:
            print("SELFTEST INVALID:\n" + "\n".join(bad))
            return 2
        print(f"SELFTEST OK: 两臂 F0 四形态各归各位 + "
              f"{len(SYNTHETIC_ARM_BRANCHES)} 支合成臂级分支活检全对")
    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        for e in result["runs"] + result["smoke_controls"]:
            print(f"{e['run_id']}  arm={e['arm']:8s} {e['verdict']:14s} "
                  f"j3={e['j3']}  delta={e['delta_green']}/{e['delta_total']}")
        j = result["arm_judgement"]
        print(f"\n臂间判决:{j['verdict']}")
        for r in j.get("reasons", []):
            print(f"  - {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
