"""上游 pin 单一来源(LESSONS #52)—— 那份锁必须**一定存在**。

来由:webcolors 连跑四发全 FAIL,死于 `ModuleNotFoundError`。链条是
`reference.lock.txt` 标着"(可选)"却缺席 → 三处各自静默降级(装配不写
controls 锁 / 备轮不下上游 / positive 彩排不预装)→ `import <上游>` 必炸,
还要等三轮修复耗尽才以 DEPENDENCY_ERROR 浮出来。

所以这里钉的不是某一处补丁,而是**那份锁在缺草稿件时也会被派生出来**。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.adoption.intake.upstream_pin import (
    derive_reference_lock,
    normalize_dist_name,
    upstream_version,
)

_COMMIT = "e6392ba6eeba81b02e666eb3ed02ef2e006344c0"


def _tree(project_root: Path, body: str, *, name: str = "pyproject.toml") -> Path:
    """按 upstream-cache/upstream-<commit12> 的真实约定摆树。

    夹具必须与生产同构:第一版把树摆在 tmp 根,派生自然找不到 ——
    那样测出来的"读不出版本"是夹具的锅,不是被测件的行为。
    """
    up = project_root / "upstream-cache" / f"upstream-{_COMMIT[:12]}"
    up.mkdir(parents=True, exist_ok=True)
    (up / name).write_text(body, encoding="utf-8")
    return up


def test_version_from_pep621_setupcfg_and_pkginfo(tmp_path: Path):
    a = _tree(tmp_path / "a", '[project]\nname = "x"\nversion = "25.10.0"\n')
    assert upstream_version(a) == "25.10.0"

    b = _tree(tmp_path / "b", "[metadata]\nversion = 1.2.3\n", name="setup.cfg")
    assert upstream_version(b) == "1.2.3"

    c = tmp_path / "c" / "upstream-cache" / f"upstream-{_COMMIT[:12]}" / "x.egg-info"
    c.mkdir(parents=True)
    (c / "PKG-INFO").write_text("Name: x\nVersion: 0.9\n", encoding="utf-8")
    assert upstream_version(c.parent) == "0.9"


def test_dynamic_version_is_not_guessed(tmp_path: Path):
    """**负控**:动态版本读不出就是读不出 —— 不猜、不去 PyPI 拿最新版。

    pin 的语义是"就这一版";解析最新版等于把钉版偷偷放开。
    """
    up = _tree(tmp_path, '[project]\nname = "x"\ndynamic = ["version"]\n')
    assert upstream_version(up) == ""
    assert derive_reference_lock(
        tmp_path, distribution="x",
        resolved_commit=_COMMIT) == ""


def test_derived_lock_carries_the_pin_and_its_provenance(tmp_path: Path):
    _tree(tmp_path, '[project]\nname = "webcolors"\nversion = "25.10.0"\n')
    lock = derive_reference_lock(
        tmp_path, distribution="webcolors",
        resolved_commit=_COMMIT)
    assert "webcolors==25.10.0" in lock
    assert "e6392ba6eeba" in lock          # 说得出出处
    assert "以你写的为准" in lock            # 人写的优先,写在文件里


def test_dist_name_normalisation_is_pep503():
    assert normalize_dist_name("Foo_Bar.baz") == "foo-bar-baz"
    assert normalize_dist_name(" webcolors ") == "webcolors"
