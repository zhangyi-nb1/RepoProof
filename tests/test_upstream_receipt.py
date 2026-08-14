"""上游执行回执(A0)的钉死 —— 第 5 步。

用户 2026-08-14 的提醒是这套设计的出发点:回执**不能设计成调用日志**。

    browser_use.do_something(...)          # 调用证据成立
    result = my_own_http_implementation()  # 真正的结果来自别处
    return result

只记"调用发生过",上面这段全过。所以回执必须同时证明四件事,且**四件分开
判、分开报** —— 合成一个 `upstream_used: false` 会把四种完全不同的失败抹平。

冻结判据(先写判据与反例;措辞此后不改):

- R1 **四道谓词各自可判定**:U1 执行方可信 / U2 上游身份 / U3 输入覆盖 /
  U4 采纳。反例:合并成一个布尔 → 读的人分不清是"没调"、"调错了"、"只调了
  一次充数",还是"调了但没用",而这四种的修法完全不同。
- R2 **没有密钥就签不出**。反例:agent 自己造一张回执塞进台账即可过关 ——
  那整套绑定形同虚设。
- R3 **哈希链不需要密钥即可自查**。反例:验证只靠签名 → 拿到密钥的人可以
  重写整本账且自洽;而拿到 bundle 的第三方无法独立复核。
- R4 **断链时拒绝追加**。反例:往已被改过的台账上继续追加 → 等于替篡改者
  把账做平(与 `TraceWriter` 同一条纪律)。
- R5 **没登记采纳谓词 → 判不过**。反例:默认放行 → 一套只证明了 U1–U3 的
  回执看起来像证明了全部四件,而 U1–U3 全过 U4 不过正是用户举的那段代码。
- R6 **没有待办清单 → U3 判不过**。反例:没有分母就默认通过 → "象征性调用
  一次"永远抓不住,因为一张回执看起来永远像"调过了"。
- R7 **预览字段不参与判定**。反例:让 `preview` 影响结论 → 被测方通过控制
  预览内容就能影响判定。
- R8 **签名不含链字段**。反例:把 `prev_sha256` 算进签名 → 同一张回执换个
  写入位置签名就变,重放检测反而更难做。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repoproof.receipts.ledger import (
    LedgerTampered,
    ReceiptLedger,
    new_key,
    new_nonce,
    read_ledger,
    verify_chain,
)
from repoproof.receipts.model import (
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
from repoproof.receipts.verify import (
    digest_equality_predicate,
    register_adoption,
    verify_receipts,
)

UP = {"distribution": "browser-use", "version": "0.13.7",
      "artifact_hash": "sha256:realbytes"}
SYMS = {"browser_use.Agent.run"}


def _receipt(run_id: str, nonce: str, i: int, inp, out, req_nonce: str,
             *, symbol: str = "browser_use.Agent.run", upstream: dict | None = None):
    u = {**UP, **(upstream or {})}
    return Receipt(
        receipt_version=RECEIPT_VERSION, run_id=run_id,
        upstream=UpstreamIdentity(u["distribution"], u["version"],
                                  u["artifact_hash"], "browser_use"),
        operation=Operation(symbol, f"inv-{i}"),
        input=Payload(digest_of(inp), size=len(str(inp)), preview=str(inp)[:20]),
        output=Payload(digest_of(out, canon=CANON_TEXT_SQUASH), size=len(out),
                       preview=out[:20]),
        runtime=Runtime("sidecar", "pid=4242:boot=17:py=/x/python", "2026-08-14T00:00:00Z",
                        profile_id="rt-sidecar-v1"),
        binding=Binding(nonce, req_nonce))


def _world(tmp_path: Path, *, jobs=(("a", "RESULT A"), ("b", "RESULT B"))):
    """一套诚实实现的完整现场:台账 + 待办清单 + 交付。"""
    key, nonce = new_key(), new_nonce()
    path = tmp_path / "upstream_receipts.jsonl"
    led = ReceiptLedger(path, key)
    units, delivery = [], []
    for i, (job, out) in enumerate(jobs):
        rn = f"rn-{job}"
        inp = {"job": job}
        led.append(_receipt("run-1", nonce, i, inp, out, rn))
        units.append({"request_nonce": rn, "input_digest": digest_of(inp)})
        delivery.append(out)
    return {"key": key, "nonce": nonce, "path": path, "units": units,
            "delivery": delivery}


def _verify(w, *, task_id="t-recv", **over):
    kw = {"key": w["key"], "run_id": "run-1", "run_nonce": w["nonce"],
          "task_id": task_id, "required_symbols": SYMS, "required_upstream": UP,
          "expected_units": w["units"], "delivery": w["delivery"]}
    kw.update(over)
    return verify_receipts(w["path"], **kw)


@pytest.fixture(autouse=True)
def _register():
    register_adoption("t-recv", digest_equality_predicate(
        lambda dv: [digest_of(x, canon=CANON_TEXT_SQUASH) for x in dv]))


# ------------------------------------------------------------------ 正控
def test_honest_delivery_passes_all_four(tmp_path):
    """假阳侧正控:诚实实现必须全过 —— 一道谁都过不了的判据不是判据,是墙。"""
    v = _verify(_world(tmp_path))
    assert v.ok, [f.detail for f in v.failed()]
    assert {f.check for f in v.findings} >= {
        "U1.chain", "U1.signature", "U1.run_nonce", "U2.symbol",
        "U2.upstream_identity", "U3.coverage", "U4.adoption"}


# ------------------------------------------------------------------ R1
def test_the_four_proofs_report_separately(tmp_path):
    """R1:四件事分开判、分开报。

    反例:合成一个布尔 → 读的人分不清"没调"/"调错"/"充数"/"调了没用",
    而这四种的修法完全不同。"""
    w = _world(tmp_path)
    v = _verify(w, delivery=["MY OWN RESULT", "MY OWN RESULT 2"])
    failed = {f.check for f in v.failed()}
    assert failed == {"U4.adoption"}, (
        f"只有采纳该红,其余三件都成立(真上游确实被真的调过了):{failed}")


def test_calling_real_upstream_but_returning_own_result_is_caught(tmp_path):
    """用户举的那段代码:调用证据成立,结果却来自别处。**必须红在 U4。**"""
    w = _world(tmp_path)
    v = _verify(w, delivery=["my_own_http_implementation output"] * 2)
    assert not v.ok
    d = next(f.detail for f in v.failed() if f.check == "U4.adoption")
    assert "用的却是别的结果" in d


# ------------------------------------------------------------------ R2
def test_forged_receipt_without_the_key_fails(tmp_path):
    """R2:没有密钥就签不出 —— agent 自己造一张塞进台账,必须验不过。"""
    w = _world(tmp_path)
    forged = _receipt("run-1", w["nonce"], 99, {"job": "c"}, "FAKE", "rn-c")
    forged = Receipt(**{**_shallow(forged), "receipt_signature": "0" * 64})
    with w["path"].open("a", encoding="utf-8") as fh:
        fh.write(forged.to_json() + "\n")
    v = _verify(w)
    assert not v.ok
    assert any(f.check == "U1.signature" and not f.ok for f in v.findings)


def test_signing_with_a_different_key_fails(tmp_path):
    """R2 的另一面:用别的密钥签也不行(不是"有签名就行")。"""
    w = _world(tmp_path)
    r = _receipt("run-1", w["nonce"], 98, {"job": "d"}, "X", "rn-d").sign(new_key())
    assert not r.signature_ok(w["key"])


# ------------------------------------------------------------------ R3 / R4
def test_hash_chain_detects_tampering_without_any_key(tmp_path):
    """R3:改写台账必被发现,而且**不需要密钥** —— 第三方可自查。"""
    w = _world(tmp_path)
    lines = w["path"].read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0])
    row["output"]["digest"] = "json/sort_keys+utf8:" + "f" * 64
    lines[0] = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    w["path"].write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, at, err = verify_chain(w["path"])          # 没传密钥
    assert not ok and at == 1, (ok, at, err)


def test_deleting_a_line_breaks_the_chain(tmp_path):
    """R3:删行也是篡改 —— 只查"每行自洽"抓不住删除。"""
    w = _world(tmp_path, jobs=(("a", "A"), ("b", "B"), ("c", "C")))
    lines = w["path"].read_text(encoding="utf-8").splitlines()
    del lines[1]
    w["path"].write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, _, _ = verify_chain(w["path"])
    assert not ok


def test_refuses_to_append_to_a_broken_ledger(tmp_path):
    """R4:往断链的台账上追加 = 替篡改者把账做平。必须拒绝。"""
    w = _world(tmp_path)
    lines = w["path"].read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0])
    row["run_id"] = "run-999"
    lines[0] = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    w["path"].write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(LedgerTampered):
        ReceiptLedger(w["path"], w["key"])


# ------------------------------------------------------------------ 重放 / 借用 / 充数
def test_replaying_a_previous_runs_receipt_fails(tmp_path):
    """重放:上一次 run 的回执签名有效、内容完好,但 run_nonce 不是本次的。"""
    w = _world(tmp_path)
    v = _verify(w, run_nonce=new_nonce())          # 本次换了新 nonce
    assert not v.ok
    assert any(f.check == "U1.run_nonce" and not f.ok for f in v.findings)


def test_borrowing_another_units_receipt_fails(tmp_path):
    """借用:B 单元没调,想拿 A 单元的回执充数 —— request_nonce 对不上。"""
    w = _world(tmp_path, jobs=(("a", "RESULT A"),))
    w["units"].append({"request_nonce": "rn-b", "input_digest": digest_of({"job": "b"})})
    w["delivery"].append("RESULT A")
    v = _verify(w)
    assert not v.ok
    assert any(f.check == "U3.coverage" and not f.ok for f in v.findings)


def test_one_symbolic_call_cannot_cover_many_units(tmp_path):
    """充数:两个单元只调了一次。R6 的分母让这件事抓得住。"""
    w = _world(tmp_path, jobs=(("a", "RESULT A"),))
    w["units"].append({"request_nonce": "rn-b", "input_digest": digest_of({"job": "b"})})
    v = _verify(w, delivery=["RESULT A"])
    assert any(f.check == "U3.coverage" and not f.ok for f in v.findings)


def test_wrong_symbol_is_caught(tmp_path):
    """调错上游方法:符号不在契约要求集里。"""
    key, nonce = new_key(), new_nonce()
    path = tmp_path / "upstream_receipts.jsonl"
    led = ReceiptLedger(path, key)
    led.append(_receipt("run-1", nonce, 0, {"job": "a"}, "A", "rn-a",
                        symbol="browser_use.Agent.__init__"))
    v = verify_receipts(path, key=key, run_id="run-1", run_nonce=nonce,
                        task_id="t-recv", required_symbols=SYMS, required_upstream=UP,
                        expected_units=[{"request_nonce": "rn-a",
                                         "input_digest": digest_of({"job": "a"})}],
                        delivery=["A"])
    assert any(f.check == "U2.symbol" and not f.ok for f in v.findings)


def test_same_name_package_with_different_bytes_is_caught(tmp_path):
    """真包在场、跑的却是复制实现:artifact_hash 对不上。

    这正是 T3 批 13 的形状 —— 交付自带一个名叫 `browser_use` 的包,
    连 `__version__` 和 `UPSTREAM_COMMIT` 都照抄。名字与版本都可以自称,
    **实际加载的字节不能**。"""
    key, nonce = new_key(), new_nonce()
    path = tmp_path / "upstream_receipts.jsonl"
    led = ReceiptLedger(path, key)
    led.append(_receipt("run-1", nonce, 0, {"job": "a"}, "A", "rn-a",
                        upstream={"artifact_hash": "sha256:selfsupplied"}))
    v = verify_receipts(path, key=key, run_id="run-1", run_nonce=nonce,
                        task_id="t-recv", required_symbols=SYMS, required_upstream=UP,
                        expected_units=[{"request_nonce": "rn-a",
                                         "input_digest": digest_of({"job": "a"})}],
                        delivery=["A"])
    assert any(f.check == "U2.upstream_identity" and not f.ok for f in v.findings)


# ------------------------------------------------------------------ R5 / R6
def test_task_without_an_adoption_predicate_cannot_pass(tmp_path):
    """R5:没登记采纳谓词一律判不过 —— 不许默认放行。

    反例:默认放行 → 只证明了 U1–U3 的回执看起来像证明了全部四件。"""
    v = _verify(_world(tmp_path), task_id="t-unregistered")
    assert not v.ok
    d = next(f.detail for f in v.failed() if f.check == "U4.adoption")
    assert "NO_ADOPTION_PREDICATE" in d


def test_missing_unit_list_cannot_pass(tmp_path):
    """R6:没有待办清单就没有分母,"象征性调用一次"永远抓不住 → 判不过。"""
    v = _verify(_world(tmp_path), expected_units=None)
    assert not v.ok
    assert any(f.check == "U3.coverage" and not f.ok for f in v.findings)


def test_empty_delivery_is_not_adoption(tmp_path):
    """R5 边界:交付为空不算采纳(否则"什么都不交"反而最容易过)。"""
    v = _verify(_world(tmp_path), delivery=[])
    assert not v.ok
    assert any(f.check == "U4.adoption" and not f.ok for f in v.findings)


# ------------------------------------------------------------------ R7 / R8
def test_preview_and_size_do_not_affect_the_verdict(tmp_path):
    """R7:预览与长度只为人工取证,不参与判定。

    反例:让它们影响结论 → 被测方控制预览内容就能影响判定。"""
    key, nonce = new_key(), new_nonce()
    inp, out = {"job": "a"}, "RESULT A"
    base = _receipt("run-1", nonce, 0, inp, out, "rn-a")
    lying = Receipt(**{**_shallow(base),
                       "input": Payload(base.input.digest, size=999999,
                                        preview="完全对不上的预览"),
                       "output": Payload(base.output.digest, size=0, preview="")})
    path = tmp_path / "upstream_receipts.jsonl"
    ReceiptLedger(path, key).append(lying)
    v = verify_receipts(path, key=key, run_id="run-1", run_nonce=nonce,
                        task_id="t-recv", required_symbols=SYMS, required_upstream=UP,
                        expected_units=[{"request_nonce": "rn-a",
                                         "input_digest": digest_of(inp)}],
                        delivery=[out])
    assert v.ok, [f.detail for f in v.failed()]


def test_signature_does_not_cover_the_chain_field(tmp_path):
    """R8:同一张回执换个写入位置,签名不变。

    反例:把 `prev_sha256` 算进签名 → 内容相同的回执因写入顺序不同而签名
    不同,重放检测(要比对内容)反而更难做。"""
    key = new_key()
    r = _receipt("run-1", "n", 0, {"job": "a"}, "A", "rn-a").sign(key)
    moved = Receipt(**{**_shallow(r), "prev_sha256": "deadbeef"})
    assert moved.signature_ok(key), "签名不该随链位置变化"


def test_round_trip_through_the_ledger_preserves_verifiability(tmp_path):
    """接线:写盘 → 读回 → 仍验得过(序列化不得悄悄改变可签名内容)。"""
    w = _world(tmp_path)
    for r in read_ledger(w["path"]):
        assert r.signature_ok(w["key"]), f"{r.operation.invocation_id} 读回来就验不过了"


def test_ledger_lives_in_the_evidence_dir_not_the_agent_workspace():
    """R9:台账落点必须在 agent 写不到的地方,密钥不得落盘进 bundle。

    反例(位置):放会话根的兄弟目录 → agent 够得到 `..`(它本来就要读
    `../upstream`),光靠位置挡不住。
    反例(密钥):把密钥也写进 run 目录 → 拿到 bundle 的人可以重签整本账,
    签名那一层就白做了。"""
    from repoproof.receipts.ledger import LEDGER_NAME, ledger_path_for

    got = ledger_path_for(Path("/x/RepoProof/runs/t3-2026"))
    assert got == Path("/x/RepoProof/runs/t3-2026") / LEDGER_NAME

    src = (Path(__file__).resolve().parents[1]
           / "src" / "repoproof" / "receipts" / "ledger.py").read_text(encoding="utf-8")
    assert "write_text(key" not in src and "write_bytes(key" not in src, (
        "密钥被写盘了 —— 它只该活在 harness 进程内存里")
    assert "KEY_ENV" in src, "密钥应通过环境变量交给 sidecar,不经 agent"


def _shallow(r: Receipt) -> dict:
    from repoproof.receipts.model import asdict_shallow

    return asdict_shallow(r)
