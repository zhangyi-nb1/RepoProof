"""Phase 7 装配层测试(RFC-007)。零 LLM、零网络、零 Docker。"""

from __future__ import annotations

from pathlib import Path

import pytest

from repoproof.adoption.assembly.example_compiler import (
    CompileError,
    Example,
    compile_pytest,
    split_examples,
)
from repoproof.adoption.assembly.task_assembler import assemble_task

EXS = [
    {"input": "周合", "expected": "contains:周会纪要"},
    {"input": "读书", "expected": "contains:测试驱动"},
    {"input": "咖啡", "expected": "contains:购物清单"},
    {"input": "kafei", "expected": "contains:购物清单"},
]


def test_split_requires_three_and_reserves_held() -> None:
    with pytest.raises(CompileError, match="至少需要 3 组"):
        split_examples([Example(**e) for e in EXS[:2]])
    pub, held = split_examples([Example(**e) for e in EXS])
    assert len(pub) == 3 and len(held) == 1  # 每 4 组留 1 组隐藏


def test_compile_pytest_contains_and_equals() -> None:
    src = compile_pytest([Example(input="a", expected="contains:X"),
                          Example(input="b", expected="Y")], header="t")
    compile(src, "<t>", "exec")  # 语法必须合法
    assert "in out" in src and "== 'Y'" in src and "用户样例级" in src


def _assemble(tmp_path: Path) -> dict:
    (tmp_path / "contracts").mkdir(exist_ok=True)
    return assemble_task(
        tmp_path, goal="把 thefuzz 的模糊匹配接入笔记搜索。",
        repo_url="https://github.com/seatgeek/thefuzz",
        resolved_commit="a" * 40, distribution="thefuzz",
        import_module="thefuzz", license_id="MIT", examples=EXS)


def test_assemble_generates_complete_runnable_fileset(tmp_path: Path) -> None:
    out = _assemble(tmp_path)
    tid = out["task_id"]
    assert tid == "adopt-thefuzz-guided-v1" and out["public"] == 3 and out["held"] == 1
    for rel in (f"contracts/{tid}.yaml", f"contracts/{tid}.yaml.sha256",
                f"contracts/{tid}.requirements.yaml",
                "fixtures/assembled_thefuzz/src/user_capability/core.py",
                "fixtures/assembled_thefuzz/public_tests/test_public_contract.py",
                f"oracle/{tid}/test_capability.py", f"oracle/{tid}/test_regression.py",
                f"oracle/{tid}/fixtures/held_out_documents.json",
                f"controls/{tid}/positive/adapter.py",
                f"controls/{tid}/negative_empty/adapter.py"):
        assert (tmp_path / rel).exists(), rel
    # oracle 语法合法,含公开+held+确定性节点
    cap = (tmp_path / f"oracle/{tid}/test_capability.py").read_text()
    compile(cap, "<cap>", "exec")
    assert "test_example_1" in cap and "test_held_example_1" in cap and "test_deterministic" in cap
    # 控制组语义:正控命中样例;负控空串必挂 contains 断言
    ns: dict = {}
    exec((tmp_path / f"controls/{tid}/positive/adapter.py").read_text(), ns)  # noqa: S102
    assert "周会纪要" in ns["run"]("周合")
    ns2: dict = {}
    exec((tmp_path / f"controls/{tid}/negative_empty/adapter.py").read_text(), ns2)  # noqa: S102
    assert ns2["run"]("周合") == ""


def test_assemble_refuses_overwrite(tmp_path: Path) -> None:
    _assemble(tmp_path)
    with pytest.raises(CompileError, match="不覆盖"):
        _assemble(tmp_path)


def test_contract_loads_with_frozen_discipline(tmp_path: Path) -> None:
    from repoproof.domain.models import TaskContract
    from repoproof.harness.requirement_spec import load_requirement_spec

    out = _assemble(tmp_path)
    c, _ = TaskContract.load_frozen(
        tmp_path / "contracts" / f"{out['task_id']}.yaml", require_sidecar=True)
    assert c.target_project.entry_point == "run"
    spec, _sha = load_requirement_spec(
        tmp_path / "contracts" / c.requirement_spec_file)
    assert spec.controls and len(spec.requirements) == 3
    assert all(r.severity == "HARD" for r in spec.requirements)
