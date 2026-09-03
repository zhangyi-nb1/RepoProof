"""密封进工作区的 requirements.lock.txt 必须是唯一的规范形
(incident-workspace-candidate-lock-canonicalization-v1/v2)。

不变量:候选样例、preflight、审计三处都经 `seal_offline_python_runtime` 密封
runtime 闭包;它写出的锁必须等于冻结时 assembler 用的
`close_workspace_runtime_lock(lock, contract)`,与调用方传来的原始字节
(注释行、空行、缺少 Core 校验器 pin)无关——否则同一份 reference 在确认时和
冻结后产出两棵不同的黄金树。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from repoproof.adoption.delivery.portable_workspace_runtime import (
    close_workspace_runtime_lock,
    seal_offline_python_runtime,
)

_spec = importlib.util.spec_from_file_location(
    "_runtime_fixtures", Path(__file__).with_name("test_portable_workspace_runtime.py")
)
_fixtures = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_fixtures)


def _sealed_lock(tmp_path: Path, raw_lock: str) -> tuple[str, dict]:
    contract = _fixtures._runtime_contract()
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    _fixtures._minimal_wheel(wheelhouse / "demo_runtime-1.0-py3-none-any.whl")
    lock = tmp_path / "reference.lock.txt"
    lock.write_text(raw_lock, encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    (output / str(contract["runtime_python_entrypoint"])).write_text("print('x')\n", encoding="utf-8")
    seal_offline_python_runtime(output, contract, wheelhouse=wheelhouse, requirements_lock=lock)
    return (output / "requirements.lock.txt").read_text(encoding="utf-8"), contract


def test_sealed_lock_is_the_closed_canonical_form_not_the_raw_bytes(tmp_path: Path) -> None:
    raw = (
        "# 由钉版上游树声明版本派生(commit 0000000);\n"
        "# 草稿束写了 reference.lock.txt 时以你写的为准。\n\ndemo-runtime==1.0\n"
    )
    sealed, contract = _sealed_lock(tmp_path, raw)
    assert sealed == close_workspace_runtime_lock(raw, contract)
    assert not any(line.startswith("#") for line in sealed.splitlines())
    assert sealed == "demo-runtime==1.0\n"


def test_already_canonical_lock_is_sealed_unchanged(tmp_path: Path) -> None:
    sealed, _ = _sealed_lock(tmp_path, "demo-runtime==1.0\n")
    assert sealed == "demo-runtime==1.0\n"
