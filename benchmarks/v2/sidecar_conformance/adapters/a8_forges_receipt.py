"""**伪造 receipt** → FAIL。除签名外样样做对。

刻意做成最强的伪造者:知道台账路径(现实里 agent 够不到 `runs/`,这里
故意给它,好把签名单独拎出来考)、把 `prev_sha256` 算对(**链是完整的**)、
上游身份/符号/input digest/两个 nonce 全部填对、output digest 填成自己产物
的摘要。

它唯一做不到的是签名 —— 密钥不在它的环境里。与 a7 成一对:a7 链断而签名
有效,a8 签名无效而链完整。两条合起来才说明这两道各自都在干活。
"""
import hashlib
import json
import os
import time
from pathlib import Path

EXPECT = "FAIL"
# `U1.count` 同样红:它往台账里塞了执行方没写过的行。两道各管一件 ——
# 计数管"条数对不对",签名管"这一行是不是执行方签的"。伪造者两样都躲不过。
EXPECT_RED = {"U1.signature", "U1.count", "U3.coverage", "U4.adoption"}
NEEDS_LEDGER_PATH = True


def _own(text: str) -> str:
    return text.strip() + "\n#canary:3333333333333333\n"


def run(sidecar, jobs):
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
    for i, j in enumerate(jobs):
        mine = _own(j["text"])
        out.append(mine)
        raw = ledger.read_bytes().splitlines() if ledger.is_file() else []
        prev = hashlib.sha256(raw[-1]).hexdigest() if raw else None
        r = Receipt(
            receipt_version=RECEIPT_VERSION, run_id=run_id,
            upstream=UpstreamIdentity(up["distribution"], up["version"],
                                      up["artifact_hash"], up["import_module"]),
            operation=Operation(up["symbol"], f"forged-{i}"),
            input=Payload(digest_of({"text": j["text"]}, canon=CANON_JSON)),
            output=Payload(digest_of(mine, canon=CANON_TEXT_SQUASH)),
            runtime=Runtime("sidecar", "pid=0:boot=0:py=/fake",
                            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            profile_id="rt-sidecar-canary-v1"),
            binding=Binding(nonce, j["request_nonce"]),
            prev_sha256=prev, receipt_signature="f" * 64)
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(r.to_json() + "\n")
    return out
