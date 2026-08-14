"""**改 receipt(删行)** → FAIL。只破链不破签名。

它先拿 `title_only` 探一次路(契约要求集之外的符号,留在台账里会让 U2 报红),
再老实渲染并如实交付,最后把探路那一行删掉想抹平痕迹。

签名不覆盖 `prev_sha256`(判据 R8,有意的),所以删行是**唯一**能只破链、
不破签名的改法 —— 改字段会把签名一起破坏,"链"那道就永远躲在"签名"后面
考不出来。
"""
import os
from pathlib import Path

EXPECT = "FAIL"
EXPECT_RED = {"U1.chain", "U1.count"}
NEEDS_LEDGER_PATH = True


def run(sidecar, jobs):
    sidecar.invoke(jobs[0]["text"], request_nonce="probe",
                   symbol="browser_use.BrowserSession.title_only")
    out = [sidecar.invoke(j["text"], request_nonce=j["request_nonce"])["result"]
           for j in jobs]
    ledger = Path(os.environ["REPOPROOF_FORGE_TARGET"])
    lines = ledger.read_text(encoding="utf-8").splitlines()
    ledger.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")
    return out
