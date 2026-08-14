"""回执台账 —— **harness 拥有的独立事件通道**,不经 agent 之手。

用户 A0 原话:"最好通过独立事件通道记录,而不是 Agent 提交"。这条不是
锦上添花 —— 只要回执是 agent 交上来的,验证方看到的就永远是被测方愿意让
它看到的那一份,前面所有密码学绑定都白做。

三层防线,各挡各的:

1. **位置**:台账写进 `runs/<run_id>/`(见 `ledger_path_for`)。不是会话根
   的兄弟目录 —— agent 够得到 `..`(它本来就要读 `../upstream`),放那儿
   只靠位置挡不住;`runs/` 在主目录硬护栏的拒绝表里,agent 连写都发不出去。
2. **签名**:HMAC,密钥每 run 现摇,只在 harness 与 sidecar 之间传递,
   **绝不进 agent 环境、绝不进 trace/bundle**。就算 agent 够到了文件,
   写进去的行也验不过。
3. **哈希链**:每行带上一行的 sha256。事后改写(包括删行、换序)必被
   `verify_chain` 发现,而且这一层**不需要密钥** —— 拿到 bundle 的人可以
   自查,不必信任我们。

签名与哈希链是两件事,少哪个都留口子:只有签名,拿到密钥就能重写整本;
只有链,谁都能从头造一本自洽的假账。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from repoproof.receipts.model import Receipt

LEDGER_NAME = "upstream_receipts.jsonl"
KEY_ENV = "REPOPROOF_RECEIPT_KEY"        # 只在 harness → sidecar 之间;不入 agent 环境
NONCE_ENV = "REPOPROOF_RUN_NONCE"


def new_key() -> bytes:
    return os.urandom(32)


def new_nonce() -> str:
    return os.urandom(16).hex()


def ledger_path_for(run_dir: Path) -> Path:
    """台账落点 = **run 证据目录**,不是会话工作区。

    为什么不是会话根的兄弟目录:agent 够得到 `..`(它本来就要读
    `../upstream`),放那儿只靠"位置"挡不住。放进 `runs/<run_id>/` 则落在
    主目录硬护栏的拒绝表里(`xiangmu/repoproof`),agent 连写都发不出去。

    密钥**不落这里**,也不落任何进 bundle 的地方 —— 只在 harness 进程内存
    里活到验完为止。于是:
      · 运行期靠签名挡伪造(要密钥,agent 没有);
      · 事后靠哈希链挡改写(不要密钥,拿到 bundle 的第三方可自查)。
    两层的信任前提不同,这正是要的 —— 我们不要求别人信任我们保管密钥。
    """
    return Path(run_dir) / LEDGER_NAME


class ReceiptLedger:
    """追加写、哈希链、签名校验。**只有 harness/sidecar 侧构造它。**"""

    def __init__(self, path: Path, key: bytes) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._key = key
        self._prev: str | None = None
        if self.path.exists():
            ok, at, err = verify_chain(self.path)
            if not ok:
                # 与 TraceWriter 同一条纪律:往一本已断链的台账上追加,
                # 等于替篡改者把账做平。
                raise LedgerTampered(f"拒绝追加到已断链的回执台账(第 {at} 行):{err}")
            lines = self.path.read_bytes().splitlines()
            if lines:
                self._prev = hashlib.sha256(lines[-1]).hexdigest()

    def append(self, receipt: Receipt) -> Receipt:
        r = Receipt(**{**_shallow(receipt), "prev_sha256": self._prev}).sign(self._key)
        line = r.to_json()
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        self._prev = hashlib.sha256(line.encode("utf-8")).hexdigest()
        return r


class LedgerTampered(RuntimeError):
    pass


def _shallow(r: Receipt) -> dict:
    from repoproof.receipts.model import asdict_shallow

    return asdict_shallow(r)


def read_ledger(path: Path) -> list[Receipt]:
    p = Path(path)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(Receipt.from_dict(json.loads(line)))
    return out


def verify_chain(path: Path) -> tuple[bool, int, str]:
    """(链完整, 出问题的行号, 说明)。**不需要密钥** —— 任何人可自查。"""
    p = Path(path)
    if not p.is_file():
        return True, 0, "台账不存在(零回执)"
    prev: str | None = None
    for i, raw in enumerate(p.read_bytes().splitlines()):
        try:
            row = json.loads(raw)
        except Exception as e:                                   # noqa: BLE001
            return False, i, f"第 {i} 行不是 JSON:{e}"
        if row.get("prev_sha256") != prev:
            return False, i, (f"第 {i} 行的 prev_sha256 对不上"
                              f"(记的是 {row.get('prev_sha256')},实际应为 {prev})")
        prev = hashlib.sha256(raw).hexdigest()
    return True, 0, ""


def verify_signatures(receipts: list[Receipt], key: bytes) -> list[str]:
    """返回签名不过的 invocation_id —— 空列表才算干净。"""
    return [r.operation.invocation_id for r in receipts if not r.signature_ok(key)]
