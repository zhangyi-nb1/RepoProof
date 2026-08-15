#!/usr/bin/env python3
"""任务级回执核验 —— **harness 侧**,不在 oracle 里。

为什么必须在这里而不在 oracle 里:回执台账与签名密钥都在 harness 手上,
agent 的会话里根本没有。要把这一步塞进 oracle,就得把密钥递进会话 ——
而递进去之后,"agent 伪造不了回执"这条性质当场作废。

所以分工是死的:

    oracle(会话内)   验**行为**:接口对不对、有没有泄漏、宿主回归还在不在
    本脚本(harness)  验**采纳**:U1 执行方可信 / U2 上游身份 / U3 输入覆盖
                                  / U4 结果进了输出链

`expected_units` 由 harness 按**它自己下发的那批待抽取项**算出,不读 agent
的任何自述 —— 分母若来自被测方,"象征性调一次"永远抓不住(U3 的教训)。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from repoproof.receipts.model import (  # noqa: E402
    CANON_JSON,
    CANON_TEXT_SQUASH,
    digest_of,
)
from repoproof.receipts.verify import (  # noqa: E402
    register_adoption,
    verify_receipts,
)

TASK_ID = "t3-sidecar-page-facts-v1"


# ---------------------------------------------------------------- A1 的结构上限
#
# 2026-08-15 第二宿主设计评审查出,记在这里而不是别处 —— 它是**这个函数**的
# 上限,读判据的人必须在同一屏里看见:
#
#     U4 比的是 `digest(交付的产出) == digest(回执的产出)`。
#     上游算得对、被测方**自己也算得对**时,两个 digest 恒等。
#     所以 U3/U4 判的是"有没有按待办项数发出等量、输入对得上的 RPC",
#     **不是"这个值是不是从上游流过来的"**。
#
# 换句话说:一个"自己算出正确答案、同时把 RPC 也照常发一遍"的实现,
# 在 U1–U4 上与诚实实现**逐项不可分辨**。这不是实现缺陷,是判据的结构上限。
#
# T3-SIDECAR 上这条被**任务的偶然性质**挡住了,不是被机制挡住的:
# fixture 的答案只能靠真渲染拿到(flex 3/5/7/11/13 在 1000px 里的定点结果),
# 而待抽取项的 nonce 在 oracle 起跑那一刻现摇(`rotate_items`,审查 B4)——
# 算不出、也预取不了。**换一道答案可独立算出的题,这条上限立刻暴露。**
#
# 正解是**差分注入**:让 harness 侧的上游返回一个受 run_key 扰动的值
# (扰动量只有上游知道),采纳判据改成"交付逐项等于**扰动后**的值"。
# 那时"自己算"与"用上游"才真正可分辨。待立项:A1-MECH-SELFTEST。
# 在它做完之前,任何引用 U4 的地方都要带上这条边界。


def _make_per_unit_adoption(units: list[dict]):
    """本任务的采纳谓词:**逐项对应 + 绑定 harness 的待办清单**。

    三个洞同源,一次补上(2026-08-15 可搬运性审查,实测三条都零红通过):

    **B1 洗白**。U3 按 `(nonce, input_digest)` 配对,而原来的 U4 只按 nonce
    配 —— 于是**两条判据可以由两张不同的回执分别满足**:对契约给的 URL 调
    一次(喂饱 U3),再用**同一个 nonce** 对自造的 `data:` URL 调一次,交后者
    的产物(喂饱 U4)。sidecar 就此沦为"任意内容的签名机"。修法:只认
    `input.digest` 等于该项**应有输入**的那些回执。

    **B2 少交**。原来的分母是 `len(delivery)` —— 来自被测方。全调、只交一半,
    照过。这与本文件自己写过的"分母若来自被测方,象征性调一次永远抓不住"
    是同一个错,只是从 U3 搬到了 U4。修法:分母用 harness 的清单。

    **B3 空产出**。`CANON_TEXT_SQUASH` 删光空白,于是 `""` / `"  \n"` /
    缺 `facts` 键三者同摘要;而 worker 找不到 `#answer` 时返回 `""` 且不抛,
    sidecar 照样签一张 `digest_of("")` 的合法回执。两边一对,空对空,过。
    修法:空产出不是采纳凭证。另:`facts` 不是字符串时**判红并归因被测方**,
    不许抛成 `RECEIPT_VERIFIER_ERROR`(那会把被测方的畸形工件记成 harness
    自己坏了)。

    **不能改成"每 nonce 只许一张回执"**:oracle 的 h1/h2/h3 各提交一次作业,
    诚实实现天然每 nonce ≥3 张。那样改是误杀。

    口径仍用 `text/whitespace-squashed`:容得下"去首尾空白、统一换行"这类
    无害整理(正控刻意做了),容不下换一份内容。
    """
    exp = {u["request_nonce"]: u["input_digest"] for u in units}

    def _pred(receipts, delivery) -> tuple[bool, str]:
        if not exp:
            # 与 U3 缺清单同一条纪律(verify.py):没有分母就没有判定。
            # 默认放行会让将来某次漏传参数静默退回今天这个形状。
            return False, ("harness 没有给出待办清单 —— 采纳无从判定。"
                           "不给一律判不过,不猜。")
        if not delivery:
            return False, "交付为空 —— 空交付不算采纳"

        # B1:只认**输入对得上**的回执。同 nonce 但喂了别的输入的那些,
        # 是被测方自己造的内容,不能替它背书。
        by_nonce: dict[str, list[str]] = {}
        for r in receipts:
            rn = r.binding.request_nonce
            if r.input.digest != exp.get(rn):
                continue
            by_nonce.setdefault(rn, []).append(r.output.digest)

        # B2:分母是 harness 的清单,不是"你交了几项"
        delivered = {i.get("request_nonce") for i in delivery}
        missing = sorted(set(exp) - delivered)
        if missing:
            return False, (f"交付漏了 {missing} —— 采纳只成立了一部分,"
                           "而契约要的是每一项都用上游的产物")

        bad = []
        for item in delivery:
            rn = item.get("request_nonce", "")
            if rn not in exp:
                bad.append(f"{rn}:不属于本批下发的项")
                continue
            want = by_nonce.get(rn)
            if not want:
                bad.append(f"{rn}:没有**输入对得上**的回执 —— 真因见 U3")
                continue
            raw = item.get("facts", "")
            if not isinstance(raw, str):
                # B3:归因被测方,不抛。抛出去会被记成 RECEIPT_VERIFIER_ERROR,
                # 把被测方交的畸形工件写成 harness 自己坏了。
                bad.append(f"{rn}:facts 是 {type(raw).__name__},交付形状不合规")
                continue
            if not raw.strip():
                bad.append(f"{rn}:交付的事实为空 —— 空产出不是采纳凭证")
                continue
            if digest_of(raw, canon=CANON_TEXT_SQUASH) not in want:
                bad.append(f"{rn}:交付的事实不是它那张回执的产出")
        if bad:
            return False, f"{len(bad)}/{len(delivery)} 项采纳不成立:{bad[:3]}"
        return True, f"{len(delivery)}/{len(exp)} 项各自对上自己那张回执"

    return _pred


def register(units: list[dict]) -> None:
    """登记本任务的采纳谓词。**必须带 harness 的待办清单** —— 那是分母。"""
    register_adoption(TASK_ID, _make_per_unit_adoption(units))


def expected_units(items: list[dict]) -> list[dict]:
    """U3 的分母 —— 按 harness 下发的那批项算,不读 agent 自述。"""
    return [{"request_nonce": it["request_nonce"],
             "input_digest": digest_of({"text": it["url"]}, canon=CANON_JSON)}
            for it in items]


def verify(*, ledger: Path, key: bytes, run_id: str, run_nonce: str,
           items: list[dict], delivery: list[dict], receipts_written: int,
           required_symbols: set[str], required_upstream: dict):
    register(expected_units(items))
    return verify_receipts(
        ledger, key=key, run_id=run_id, run_nonce=run_nonce, task_id=TASK_ID,
        required_symbols=required_symbols, required_upstream=required_upstream,
        expected_units=expected_units(items), delivery=delivery,
        expected_receipt_count=receipts_written)


def main() -> int:
    """命令行用法留给 host-run 接线之后;现在只做自检式说明。"""
    print(__doc__)
    print(f"task_id = {TASK_ID}")
    print("接线状态:**已接进 host-run**(host_guided 在 oracle 之后、会话销毁"
          "之前取交付并调本模块核验);任务级矩阵 "
          "scripts/t3_sidecar_conformance.py 也调它。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
