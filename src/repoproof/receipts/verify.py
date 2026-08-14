"""回执验证 —— 四个各自可判定的谓词,任一不过即整体不过。

为什么要拆成四个而不是一个布尔:因为"没通过"的四种原因在决策上完全不同,
合成一个 `upstream_used: false` 会把它们抹平。这与 E 轨终结报告拒绝把六步
一律记成 Null 是同一条道理。

    U1 执行方可信   签名过 + 链完整 + run_nonce 是本次的
    U2 上游身份对   发行版/版本/artifact_hash/符号 都在契约要求集里
    U3 输入对得上   每个待办单元各有一张 input digest 对得上的回执
    U4 结果进了输出链  最终交付确实由回执的 output 派生 —— **采纳谓词**

U4 是整套设计的要害,也是唯一不能通用化的一件事:"最终输出"是什么,只有
任务自己知道。所以采纳谓词按任务登记,**没登记就判不过**(`NO_ADOPTION_
PREDICATE`),不许默认放行。理由和"缺正控清单显式失败"一样 —— 默认放行
会让一套只证明了 U1–U3 的回执看起来像证明了全部四件,而 U1–U3 全过、U4
不过,正是用户举的那段代码的形状:

    browser_use.do_something(...)          # U1 U2 U3 全过
    result = my_own_http_implementation()  # U4 不过
    return result
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from repoproof.receipts.ledger import read_ledger, verify_chain, verify_signatures
from repoproof.receipts.model import RECEIPT_VERSION, Receipt


@dataclass
class Finding:
    check: str
    ok: bool
    detail: str
    invocation_id: str = ""


@dataclass
class ReceiptVerdict:
    ok: bool
    findings: list[Finding] = field(default_factory=list)
    receipts: int = 0

    def failed(self) -> list[Finding]:
        return [f for f in self.findings if not f.ok]

    def as_dict(self) -> dict:
        return {"ok": self.ok, "receipts": self.receipts,
                "findings": [{"check": f.check, "ok": f.ok, "detail": f.detail,
                              "invocation_id": f.invocation_id} for f in self.findings]}


# ---------------------------------------------------------------- 采纳谓词登记
#
# 签名:predicate(receipts, delivery) -> (ok, detail)
#   receipts —— 本 run 通过 U1–U3 的回执
#   delivery —— 任务侧交上来的最终产物(内容由任务定义)
#
# **登记表按任务 id**;查不到就是 NO_ADOPTION_PREDICATE。
AdoptionPredicate = Callable[[list[Receipt], object], tuple[bool, str]]
_ADOPTION: dict[str, AdoptionPredicate] = {}


def register_adoption(task_id: str, fn: AdoptionPredicate) -> None:
    _ADOPTION[task_id] = fn


def adoption_predicate(task_id: str) -> AdoptionPredicate | None:
    return _ADOPTION.get(task_id)


def digest_equality_predicate(extract: Callable[[object], list[str]]) -> AdoptionPredicate:
    """最常用的一种 U4:交付里逐单元的摘要必须**等于**某张回执的 output digest。

    注意是"等于",不是"包含"。包含式判据挡不住用户举的那种绕过 —— 把上游
    结果里的一个标记原样抄进自己的产物即可满足"包含",而实质内容仍是自写的
    (#43 坑三:常量可以被搬运)。等于式要求实质内容本身就是上游产出的那份,
    搬运一个标记做不到。

    诚实边界:严格相等对**做过合理后处理**的诚实实现是误杀。所以回执在
    `output.digest` 上带了规范化口径(`canon`),任务应当选一个既容得下
    排版差异、又容不下"换一份内容"的口径(如 `text/whitespace-squashed`)。
    口径选松了,这条判据就退化成搬运即可满足 —— 那是任务的责任,不是本
    模块能替它决定的。

    **另一条边界,实测踩到过(2026-08-15,T3-SIDECAR 的 nc3)**:它判的是
    "交付里每一项的摘要**在**回执 output 的集合里",是**集合成员**不是逐项
    对应。于是"一次调用充抵所有项"过得去 —— 只调一次拿到 A 的结果,把它
    当作 A 和 B 一起交,两项都落在集合里,U4 照绿(当时只有 U3 报红)。

    要挡住它,任务得自己写**逐项对应**的谓词:交付项与回执按
    `binding.request_nonce` 配对,每项只认它自己那张。做得到这件事的信息
    只有任务有(哪一项对应哪个 nonce),所以本模块给不出通用版本 ——
    这正是采纳谓词按任务登记的理由。参见
    `scripts/verify_task_receipts.py::_per_unit_adoption`。"""

    def _pred(receipts: list[Receipt], delivery: object) -> tuple[bool, str]:
        want = {r.output.digest for r in receipts}
        units = extract(delivery)
        if not units:
            return False, "交付里没有可核对的单元 —— 空交付不算采纳"
        missing = [u for u in units if u not in want]
        if missing:
            return False, (f"{len(missing)}/{len(units)} 个交付单元的摘要与任何一张回执的 "
                           f"output 都对不上 —— 调用发生了,用的却是别的结果")
        return True, f"{len(units)}/{len(units)} 个交付单元逐一对上回执 output"

    return _pred


# ---------------------------------------------------------------- 四道谓词
def verify_receipts(
    ledger_path: Path,
    *,
    key: bytes,
    run_id: str,
    run_nonce: str,
    task_id: str,
    required_symbols: set[str],
    required_upstream: dict,
    expected_units: list[dict] | None = None,
    delivery: object = None,
    expected_receipt_count: int | None = None,
) -> ReceiptVerdict:
    """跑完 U1–U4。

    `expected_units`:harness 侧知道的待办单元,每个形如
    `{"request_nonce": ..., "input_digest": ...}`。它是 U3 的分母 ——
    **没有它就无法回答"象征性调用一次"**,因为一张回执看起来永远像"调过了"。

    `expected_receipt_count`:执行方自己数出来的条数,**在台账之外**。
    哈希链查得出改写/乱序/删中间行,**查不出尾部截断**(实测:删最后一行
    链校验照样通过)。不给这个数,砍尾巴就是免费的。
    """
    f: list[Finding] = []
    receipts = read_ledger(ledger_path)

    # ---- U1 执行方可信 ------------------------------------------------
    chain_ok, at, err = verify_chain(ledger_path)
    f.append(Finding("U1.chain", chain_ok, err or f"{len(receipts)} 条,链完整",
                     invocation_id="" if chain_ok else f"line {at}"))

    bad_sig = verify_signatures(receipts, key)
    f.append(Finding("U1.signature", not bad_sig,
                     "全部签名有效" if not bad_sig else f"签名无效:{bad_sig}"))

    wrong_run = [r.operation.invocation_id for r in receipts
                 if r.run_id != run_id or r.binding.run_nonce != run_nonce]
    f.append(Finding("U1.run_nonce", not wrong_run,
                     "全部绑定到本次 run" if not wrong_run
                     else f"回执来自别的 run(重放):{wrong_run}"))

    if expected_receipt_count is None:
        f.append(Finding("U1.count", False,
                         "调用方没有给出执行方实际写入的条数 —— **尾部截断不可检测**"
                         "(哈希链只证明留下的这些是连续的,证明不了没被砍尾巴)。"
                         "不给一律判不过,不猜。"))
    else:
        n = len(receipts)
        f.append(Finding("U1.count", n == expected_receipt_count,
                         f"执行方写了 {expected_receipt_count} 条,台账里 {n} 条"
                         + ("" if n == expected_receipt_count else " —— 对不上")))

    bad_ver = [r.operation.invocation_id for r in receipts
               if r.receipt_version != RECEIPT_VERSION]
    f.append(Finding("U1.version", not bad_ver,
                     f"receipt_version={RECEIPT_VERSION}" if not bad_ver
                     else f"版本不符:{bad_ver}"))

    dup = _duplicates([r.operation.invocation_id for r in receipts])
    f.append(Finding("U1.invocation_unique", not dup,
                     "invocation_id 无重复" if not dup else f"重复的 invocation_id:{dup}"))

    trusted = [r for r in receipts
               if r.signature_ok(key) and r.run_id == run_id
               and r.binding.run_nonce == run_nonce
               and r.receipt_version == RECEIPT_VERSION]

    # ---- U2 上游身份对 ------------------------------------------------
    bad_sym = [r.operation.invocation_id for r in trusted
               if r.operation.symbol not in required_symbols]
    f.append(Finding("U2.symbol", not bad_sym,
                     f"符号都在要求集 {sorted(required_symbols)} 内" if not bad_sym
                     else f"调了要求集之外的符号:{bad_sym}"))

    bad_up = []
    for r in trusted:
        for k, want in required_upstream.items():
            got = getattr(r.upstream, k, None)
            if want and got != want:
                bad_up.append(f"{r.operation.invocation_id}:{k}={got!r}≠{want!r}")
    f.append(Finding("U2.upstream_identity", not bad_up,
                     "发行版/版本/artifact_hash 全部对上" if not bad_up
                     else f"上游身份对不上:{bad_up}"))

    id_ok = [r for r in trusted
             if r.operation.symbol in required_symbols
             and all(not w or getattr(r.upstream, k, None) == w
                     for k, w in required_upstream.items())]

    # ---- U3 输入对得上(覆盖率;这一条挡"象征性调用一次") ---------------
    if expected_units is None:
        f.append(Finding("U3.coverage", False,
                         "harness 没有给出待办单元清单 —— 无从判断是不是只象征性"
                         "调了一次。不给清单一律判不过,不猜。"))
    else:
        by_nonce = {}
        for r in id_ok:
            by_nonce.setdefault(r.binding.request_nonce, []).append(r)
        uncovered = []
        for u in expected_units:
            hits = [r for r in by_nonce.get(u["request_nonce"], [])
                    if r.input.digest == u["input_digest"]]
            if not hits:
                uncovered.append(u["request_nonce"])
        f.append(Finding("U3.coverage", not uncovered,
                         f"{len(expected_units)} 个单元各有对得上的回执" if not uncovered
                         else f"{len(uncovered)}/{len(expected_units)} 个单元没有回执"
                              f"(或输入对不上):{uncovered}"))

    # ---- U4 结果进了输出链 --------------------------------------------
    pred = adoption_predicate(task_id)
    if pred is None:
        f.append(Finding("U4.adoption", False,
                         f"NO_ADOPTION_PREDICATE:任务 {task_id} 没有登记采纳谓词。"
                         "U1–U3 全过只证明'真上游被真的调用过',**没有**证明"
                         "它的结果进了最终输出 —— 那正是要防的那种绕过。"
                         "不许默认放行。"))
    else:
        ok, detail = pred(id_ok, delivery)
        f.append(Finding("U4.adoption", ok, detail))

    return ReceiptVerdict(ok=all(x.ok for x in f), findings=f, receipts=len(receipts))


def _duplicates(xs: list[str]) -> list[str]:
    seen, dup = set(), []
    for x in xs:
        if x in seen and x not in dup:
            dup.append(x)
        seen.add(x)
    return dup
