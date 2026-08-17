"""DSH 供应链钉死的钉 —— `check_pins` 的失败方向必须朝紧。

阶段 1(ADR:docs/adr/ADR-DSH-MINIMAL-AGENT-BACKEND.md)。守的不是攻击者,
是我们自己:wheel 被重下过一个字节不同的、cordis 配置被"顺手改一行"、
仓内参考副本与封存件分叉 —— 任何一样发生时 `--verify` 必须点名,而不是
沉默放行。

新符号不在模块级导入(LESSONS #34:红的粒度与钉死的粒度一致)。
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location(
        "pdr", REPO / "scripts" / "provision_dsh_runtime.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _seed(root: Path, rel: str, body: bytes) -> str:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)
    return hashlib.sha256(body).hexdigest()


def test_pins_fail_closed_on_tamper(tmp_path: Path) -> None:
    """封存后动过一个字节 → 必须点名那个文件。"""
    m = _mod()
    pins = {"wheels/a.whl": _seed(tmp_path, "wheels/a.whl", b"alpha"),
            "config/c.yml": _seed(tmp_path, "config/c.yml", b"conf")}
    ok, problems = m.check_pins(tmp_path, pins)
    assert ok and problems == []
    (tmp_path / "config/c.yml").write_bytes(b"conf-TAMPERED")
    ok, problems = m.check_pins(tmp_path, pins)
    assert not ok
    assert any("config/c.yml" in x and "hash 不符" in x for x in problems)


def test_missing_pinned_file_fails(tmp_path: Path) -> None:
    """缺文件不是"还没下载",是破 —— 不许静默跳过。"""
    m = _mod()
    pins = {"wheels/a.whl": _seed(tmp_path, "wheels/a.whl", b"alpha"),
            "wheels/gone.whl": hashlib.sha256(b"never").hexdigest()}
    ok, problems = m.check_pins(tmp_path, pins)
    assert not ok
    assert any("缺失" in x and "wheels/gone.whl" in x for x in problems)


def test_registered_pins_shape() -> None:
    """PINS 表本身的形状:四件套齐、hash 是 64 位小写十六进制、
    commit 是 40 位、来源域名只有 PyPI 官方与 raw.githubusercontent。"""
    m = _mod()
    named = {m.REL_SDK_WHEEL, m.REL_RT_WHEEL, m.REL_CONFIG, m.REL_LICENSE}
    assert named <= set(m.PINS)
    # 2 官方 wheel + 5 依赖闭包 wheel + cordis 配置 + LICENSE;PINS 与 FETCH
    # 一一对应 —— 有 hash 没来源、有来源没 hash 都是表在撒谎
    assert len(m.PINS) == 9
    assert set(m.PINS) == set(m.FETCH)
    for v in m.PINS.values():
        assert re.fullmatch(r"[0-9a-f]{64}", v)
    assert re.fullmatch(r"[0-9a-f]{40}", m.SOURCE_COMMIT)
    for rel, url in m.FETCH.items():
        assert url.startswith(("https://files.pythonhosted.org/",
                               "https://raw.githubusercontent.com/")), (rel, url)
    # 仓内参考副本与封存件钉同一枚 hash(分叉即两处必有一处报破)
    rc = m.repo_copy_pins()
    assert rc[m.REPO_CONFIG_COPY] == m.PINS[m.REL_CONFIG]
    assert rc[m.REPO_LICENSE_COPY] == m.PINS[m.REL_LICENSE]


def test_repo_reference_copies_match_pins() -> None:
    """仓里实际提交的参考副本必须与钉的 hash 一致 —— 这条钉住"提交进仓的
    那份被人改过而封存件没变"的分叉方向。"""
    m = _mod()
    ok, problems = m.check_pins(REPO, m.repo_copy_pins())
    assert ok, problems
