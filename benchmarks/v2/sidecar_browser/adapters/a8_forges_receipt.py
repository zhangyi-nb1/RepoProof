"""**伪造 receipt(增行)** → FAIL。除签名外样样做对。

给它台账路径(现实里 agent 够不到 `runs/`)、把 `prev_sha256` 算对、身份/
符号/两个 nonce/输入输出摘要全部填对。唯一做不到的是签名 —— 密钥不在它的
环境里。与 a7 成一对:a7 链断而签名有效,a8 签名无效而链完整。
"""
import hashlib
import json
import os
import time
from pathlib import Path

EXPECT = "FAIL"
EXPECT_RED = {"U1.signature", "U1.count", "U3.coverage", "U4.adoption"}
NEEDS_LEDGER_PATH = True


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
        mine = f"{j['request_nonce']}|forged-numbers"
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
                            profile_id="rt-sidecar-browser-v1"),
            binding=Binding(nonce, j["request_nonce"]),
            prev_sha256=prev, receipt_signature="f" * 64)
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(r.to_json() + "\n")
    return out
