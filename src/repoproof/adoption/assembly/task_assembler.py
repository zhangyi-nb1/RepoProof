"""任务装配器(RFC-007)— 冻结意向 + 用户样例 → 完整任务文件集。

生成:合同(+sidecar)、RequirementSpec(含自动控制组)、seam 式
consumer fixture(user_capability 包)、oracle(公开+held-out 样例
测试 / 平凡回归)、公开样例与公开测试、控制组 adapter(正=样例映射
自洽证明;负=空实现)。随后由既有 `freeze-task --full` 冻结——
零 Core 改动,零外部 AI。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from repoproof.adoption.assembly.example_compiler import (
    CompileError,
    Example,
    compile_pytest,
    split_examples,
)

_CONSUMER_INIT = '''from user_capability.core import run, health

__all__ = ["run", "health"]
'''
_CONSUMER_CORE = '''"""用户能力 seam:AI 的适配代码经 REPOPROOF_ADAPTATION_DIR 注入。"""
import importlib.util
import os
from pathlib import Path


def _adapter():
    root = os.environ.get("REPOPROOF_ADAPTATION_DIR", "")
    cand = Path(root) / "adapter.py" if root else None
    if cand and cand.exists():
        spec = importlib.util.spec_from_file_location("user_adapter", cand)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    return None


def run(value):
    mod = _adapter()
    if mod is None:
        raise NotImplementedError("尚无适配代码(direct 模式不实现该能力)")
    return mod.run(value)


def health():
    return "ok"
'''
_REGRESSION = '''"""平凡回归:seam 包自身行为不被适配破坏。"""
import json
from pathlib import Path

import pytest

import user_capability


def test_health():
    assert user_capability.health() == "ok"


def test_examples_file_intact():
    p = Path(__file__).parent / "fixtures" / "public_documents.json"
    assert json.loads(p.read_text(encoding="utf-8"))["examples"]


def test_direct_mode_declares_not_implemented(monkeypatch):
    monkeypatch.delenv("REPOPROOF_ADAPTATION_DIR", raising=False)
    with pytest.raises(NotImplementedError):
        user_capability.run("x")
'''


def assemble_task(
    root: Path,
    *,
    goal: str,
    repo_url: str,
    resolved_commit: str,
    distribution: str,
    import_module: str,
    license_id: str,
    examples: list[dict],
    requires_python: str = ">=3.10",
) -> dict:
    """生成全部任务文件;返回 {task_id, files, next}。不冻结、不运行。"""
    exs = [Example(**e) for e in examples]
    public, held = split_examples(exs)
    slug = re.sub(r"[^a-z0-9-]+", "-", distribution.lower()).strip("-")
    task_id = f"adopt-{slug}-guided-v1"
    if (root / "contracts" / f"{task_id}.yaml").exists():
        raise CompileError(f"任务 {task_id} 已存在,不覆盖;如需重装配请先删除旧任务文件")

    consumer_rel = f"fixtures/assembled_{slug}"
    files: dict[str, str] = {}

    ex_lines = "; ".join(f"run({e.input!r}) -> {e.expected!r}" for e in public[:3])
    statement = (
        f"{goal.strip()} 交付 /adaptation/adapter.py,暴露 run(value) 单函数,"
        f"必须调用 pinned {distribution} 实现该能力;行为以公开样例为准"
        f"(例:{ex_lines});重复调用确定;完全离线 CPU-only。"
        "公开样例与可运行公开测试位于 /consumer 下,是本合同的一部分。"
    )
    files[f"contracts/{task_id}.yaml"] = f"""task_id: {task_id}

source_repo:
  url: {repo_url}
  revision: guided
  resolved_commit: {resolved_commit}
  license: {license_id}
  distribution: {distribution}
  import_module: {import_module}

target_project:
  kind: consumer_fixture
  path: {consumer_rel}
  package: user_capability
  entry_point: run

requirement_spec_file: {task_id}.requirements.yaml

capability:
  statement: >
    {statement}
  output_schema: UserExampleOutcome

environment: {{os: linux, arch: arm64, python: "3.12", cpu_only: true, network_install: true, network_test: false}}

constraints:
  forbidden: [gpu, privileged_container, oracle_write, model_download, network_at_test_time]
  editable_zones: [adaptation]
  forbidden_install_extras: []

budgets:
  max_agent_steps: 20
  max_wall_time_minutes: 30
  max_command_minutes: 5
  max_semantic_recoveries: 3
  max_same_action: 2
  max_patch_files: 8
  max_patch_lines: 400
  max_input_tokens_total: 400000
  max_output_tokens_total: 40000
  monetary_soft_cap_usd: 5.0

acceptance:
  capability_command: ["pytest", "-q", "/oracle/test_capability.py"]
  regression_command: ["pytest", "-q", "/oracle/test_regression.py"]
  probe_script: direct_frontmatter_probe_v2.py
