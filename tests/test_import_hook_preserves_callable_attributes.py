"""量具不许改被测,包括被测自己的函数属性(incident-receipt-wrapper-drops-lru-cache-attributes-*)。

现象:上游模块里 `@functools.lru_cache` 装饰的公开函数被回执代理替换后,上游自己的
`get_themes.cache_clear()` 抛 `'function' object has no attribute 'cache_clear'`——正确的
裁决者因此在正常运行里被量具打死。`functools.wraps` 只拷 `__dict__`,而 lru_cache 的
`cache_clear/cache_info/cache_parameters` 是包装器对象上的方法,拷不过来。

不变量:
  I1 代理对象上找不到的属性回落到原函数(cache_clear/cache_info/__wrapped__ 都可达);
  I2 调用照旧记账,返回值不变;
  I3 反事实代理同样保留属性,使控制组失败的原因只能是"结果被控制",不是量具自身崩溃。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from repoproof.execution.import_hook import ENV_LEDGER, ENV_MODULE, ENV_SECRET, verify_import_receipts, write_hook_dir

_CACHED_UP = '''import functools


@functools.lru_cache(maxsize=None)
def get_themes():
    return {"a": 1}


def reset_and_count():
    get_themes.cache_clear()
    get_themes()
    get_themes()
    return get_themes.cache_info().hits
'''


def _run(tmp: Path, body: str) -> tuple[subprocess.CompletedProcess, Path]:
    up = tmp / "up"
    up.mkdir(exist_ok=True)
    (up / "cachedup.py").write_text(_CACHED_UP, encoding="utf-8")
    hook = write_hook_dir(tmp / "hook")
    ledger = tmp / "ledger.jsonl"
    script = tmp / "child.py"
    script.write_text(body, encoding="utf-8")
    env = dict(
        os.environ,
        PYTHONPATH=f"{hook}{os.pathsep}{up}",
        **{ENV_MODULE: "cachedup", ENV_LEDGER: str(ledger), ENV_SECRET: "s3cr3t"},
    )
    run = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=120)
    return run, ledger


def test_lru_cache_attributes_survive_the_receipt_wrapper(tmp_path: Path) -> None:
    run, ledger = _run(
        tmp_path,
        "import cachedup\n"
        "assert cachedup.reset_and_count() == 1, cachedup.reset_and_count()\n"
        "assert cachedup.get_themes.cache_info().currsize == 1\n"
        "assert cachedup.get_themes.__wrapped__() == {'a': 1}\n",
    )
    assert run.returncode == 0, run.stderr
    got = verify_import_receipts(ledger, "s3cr3t", module="cachedup", min_calls=1)
    assert got["ok"] is True and got["calls"] >= 1


def test_counterfactual_proxy_keeps_attributes_reachable(tmp_path: Path) -> None:
    from repoproof.verification import semantic_artifact

    hook_src = tmp_path / "repoproof_counterfactual_hook.py"
    hook_src.write_text(semantic_artifact._COUNTERFACTUAL_HOOK, encoding="utf-8")
    run, _ = _run(
        tmp_path,
        "import sys\n"
        f"sys.path.insert(0, {str(tmp_path)!r})\n"
        "import repoproof_counterfactual_hook as h\n"
        "h.install()\n"
        "import cachedup\n"
        "cachedup.get_themes.cache_clear()\n"  # upstream-internal housekeeping must not crash the control
        "result = cachedup.get_themes()\n"
        "assert repr(result) == '<controlled-upstream-result>', repr(result)\n",
    )  # ENV_MODULE already names the target module for both hooks
    assert run.returncode == 0, run.stderr
