"""M7 强回执(验收期取证会话)· 检查器先自证。

分层喂正反例:
  audit 层(E2E,真起 server 真发请求)——
    正例:impl 真调上游 → U1–U4 全绿;
    U4 负控:交付链(bin 壳)在输出上做手脚 → 等于式采纳当场杀;
    故障形态:impl 抛异常 → 取证面如实截停;包名错 → server died 归 harness。
  verify 层(对同一本真账做攻击矩阵)——
    改行→U1 链杀;砍尾→U1 计数杀;换 artifact_hash 期望→U2 杀;
    多一个待办单元→U3 杀。
不自证判别力的取证件,发的每张回执都是墙纸。
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from repoproof.adoption.assembly.tool_assembler import assemble_tool_task
from repoproof.domain.models import (
    ToolInterface,
    ToolInterfaceIO,
    ToolOutputContract,
    ToolRuntimeSpec,
    ToolSpec,
)
from repoproof.runner.managed_receipt_session import run_managed_receipt_audit

pytestmark = pytest.mark.slow

_IMPL_GOOD = (
    "from pathlib import Path\n"
    "import json\n\n\n"
    "class UserInputError(ValueError):\n    pass\n\n\n"
    "def extract(input_path: Path) -> str:\n"
    "    try:\n"
    "        data = json.loads(input_path.read_text(encoding='utf-8'))\n"
    "    except ValueError as e:\n"
    "        raise UserInputError(str(e)) from e\n"
    "    return json.dumps(data, ensure_ascii=False, sort_keys=True)\n"
)

_IMPL_CRASH = (
    "from pathlib import Path\n\n\n"
    "class UserInputError(ValueError):\n    pass\n\n\n"
    "def extract(input_path: Path) -> str:\n"
    "    raise RuntimeError('boom')\n"
)


def _world(tmp_path: Path, impl_src: str) -> dict:
    examples = tmp_path / "example-source"
    examples.mkdir()
    rows = []
    for i, doc in enumerate(('{"a": 1}', '{"b": [1, 2]}', '{"c": "值"}'), 1):
        (examples / f"in-{i}.json").write_text(doc, encoding="utf-8")
        (examples / f"out-{i}.txt").write_text(
            json.dumps(json.loads(doc), ensure_ascii=False, sort_keys=True),
            encoding="utf-8")
        rows.append({"input_file": f"in-{i}.json", "expected_file": f"out-{i}.txt"})
    spec = ToolSpec(
        schema_version=3,
        name="rcpt-demo", summary="receipt demo",
        interface=ToolInterface(
            usage="rcpt-demo <input>",
            input=ToolInterfaceIO(kind="file", format="JSON"),
            output=ToolInterfaceIO(
                kind="stdout", format="text",
                contract=ToolOutputContract(
                    media_type="text/plain", root_type="text", required={})),
            exit_codes={"0": "success", "1": "user_error", "2": "internal_error"}),
        runtime=ToolRuntimeSpec(
            mode="http_sidecar", profile_id="tool-http-sidecar-v1",
            lifecycle="per_invocation", credentials="none",
            network="loopback_only", protocol="repoproof-http-sidecar-v1",
            startup_timeout_seconds=10, request_timeout_seconds=120,
            shutdown_timeout_seconds=3),
    )
    assemble_tool_task(
        tmp_path, goal="normalize json deterministically",
        repo_url="https://example.invalid/up", resolved_commit="b" * 40,
        distribution="demo-upstream", import_module="json", license_id="MIT",
        tool=spec, examples=rows, example_src_dir=examples,
        reference_impl=_IMPL_GOOD, input_ext=".json",
        malformed_applicable=False, capability_output_schema="text")
    skeleton = tmp_path / "fixtures" / "tool_skeleton_rcpt-demo"
    pkg = skeleton / "src" / "rcpt_demo"
    (pkg / "impl.py").write_text(impl_src, encoding="utf-8")
    fixtures = sorted((examples).glob("in-*.json"))

    shim = tmp_path / "tool-bin"
    shim.write_text(
        "#!/bin/bash\n"
        f'export PYTHONPATH="{skeleton / "src"}"\n'
        f'exec "{sys.executable}" -m rcpt_demo "$@"\n', encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    return {"skeleton": skeleton, "src": skeleton / "src", "fixtures": fixtures,
            "shim": shim, "run_dir": tmp_path / "run"}


def _audit(w: dict, *, tool_bin: Path | None = None, run_id: str = "m7r-1") -> dict:
    return run_managed_receipt_audit(
        src_dir=w["src"], package="rcpt_demo", venv_python=Path(sys.executable),
        import_module="json", distribution="demo-upstream",
        task_id="tool-rcpt-demo-v1", run_id=run_id, run_dir=w["run_dir"],
        fixtures=w["fixtures"], tool_bin=tool_bin or w["shim"])


def test_positive_full_green_and_ledger_on_disk(tmp_path):
    w = _world(tmp_path, _IMPL_GOOD)
    rv = _audit(w)
    assert rv["ok"] is True, rv
    assert rv["receipts"] == len(w["fixtures"])
    red = [f for f in rv["findings"] if not f["ok"]]
    assert not red, red
    ledger = w["run_dir"] / "managed_receipt_audit" / "receipts.jsonl"
    rows = [json.loads(x) for x in
            ledger.read_text(encoding="utf-8").splitlines()]
    # 现场上游指纹必须真的算出来了(不是空串装样子)
    assert all(r["upstream"]["artifact_hash"] for r in rows)
    assert all(r["operation"]["symbol"] == "rcpt_demo.impl.extract" for r in rows)


def test_delivery_tampering_dies_at_u4(tmp_path):
    """交付链换答案:bin 壳把 stdout 动了手脚 —— 等于式采纳必须当场杀。
    这正是「取证面证明上游产出 X、交付面却交出 Y」的形态。"""
    w = _world(tmp_path, _IMPL_GOOD)
    evil = tmp_path / "evil-bin"
    evil.write_text(
        "#!/bin/bash\n"
        f'export PYTHONPATH="{w["src"]}"\n'
        f'"{sys.executable}" -m rcpt_demo "$@" | sed "s/$/-TAMPERED/"\n',
        encoding="utf-8")
    evil.chmod(evil.stat().st_mode | stat.S_IXUSR)
    rv = _audit(w, tool_bin=evil, run_id="m7r-2")
    assert rv["ok"] is False
    assert rv["reason"] == "RECEIPT_VERIFICATION_FAILED"
    red = {f["check"] for f in rv["findings"] if not f["ok"]}
    assert "U4.adoption" in red, rv["findings"]


def test_impl_crash_stops_probe_honestly(tmp_path):
    w = _world(tmp_path, _IMPL_CRASH)
    rv = _audit(w, run_id="m7r-3")
    assert rv["ok"] is False
    assert rv["reason"] == "RECEIPT_PROBE_INVOKE_FAILED"
    assert rv["attribution"] == "agent"


def test_bad_package_is_harness_side_server_death(tmp_path):
    w = _world(tmp_path, _IMPL_GOOD)
    rv = run_managed_receipt_audit(
        src_dir=w["src"], package="no_such_pkg", venv_python=Path(sys.executable),
        import_module="json", distribution="demo-upstream",
        task_id="tool-rcpt-demo-v1", run_id="m7r-4", run_dir=w["run_dir"],
        fixtures=w["fixtures"], tool_bin=w["shim"])
    assert rv["ok"] is False
    assert rv["reason"] in ("RECEIPT_SERVER_DIED", "RECEIPT_SERVER_TIMEOUT")
    assert rv["attribution"] == "harness"


# ---------------------------------------------------- verify 层:账本攻击矩阵

def _green_ledger(tmp_path):
    """跑一遍正例,返回重放 verify 所需的全部材料。"""
    from repoproof.execution.receipt_hook import (
        input_digest_of,
        norm_output_digest,
        probe_upstream_identity,
    )
    from repoproof.receipts.verify import (
        digest_equality_predicate,
        register_adoption,
        verify_receipts,
    )

    w = _world(tmp_path, _IMPL_GOOD)
    rv = _audit(w, run_id="m7r-replay")
    assert rv["ok"] is True, rv
    audit_root = w["run_dir"] / "managed_receipt_audit"
    ledger = audit_root / "receipts.jsonl"
    rows = [json.loads(x) for x in ledger.read_text(encoding="utf-8").splitlines()]
    # 从落盘账里恢复 verify 入参(nonce 从 staging 文件名逆推;key 无法恢复
    # —— 攻击矩阵只考不需要真 key 的谓词,签名类攻击用假 key 验证判死方向)
    units = [{"request_nonce": r["binding"]["request_nonce"],
              "input_digest": r["input"]["digest"]} for r in rows]
    delivery = []
    for f in w["fixtures"]:
        import subprocess
        p = subprocess.run([str(w["shim"]), str(f)], capture_output=True,
                           text=True, timeout=120)
        delivery.append(p.stdout)
    ident = probe_upstream_identity(Path(sys.executable), "json", "demo-upstream")
    run_nonce = rows[0]["binding"]["run_nonce"]
    true_key = bytes.fromhex(
        (audit_root / "receipts.key").read_text(encoding="utf-8").strip())

    def verify(ledger_path, *, key=None, extra_unit=None,
               artifact_override=None, count=None):
        register_adoption("tool-rcpt-demo-v1", digest_equality_predicate(
            lambda d: [norm_output_digest(t) for t in d]))
        req_up = dict(ident)
        if artifact_override is not None:
            req_up["artifact_hash"] = artifact_override
        u = list(units) + ([extra_unit] if extra_unit else [])
        return verify_receipts(
            ledger_path, key=key if key is not None else true_key,
            run_id="m7r-replay", run_nonce=run_nonce,
            task_id="tool-rcpt-demo-v1",
            required_symbols={"rcpt_demo.impl.extract"},
            required_upstream=req_up, expected_units=u, delivery=delivery,
            expected_receipt_count=count if count is not None else len(rows))
    return ledger, rows, verify


def test_ledger_attack_matrix(tmp_path):
    ledger, rows, verify = _green_ledger(tmp_path)

    # 假密钥重验:签名谓词必须红(伪造者摇不出 harness 的 key)
    v = verify(ledger, key=b"wrong-key")
    assert not v.ok and any(f.check == "U1.signature" and not f.ok
                            for f in v.findings)

    # 改写中间一行:哈希链必须断
    lines = ledger.read_text(encoding="utf-8").splitlines()
    doctored = tmp_path / "doctored.jsonl"
    doc0 = json.loads(lines[0])
    doc0["input"]["size"] += 1              # 改一字节内容,格式仍合法
    forged0 = json.dumps(doc0, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    doctored.write_text("\n".join([forged0] + lines[1:]) + "\n",
                        encoding="utf-8")
    v = verify(doctored)
    assert not v.ok and any(f.check == "U1.chain" and not f.ok
                            for f in v.findings)

    # 砍尾:行数与执行方自数不符必须红
    truncated = tmp_path / "truncated.jsonl"
    truncated.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    v = verify(truncated, count=len(rows))
    assert not v.ok and any(f.check == "U1.count" and not f.ok
                            for f in v.findings)

    # 期望 artifact_hash 换假(=装了别的上游版本):U2 必须红
    v = verify(ledger, artifact_override="f" * 64)
    assert not v.ok and any(f.check == "U2.upstream_identity" and not f.ok
                            for f in v.findings)

    # 多一个从未下发过回执的待办单元:U3 覆盖必须红
    v = verify(ledger, extra_unit={"request_nonce": "ghost",
                                   "input_digest": "bytes/raw:" + "0" * 64})
    assert not v.ok and any(f.check == "U3.coverage" and not f.ok
                            for f in v.findings)