"""
    n_pub, n_held = len(public), len(held)
    files[f"contracts/{task_id}.requirements.yaml"] = f"""task_id: {task_id}

controls:
  positive: controls/{task_id}/positive
  negatives:
    - path: controls/{task_id}/negative_empty
      label: NC_empty_adapter
      must_fail_nodes: ["test_example"]

requirements:
  - id: satisfy-user-examples
    owner: ADAPTER
    severity: HARD
    source_field: capability.statement
    public_text: >
      调用 pinned {distribution} 实现能力,使全部用户样例断言通过
      (行为以公开样例为准,例:{ex_lines})。
    examples:
      - "{ex_lines}"
    oracle_nodes:
{chr(10).join(f'      - "test_capability::test_example_{i + 1}"' for i in range(n_pub))}
{chr(10).join(f'      - "test_capability::test_held_example_{i + 1}"' for i in range(n_held))}
  - id: deterministic-runs
    owner: ADAPTER
    severity: HARD
    source_field: capability.statement
    public_text: >
      重复调用同一输入返回相同结果;完全离线 CPU-only 运行。
    examples:
      - "run(x) == run(x)"
    oracle_nodes:
      - "test_capability::test_deterministic"
  - id: seam-unbroken
    owner: ADAPTER
    severity: HARD
    source_field: capability.statement
    public_text: >
      不破坏宿主 seam 包既有行为(health/样例文件/direct 模式语义)。
    examples:
      - "health() == 'ok'"
    oracle_nodes:
      - "test_regression::test_health"
      - "test_regression::test_examples_file_intact"
      - "test_regression::test_direct_mode_declares_not_implemented"
"""
    # consumer fixture(seam 包 + 公开样例 + 公开测试)
    files[f"{consumer_rel}/src/user_capability/__init__.py"] = _CONSUMER_INIT
    files[f"{consumer_rel}/src/user_capability/core.py"] = _CONSUMER_CORE
    files[f"{consumer_rel}/public_examples/truth_table.json"] = json.dumps(
        {"note": "用户样例(公开子集)。expected 以 contains: 开头为包含断言,否则相等断言。"
                 "验收强度=用户样例级;另有同语义 held-out 样例用于隐藏验证。",
         "examples": [e.model_dump() for e in public]}, ensure_ascii=False, indent=1)
    files[f"{consumer_rel}/public_tests/test_public_contract.py"] = compile_pytest(
        public, header="公开合同测试 — agent 可运行自测")

    # oracle:公开样例 + held-out 样例 + 确定性;平凡回归
    pub_src = compile_pytest(public, header="验收(公开样例)")
    held_src = compile_pytest(held, header="验收(held-out 样例,agent 不可见)").replace(
        "def test_example_", "def test_held_example_")
    det = ("\n\ndef test_deterministic():\n"
           f"    v = {public[0].input!r}\n"
           "    assert str(run(v)) == str(run(v))\n")
    files[f"oracle/{task_id}/test_capability.py"] = pub_src + "\n" + held_src.split('"""')[2].lstrip("\n") + det
    files[f"oracle/{task_id}/test_regression.py"] = _REGRESSION
    files[f"oracle/{task_id}/fixtures/public_documents.json"] = json.dumps(
        {"examples": [e.model_dump() for e in public]}, ensure_ascii=False)
    files[f"oracle/{task_id}/fixtures/held_out_documents.json"] = json.dumps(
        {"examples": [e.model_dump() for e in held]}, ensure_ascii=False)

    # 控制组:正=样例映射(自洽证明,绝不给 agent);负=空实现
    mapping = {e.input: e.expected for e in [*public, *held]}
    files[f"controls/{task_id}/positive/adapter.py"] = (
        '"""正控:样例硬编码映射——只证明样例测试自洽可满足,绝不交付。"""\n'
        f"_M = {mapping!r}\n\n\n"
        "def run(value):\n"
        "    exp = _M.get(value, '')\n"
        "    return exp[len('contains:'):] if exp.startswith('contains:') else exp\n")
    files[f"controls/{task_id}/negative_empty/adapter.py"] = (
        '"""负控:空实现——样例测试必须拒绝它。"""\n\n\n'
        "def run(value):\n    return ''\n")

    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    contract = root / "contracts" / f"{task_id}.yaml"
    sha = hashlib.sha256(contract.read_bytes()).hexdigest()
    (root / "contracts" / f"{task_id}.yaml.sha256").write_text(
        f"{sha}  {contract.name}\n", encoding="utf-8")

    return {"task_id": task_id, "files": sorted(files), "public": n_pub, "held": n_held,
            "next": f".venv/bin/python -m repoproof.cli freeze-task --contract contracts/{task_id}.yaml --full"}
