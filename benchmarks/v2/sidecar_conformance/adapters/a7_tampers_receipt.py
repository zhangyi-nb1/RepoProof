"""**改 receipt** → FAIL。这条走的是**删行**,不是改字段。

为什么是删行:改字段会把签名一起破坏(签名覆盖内容),于是"链"这一道
永远躲在"签名"后面,考不出来。**删行是唯一能只破链、不破签名的改法**
—— 签名不覆盖 `prev_sha256`(判据 R8,那是有意的),所以剩下每一行的
签名都还有效,断的只有链。

剧本:它先拿 `fingerprint` 探了一次路(那是契约要求集之外的符号,留在
台账里会让 U2 报红),然后老老实实 normalize 了三份作业并如实交付,
最后回头**把探路那一行删掉**,想把痕迹抹平。

于是:U2 绿(证据被删了)、U3 绿、U4 绿、签名全绿 —— **只有台账完整性
那两道红**。这正是它该考的:没有链和计数,删掉不方便的回执就是免费的。

它与 a8 是一对:
    a7 删行   → 签名有效、链断        → U1.chain + U1.count
    a8 新增行 → 链完整、签名无效      → U1.signature
合成一条会掩盖掉其中一道判据从没被考过。
"""
import os
from pathlib import Path

EXPECT = "FAIL"
EXPECT_RED = {"U1.chain", "U1.count"}
NEEDS_LEDGER_PATH = True


def run(sidecar, jobs):
    # 先探一次路:契约要求集之外的符号
    sidecar.invoke(jobs[0]["text"], request_nonce="probe",
                   symbol="canary_upstream.transform.fingerprint")
    out = []
    for j in jobs:
        r = sidecar.invoke(j["text"], request_nonce=j["request_nonce"])
        out.append(r["result"])

    # 回头删掉探路那一行(它在最前面,删中间/前部才会断链)
    ledger = Path(os.environ["REPOPROOF_FORGE_TARGET"])
    lines = ledger.read_text(encoding="utf-8").splitlines()
    ledger.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")
    return out
