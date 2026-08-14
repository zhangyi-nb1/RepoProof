"""Runtime Profile 的晋级判据 —— 一个 profile 凭什么往上走一级。

生命周期(沿用 `docs/RUNTIME-MODES.md`)::

    experimental → candidate → qualified → default → deprecated

每一级问的是**不同的问题**,所以判据也不同。这一点是整份设计的骨架:

    → candidate   机制自己站不站得住?**零模型可判。**
                  拓扑成立、假阳侧不误杀、负控各红各位、变异全捕。
    → qualified   真模型跑得动吗?**必须有真实发次,零模型判不了。**
                  参考实现能过不代表模型能过 —— 我们的 adapter 是照着判据
                  写的,那叫"出题人自己会做",不叫"题目可解"。
    → default     该不该成为默认?**机器判不了,明说判不了。**
                  这是取舍(成本、语义、对既有发次的影响),要人来定并留痕。

**证据缺失一律拒绝晋级,不假设。** 与"缺正控清单显式失败""U3 没有分母就
判不过"同一条纪律:一个查不到证据就默认放行的闸门,和没有闸门的区别只在于
它会让人误以为有闸门。

冻结判据(先写判据与反例;措辞此后不改):

- **G1 拓扑成立**(仅 sidecar)。反例:上游其实 agent 够得着 → 后面的回执与
  负控全是装饰,"它没来敲门"会被读成偷懒,其实是它不需要。
- **G2 假阳侧不误杀**。正控必须过。反例:判据成墙 —— 墙拦不住洗白,只拦得住
  诚实实现(LESSONS #44)。
- **G3 负控各红各位**。每条负控的实际红点集与它自己声明的期望集逐一相等。
  反例:红一片也算数 → 分不清"四道判据"和"一道判据起了四个名字"。
- **G4 判别力**。每族谓词都得红过也绿过。反例:某族恒红 → 与"永远报错"
  无从区分,不携带信息。
- **G5 变异全捕**,且守护该机制的那些条目确实在场。反例:捕获率 100% 但
  登记簿里根本没有守这套机制的条目 —— 那个 100% 与本 profile 无关。
- **G6 真实发次**(→ qualified)。至少两个不同模型 profile、各自预注册、
  且**至少一发诚实通过**。反例:只有我们自己的参考 adapter 过了 → 那是
  出题人自己会做,不是题目可解。
- **G7 无未决的假通过**(→ qualified)。该 profile 上若有被裁定
  `INVALIDATED_FALSE_PASS` 且未修复的发次,不得晋级。
- **G8 default 不由机器判**。反例:凑齐几个数就自动设默认 → 把一个取舍
  伪装成一个测量。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from repoproof.execution.runtime_profiles import RuntimeProfile, profile

LIFECYCLE_ORDER = ("experimental", "candidate", "qualified", "default", "deprecated")

# → qualified 的最低真实发次要求。**先写死,再看数据**(防事后挪门槛)。
MIN_MODEL_PROFILES = 2
MIN_HONEST_PASSES = 1

# G5 要求在场的变异条目前缀 —— 守护回执与 conformance 这套机制的那些。
# 写成前缀而不是全名,是为了让同族新增条目自动纳入;写成**必须在场**而不是
# "只要捕获率 100%",是因为一个空登记簿的捕获率也是 100%。
REQUIRED_MUTATION_PREFIXES = ("M49", "M50", "M52")


@dataclass
class Check:
    id: str
    ok: bool
    detail: str


@dataclass
class PromotionVerdict:
    profile_id: str
    frm: str
    to: str
    ok: bool
    machine_decidable: bool
    checks: list[Check] = field(default_factory=list)

    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def as_dict(self) -> dict:
        return {"profile_id": self.profile_id, "from": self.frm, "to": self.to,
                "ok": self.ok, "machine_decidable": self.machine_decidable,
                "checks": [{"id": c.id, "ok": c.ok, "detail": c.detail}
                           for c in self.checks]}


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return None


def _mutation_evidence_at_head(repo: Path) -> tuple[dict | None, str]:
    """取**当前 HEAD 那一次**的变异证据。返回 (证据, 说明)。

    两处曾经想当然、都被现场打脸:

    1. **不按 mtime 取"最新"**。变异闸门在临时 git worktree 里跑,checkout
       出来的文件 mtime 全都一样 —— "最新"其实是随机取。
    2. **不接受别的 commit 的证据**。证据文件按 HEAD 命名正是为了这个:
       上一个 commit 跑绿了,不代表这个 commit 还绿。拿旧证据给新代码背书,
       与"改完不重跑"没有区别。
    """
    import subprocess

    d = repo / "docs" / "evidence" / "mutation_gate"
    if not d.is_dir():
        return None, "没有变异证据目录"
    head = subprocess.run(                                   # noqa: S603 固定 argv
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False).stdout.strip()
    if not head:
        return None, "取不到 HEAD —— 无从判断证据是不是这份代码的"
    f = d / f"{head[:12]}.json"
    if not f.is_file():
        return None, (f"HEAD {head[:12]} 上没有变异证据 —— 先跑 "
                      "scripts/mutation_gate.py。上一个 commit 跑绿了不代表"
                      "这个 commit 还绿")
    return _read_json(f), f"HEAD {head[:12]}"


# ------------------------------------------------------------------ 判据
def _check_conformance(repo: Path, p: RuntimeProfile) -> list[Check]:
    """G1–G4:零模型的机制证明。证据来自 conformance 矩阵。"""
    out: list[Check] = []
    m = _read_json(repo / "docs" / "evidence" / "sidecar_conformance" / "matrix.json")
    if m is None:
        return [Check("G1-G4.evidence", False,
                      "没有 conformance 矩阵证据 —— 跑 scripts/sidecar_conformance.py。"
                      "查不到证据一律拒绝晋级,不假设")]
    if m.get("profile_id") != p.id:
        return [Check("G1-G4.evidence", False,
                      f"矩阵证的是 {m.get('profile_id')!r},不是 {p.id!r} —— "
                      "别人的体检报告不能拿来给自己晋级")]

    topo = m.get("topology") or {}
    bad_topo = [f["check"] for f in topo.get("findings", []) if not f["ok"]]
    out.append(Check("G1.topology", bool(topo.get("ok")) and not bad_topo,
                     "拓扑四条全过" if topo.get("ok") else f"拓扑不成立:{bad_topo}"))

    rows = m.get("rows") or []
    pos = [r for r in rows if r.get("expect") == "PASS"]
    out.append(Check("G2.no_false_kill", bool(pos) and all(r["actual"] == "PASS" for r in pos),
                     f"{len(pos)} 个正控全过" if pos and all(r["actual"] == "PASS" for r in pos)
                     else "正控没过或根本没有正控 —— 判据成墙,或从没验过误杀侧"))

    negs = [r for r in rows if r.get("expect") == "FAIL"]
    misplaced = [r["adapter"] for r in negs
                 if sorted(r.get("actual_red", [])) != sorted(r.get("expect_red", []))]
    out.append(Check("G3.reds_where_declared", bool(negs) and not misplaced,
                     f"{len(negs)} 条负控各红各位" if negs and not misplaced
                     else f"红点错位或没有负控:{misplaced}"))

    disc = m.get("discrimination_by_family") or {}
    dead = [f for f, d in disc.items() if not d.get("red_in") or not d.get("green_in")]
    out.append(Check("G4.discrimination", bool(disc) and not dead,
                     f"{len(disc)} 族谓词都红过也绿过" if disc and not dead
                     else f"这些族不携带信息(恒红或从没红过):{dead}"))
    return out


def _check_mutations(repo: Path, *, evidence: dict | None = None) -> Check:
    """G5:变异全捕,且守护这套机制的条目确实在场。

    `evidence` 显式传入时直接用它(钉死喂合成数据走这条);否则按 HEAD 取。
    做成显式参数而不是"目录里只有一个文件就用那个",是因为后者是**隐式
    行为** —— 真仓里有几十个文件所以严格,合成目录里只有一个所以宽松,
    两种行为差别很大却没人写出来。
    """
    why = "显式传入"
    if evidence is None:
        evidence, why = _mutation_evidence_at_head(repo)
    ev = evidence
    if ev is None:
        return Check("G5.mutation", False, f"拿不到变异证据({why})—— 查不到就拒绝晋级")
    ids = [r.get("id", "") for r in (ev.get("results") or [])]
    present = {pre for pre in REQUIRED_MUTATION_PREFIXES
               if any(i.startswith(pre) for i in ids)}
    missing = set(REQUIRED_MUTATION_PREFIXES) - present

    # 全捕的判据**不读 `capture_rate` 那个字符串**,直接看逃逸与过期。
    # 读字符串要解析("101/101" / "100%" / 1.0 都可能),而解析失败时最容易
    # 顺手当成通过 —— 那正是"闸门看起来在,其实没在"的经典形态。
    #
    # `escaped`/`stale` 现在是 id 列表(实测),历史上可能是计数。两种都认,
    # **认不出的一律判不过** —— 这里绝不能有"看不懂就放行"的分支。
    def _count(v, name: str):
        if isinstance(v, bool):          # bool 是 int 的子类,先挡掉
            return None
        if isinstance(v, int):
            return v
        if isinstance(v, (list, tuple)):
            return len(v)
        return None

    escaped, stale = _count(ev.get("escaped"), "escaped"), _count(ev.get("stale"), "stale")
    if escaped is None or stale is None:
        return Check("G5.mutation", False,
                     f"变异证据里读不出逃逸/过期(escaped={ev.get('escaped')!r}, "
                     f"stale={ev.get('stale')!r})—— 读不出就判不过,不猜")
    ok = escaped == 0 and stale == 0 and not missing
    return Check("G5.mutation", ok,
                 f"逃逸 0、过期 0(共 {len(ids)} 条,{why}),守护条目 "
                 f"{sorted(present)} 在场" if ok
                 else f"逃逸 {escaped}、过期 {stale};缺守护条目 {sorted(missing)} —— "
                      "空登记簿的逃逸数也是 0,所以还要查在场")


def _check_real_runs(repo: Path, p: RuntimeProfile) -> list[Check]:
    """G6/G7:→ qualified 必须有真实发次。零模型判不了这一级。"""
    out: list[Check] = []
    ledger = repo / "benchmarks" / "v2" / "runs.jsonl"
    rows = []
    if ledger.is_file():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except Exception:                            # noqa: BLE001
                    pass
    mine = [r for r in rows if r.get("runtime_profile") == p.id
            and not str(r.get("model", "")).startswith("fake")]

    models = {r.get("model") for r in mine if r.get("model")}
    out.append(Check("G6.model_profiles", len(models) >= MIN_MODEL_PROFILES,
                     f"{len(models)} 个模型 profile 跑过:{sorted(models)}"
                     if len(models) >= MIN_MODEL_PROFILES
                     else f"只有 {len(models)} 个模型跑过(要求 ≥{MIN_MODEL_PROFILES})——"
                          "参考 adapter 能过只说明出题人自己会做,不说明题目可解"))

    # 诚实通过 = 台账 PASS 且没有被裁定作废
    adj = {}
    ap = repo / "benchmarks" / "v2" / "adjudications.jsonl"
    if ap.is_file():
        for line in ap.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    a = json.loads(line)
                    adj[a.get("run_id")] = a
                except Exception:                            # noqa: BLE001
                    pass
    passes = [r for r in mine
              if str(r.get("verdict", "")).startswith("PASS")
              and adj.get(r.get("run_id"), {}).get("counts_as_pass") is not False]
    out.append(Check("G6b.honest_pass", len(passes) >= MIN_HONEST_PASSES,
                     f"{len(passes)} 发诚实通过" if len(passes) >= MIN_HONEST_PASSES
                     else f"零发诚实通过(要求 ≥{MIN_HONEST_PASSES})—— "
                          "没有真实模型过过这道题,'可解'只是我们自己的断言"))

    false_pass = [r["run_id"] for r in mine
                  if adj.get(r.get("run_id"), {}).get("effective_verdict")
                  == "INVALIDATED_FALSE_PASS"]
    out.append(Check("G7.no_open_false_pass", not false_pass,
                     "无未决假通过" if not false_pass
                     else f"该 profile 上有被裁定的假通过,未修复不得晋级:{false_pass}"))
    return out


# ------------------------------------------------------------------ 入口
def evaluate_promotion(profile_id: str, *, repo: Path,
                       to: str | None = None) -> PromotionVerdict:
    """判一个 profile 能不能晋到下一级(或指定的目标级)。

    `machine_decidable=False` 时 `ok` 恒为 False —— **判不了就是不通过**,
    不是"暂且通过"。要往那一级走,得有人做决定并留痕。
    """
    p = profile(profile_id)
    frm = p.lifecycle
    if to is None:
        i = LIFECYCLE_ORDER.index(frm)
        to = LIFECYCLE_ORDER[i + 1] if i + 1 < len(LIFECYCLE_ORDER) else frm

    checks: list[Check] = []
    machine = True

    if to == "candidate":
        if p.topology == "sidecar":
            checks += _check_conformance(repo, p)
        else:
            checks.append(Check("G1.topology", True,
                                "in_process 拓扑无 sidecar 可核 —— 本组判据不适用"))
        checks.append(_check_mutations(repo))
    elif to == "qualified":
        if p.lifecycle == "experimental":
            checks.append(Check("G0.no_skipping", False,
                                f"{p.id} 还在 experimental —— 不得跳级到 qualified。"
                                "candidate 那一级问的是'机制站不站得住',跳过去等于"
                                "拿真实发次去替机制背书"))
        checks += _check_real_runs(repo, p)
    elif to == "default":
        machine = False
        checks.append(Check("G8.not_machine_decidable", False,
                            "'该不该成为默认'是取舍(成本、语义、对既有发次的影响),"
                            "不是测量。机器判不了 —— 要人来定并在 RUNTIME-MODES.md "
                            "留痕。凑几个数就自动设默认,等于把取舍伪装成测量"))
    elif to == "deprecated":
        machine = False
        checks.append(Check("G8.not_machine_decidable", False,
                            "废弃同样是决定,不是测量"))
    else:
        checks.append(Check("G0.unknown_target", False, f"未知目标级别:{to}"))

    return PromotionVerdict(profile_id=p.id, frm=frm, to=to,
                            ok=machine and bool(checks) and all(c.ok for c in checks),
                            machine_decidable=machine, checks=checks)
