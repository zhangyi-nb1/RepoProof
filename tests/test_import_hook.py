"""import-hook 取证件的自证(M2-c · [D4] 运行时升级)。

真子进程级喂缺陷矩阵 —— 检查器先证明自己查得出:
  真调 → 过;只 import 不调(装样子,静态 provenance 的盲区)→ 抓;
  不 import → 抓;错 secret 伪造 → HMAC 抓;账缺失 → 判死(沉默不是
  通过);min_calls 不足 → 抓;交付文本探测协议字样 → 自曝扫描抓;
  wrapper 必须行为透明(包装后返回值不变 —— 量具不许改被测)。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from repoproof.execution.import_hook import (
    ENV_LEDGER,
    ENV_MODULE,
    ENV_SECRET,
    scan_probe_marker,
    verify_import_receipts,
    write_hook_dir,
)

_FAKEUP = '''MAGIC = 7


class Boom(ValueError):
    pass


def work(x):
    if x < 0:
        raise Boom("negative")
    return x * MAGIC


def helper(y):
    return y + 1
'''


def _run_child(tmp: Path, body: str) -> Path:
    """在注入 hook 的子进程里跑 body;返回 ledger 路径。"""
    up = tmp / "up"
    up.mkdir(exist_ok=True)
    (up / "fakeup.py").write_text(_FAKEUP, encoding="utf-8")
    hook = write_hook_dir(tmp / "hook")
    ledger = tmp / "ledger.jsonl"
    script = tmp / "child.py"
    script.write_text(body, encoding="utf-8")
    env = dict(os.environ,
               PYTHONPATH=f"{hook}{os.pathsep}{up}",
               **{ENV_MODULE: "fakeup", ENV_LEDGER: str(ledger),
                  ENV_SECRET: "s3cr3t"})
    r = subprocess.run([sys.executable, str(script)], env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return ledger


def test_real_call_passes_and_wrapper_is_transparent(tmp_path):
    ledger = _run_child(tmp_path, (
        "import fakeup\n"
        "assert fakeup.work(6) == 42, fakeup.work(6)\n"   # 包装后语义不变
        "assert fakeup.helper(1) == 2\n"
        # 异常类不许被包:except 语义必须保持(真实上游 FormatError 实测坑)
        "assert isinstance(fakeup.Boom, type)\n"
        "try:\n"
        "    fakeup.work(-1)\n"
        "except fakeup.Boom:\n"
        "    pass\n"))
    got = verify_import_receipts(ledger, "s3cr3t", module="fakeup", min_calls=2)
    assert got["ok"] is True and got["imports"] == 1 and got["calls"] == 3


def test_ghost_import_is_caught(tmp_path):
    """静态 provenance 的盲区:import 了但一次没调 —— 运行时账必须抓。"""
    ledger = _run_child(tmp_path, "import fakeup\nprint('done')\n")
    got = verify_import_receipts(ledger, "s3cr3t", module="fakeup", min_calls=1)
    assert got["ok"] is False and "装样子" in got["reason"]
    assert got["imports"] == 1 and got["calls"] == 0


def test_never_imported_is_caught(tmp_path):
    """不 import → 一行账都没有 → ledger 缺失路径判死(沉默不是通过)。"""
    ledger = _run_child(tmp_path, "print('no upstream at all')\n")
    got = verify_import_receipts(ledger, "s3cr3t", module="fakeup", min_calls=1)
    assert got["ok"] is False and "缺失" in got["reason"]


def test_import_event_required_even_with_noise_rows(tmp_path):
    """账里只有别的模块的行:目标模块 imports=0 必须走"从未被 import"。"""
    ledger = _run_child(tmp_path, "import fakeup\nfakeup.work(1)\n")
    text = ledger.read_text(encoding="utf-8")
    ledger.write_text("", encoding="utf-8")  # 清空后放入他模块行(合法签名)
    import hashlib
    import hmac
    import json

    payload = {"kind": "import", "module": "other", "seq": 1, "pid": 1}
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    sig = hmac.new(b"s3cr3t", body.encode(), hashlib.sha256).hexdigest()
    ledger.write_text(json.dumps({"p": payload, "sig": sig}) + "\n",
                      encoding="utf-8")
    got = verify_import_receipts(ledger, "s3cr3t", module="fakeup", min_calls=1)
    assert got["ok"] is False and "从未被 import" in got["reason"]
    assert text  # 原真账确实存在过(本测不是在测空转)


def test_missing_ledger_is_dead_not_green(tmp_path):
    got = verify_import_receipts(tmp_path / "nope.jsonl", "s3cr3t",
                                 module="fakeup")
    assert got["ok"] is False and "缺失" in got["reason"]


def test_forged_row_wrong_secret_is_caught(tmp_path):
    ledger = _run_child(tmp_path, "import fakeup\nfakeup.work(1)\n")
    # 攻击者不知道 secret,按自造密钥补写一行"调用"
    import hashlib
    import hmac
    import json

    payload = {"kind": "call", "module": "fakeup", "symbol": "fakeup.work",
               "seq": 99, "pid": 1, "args_sha": "x"}
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    sig = hmac.new(b"guessed", body.encode(), hashlib.sha256).hexdigest()
    with open(ledger, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"p": payload, "sig": sig}) + "\n")
    got = verify_import_receipts(ledger, "s3cr3t", module="fakeup", min_calls=1)
    assert got["ok"] is False and "HMAC" in got["reason"]


def test_min_calls_floor_is_enforced(tmp_path):
    ledger = _run_child(tmp_path, "import fakeup\nfakeup.work(1)\n")
    got = verify_import_receipts(ledger, "s3cr3t", module="fakeup", min_calls=3)
    assert got["ok"] is False and "最低 3" in got["reason"]


def test_probe_marker_scan(tmp_path):
    (tmp_path / "ok.py").write_text("import fakeup\n", encoding="utf-8")
    (tmp_path / "probe.py").write_text(
        "import os\nx = os.environ.get('REPOPROOF_HOOK_SECRET')\n",
        encoding="utf-8")
    hits = scan_probe_marker(tmp_path, ["ok.py", "probe.py"])
    assert hits == ["probe.py"]
