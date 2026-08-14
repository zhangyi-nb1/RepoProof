"""负控 8:**伪造一张回执塞进台账** —— 除签名外样样做对。

用户列的"伪造"那一种。这条刻意做成最强的伪造者:

- 它知道台账路径(现实里 agent 够不到 `runs/`,这里故意给它,好把签名这道
  单独拎出来考);
- 它读了台账,把 `prev_sha256` 算对了 —— **哈希链是完整的**;
- 上游身份、符号、input digest、request_nonce、run_nonce 全部填对;
- 输出摘要也填成它自己产物的摘要,于是采纳谓词都能对上。

它唯一做不到的是签名 —— 密钥不在它的环境里。所以这条必须**只红在
`U1.signature`**(以及由此级联的 U3/U4:不可信的回执不得参与后续判定)。

它与 nc5 是一对:nc5 签名有效而 nonce 不对,nc8 nonce 对而签名无效。两条
合起来才说明"这两道各自都在干活",而不是其中一道替另一道背了书。
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

EXPECT = "FAIL"
# `U1.count`(2026-08-14 新增)同样红:它塞了执行方没写过的行。
EXPECT_RED = {"U1.signature", "U1.count", "U3.coverage", "U4.adoption"}
NEEDS_LEDGER_PATH = True


def _own_render(text: str) -> str:
    return "".join(f"<em>{ln}</em>\n" for ln in text.splitlines() if ln.strip())


def run(sidecar, jobs):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
    from repoproof.receipts.model import (
        CANON_JSON,
        CANON_TEXT_SQUASH,
        RECEIPT_VERSION,
        Binding,
        Operation,
        Payload,
        Receipt,
        Runtime,
        UpstreamIdentity,
        digest_of,
    )

    ledger = Path(os.environ["REPOPROOF_FORGE_TARGET"])
    up = json.loads(os.environ["REPOPROOF_FORGE_UPSTREAM"])
    run_id = os.environ["REPOPROOF_FORGE_RUN_ID"]
    nonce = os.environ["REPOPROOF_FORGE_RUN_NONCE"]

    out = []
    for i, job in enumerate(jobs):
        html = _own_render(job["text"])
        out.append(html)

        raw = ledger.read_bytes().splitlines() if ledger.is_file() else []
        prev = hashlib.sha256(raw[-1]).hexdigest() if raw else None
        r = Receipt(
            receipt_version=RECEIPT_VERSION, run_id=run_id,
            upstream=UpstreamIdentity(up["distribution"], up["version"],
                                      up["artifact_hash"], up["import_module"]),
            operation=Operation(up["symbol"], f"forged-{i}"),
            input=Payload(digest_of({"text": job["text"]}, canon=CANON_JSON)),
            output=Payload(digest_of(html, canon=CANON_TEXT_SQUASH)),
            runtime=Runtime("sidecar", "pid=0:boot=0:py=/fake",
                            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            profile_id="rt-sidecar-v1"),
            binding=Binding(nonce, job["request_nonce"]),
            prev_sha256=prev,
            receipt_signature="f" * 64)          # 唯一伪不出来的东西
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(r.to_json() + "\n")
    return out
