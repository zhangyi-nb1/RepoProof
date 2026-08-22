"""LOCAL-TOOL 任务装配器(M1 · TOOL_CONTRACT_SCHEMA / TOOL_PACKAGE_LAYOUT)
— 冻结意向 + 用户样例 + ToolSpec → 完整任务文件集。

与旧 `task_assembler.assemble_task`(seam 谱系)并存,互不触碰。

生成物:
  contracts/tool-<slug>-v<n>.yaml (+sidecar) + requirements.yaml
  fixtures/tool_skeleton_<slug>[-vN]/   工具骨架(结构锚,agent 填肉)
  oracle/<task_id>/                     golden(公开+held-out,cli 编译)
                                        + 接口契约五项 + 全部样例 fixtures
  controls/<task_id>/                   五控制(impl.py 变体;NC_reimpl 的
                                        判死在 provenance 层,不进 battery)

责任分界(LAYOUT §四):main.py 的 argparse + 输入存在检查 + exit 语义
= 骨架(HOST_INPUT_GUARD,不计 agent 能力);impl.extract 的能力实现与
坏输入包装(抛 UserInputError → exit 1)= agent(ADAPTER)。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from repoproof.adoption.assembly.example_compiler import (
    CompileError,
    Example,
    compile_pytest,
    split_examples,
)
from repoproof.domain.models import ToolSpec

# ------------------------------------------------------------------ 骨架模板

_MAIN_PY = '''"""{name} — CLI 骨架(harness 锁定件:argparse / exit 语义 / 错误分层)。

exit 语义(合同冻结):0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。
能力实现在 impl.py(agent 交付);本文件的结构改动 = 越权。
"""
import argparse
import sys
from pathlib import Path

from . import impl


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog={name!r}, description={summary!r})
    p.add_argument("input", help="输入文件({in_format})")
    p.add_argument("--out", help="输出文件(缺省写 stdout)")
    return p


def cli(argv=None) -> int:
    args = _parser().parse_args(argv)
    src = Path(args.input)
    if not src.is_file():
        print(f"error: input not found: {{src}}", file=sys.stderr)
        return 1
    try:
        result = impl.extract(src)
    except impl.UserInputError as e:
        print(f"error: {{e}}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 — 兜底即内部错误,语义=2
        print(f"internal error: {{type(e).__name__}}: {{e}}", file=sys.stderr)
        return 2
    if args.out:
        Path(args.out).write_text(result, encoding="utf-8")
    else:
        sys.stdout.write(result if result.endswith("\\n") else result + "\\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
'''

_IMPL_PY = '''"""能力位(agent 交付区):必须调用 pinned {distribution} 实现。

约定(合同的一部分):
  - extract(input_path) -> str:返回 {out_format} 文本;
  - 输入内容坏(能打开但不是合法 {in_format})→ raise UserInputError(...)
    (骨架把它转成 exit 1;裸奔其他异常会被兜成 exit 2 = 接口契约违约);
  - 重复调用同一输入必须返回相同结果;完全离线 CPU-only。
"""
from pathlib import Path


class UserInputError(ValueError):
    """输入内容级错误(格式坏/不可解析)。"""


def extract(input_path: Path) -> str:
    raise NotImplementedError("能力未实现(骨架初始态)")
'''

_MAIN_MOD = '''from .main import cli

raise SystemExit(cli())
'''

_INIT_PY = '''__all__ = ["cli"]

from .main import cli
'''

_BIN_SH = '''#!/usr/bin/env bash
# CLI 壳(harness 锁定件):进本包 venv 执行,不污染调用方环境。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/.venv/bin/python" -m {package} "$@"
'''

_BUILD_SH = '''#!/usr/bin/env bash
# 唯一构建声明(harness 锁定件)。clean replay 与用户安装走同一条路。
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install --disable-pip-version-check -q -r requirements.lock.txt
.venv/bin/pip install --disable-pip-version-check -q -e .
echo "build ok: $(pwd)"
'''

_PYPROJECT = '''[project]
name = "{package}"
version = "1.0.0"
description = {summary!r}
requires-python = ">=3.12"

[tool.setuptools.packages.find]
where = ["src"]
'''

_README = '''# {name}

{summary}

## 用法

```
{usage}
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/{name} <input>
```

来源:{repo_url} @ {commit}(license: {license});
验证证据见 `evidence/`(harness 写入)。
'''


def _tool_json(spec: ToolSpec, *, repo_url: str, commit: str, license_id: str,
               distribution: str) -> str:
    return json.dumps({
        "manifest_version": 1,
        "name": spec.name,
        "version": "1.0.0",
        "summary": spec.summary,
        "source": {"url": repo_url, "resolved_commit": commit,
                   "license": license_id, "distribution": distribution},
        "interface": spec.interface.model_dump(),
        "runtime": {"python": "3.12", "cpu_only": True, "offline": True},
        "verification": None,   # harness 在 gate 后写入;agent 写非 null = 越权
    }, ensure_ascii=False, indent=1) + "\n"


# ------------------------------------------------------- 接口契约测试(五项)

_REGRESSION_TMPL = '''"""接口契约(regression 新所指;从 ToolSpec 确定性生成,不依赖能力语义)。

exit 语义:0=成功;1=用户错误;2=内部错误。malformed fixture 是合成的
坏格式文件 —— 能打开、不是合法输入;必须 exit 1,不得兜成 2。
"""
import os
import subprocess
from pathlib import Path

_TOOL = os.environ["REPOPROOF_TOOL_BIN"]
_FIX = Path(__file__).resolve().parent / "fixtures"


def _run(args):
    return subprocess.run([_TOOL, *args], capture_output=True, text=True, timeout=120)


def test_help_reachable():
    r = _run(["--help"])
    assert r.returncode == 0, f"--help 必须 exit 0,实际 {{r.returncode}}"
    assert "usage" in r.stdout.lower(), f"--help 须含 usage 行: {{r.stdout[:120]}}"


def test_missing_input_is_user_error():
    r = _run([str(_FIX / "no_such_file{ext}")])
    assert r.returncode == 1, f"输入不存在必须 exit 1,实际 {{r.returncode}}"
    assert r.stderr.strip(), "用户错误必须在 stderr 说明原因"
    assert not r.stdout.strip(), "错误路径不得向 stdout 输出半成品"


def test_malformed_input_is_user_error():
    r = _run([str(_FIX / "malformed{ext}")])
    assert r.returncode == 1, (
        f"坏格式输入必须 exit 1(user_error),实际 {{r.returncode}} —— "
        "exit 2 意味着异常裸奔到兜底层(接口契约违约)")
    assert r.stderr.strip(), "用户错误必须在 stderr 说明原因"


def test_deterministic_output():
    a = _run([str(_FIX / {det_input!r})])
    b = _run([str(_FIX / {det_input!r})])
    assert a.returncode == 0 and b.returncode == 0
    assert a.stdout == b.stdout, "同一输入两次运行输出必须逐字节一致"


def test_stdout_purity_on_success():
    r = _run([str(_FIX / {det_input!r})])
    assert r.returncode == 0
    assert r.stdout.strip(), "成功路径 stdout 必须有产出"
    assert "Traceback" not in r.stderr, "成功路径不得泄漏 traceback 到 stderr"
'''

# --------------------------------------------------------------- 控制组模板

_CTRL_HEAD = '''"""{label}(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {mapping!r}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {{key}}")
    return _M[key]
'''

_CTRL_POSITIVE = _CTRL_HEAD + '''

def extract(input_path: Path) -> str:
    return _lookup(input_path)
'''

_CTRL_EMPTY = '''"""NC_empty:空实现 —— 样例断言必须拒绝它。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    return ""
'''

_CTRL_BADEXIT = _CTRL_HEAD + '''

def extract(input_path: Path) -> str:
    # 坏输入不包装:裸奔异常 → 骨架兜成 exit 2 → 接口契约测试必须抓
    return _M[input_path.name]
'''


def _expected_text(e: Example, src_dir: Path) -> str:
    if e.expected_file is not None:
        return (src_dir / e.expected_file).read_text(encoding="utf-8")
    if e.expected.startswith("contains:"):
        return e.expected[len("contains:"):]
    return e.expected


# ------------------------------------------------------------------ 装配函数

def assemble_tool_task(
    root: Path,
    *,
    goal: str,
    repo_url: str,
    resolved_commit: str,
    distribution: str,
    import_module: str,
    license_id: str,
    tool: ToolSpec,
    examples: list[dict],
    example_src_dir: Path,
    input_ext: str = ".pdf",
) -> dict:
    """生成 LOCAL-TOOL 全部任务文件;返回 {task_id, files, next}。不冻结、不运行。

    examples 里的 input_file/expected_file 相对 example_src_dir;
    装配器负责把公开样例文件落到骨架公开区、全部样例文件落到 oracle 区。
    文件样例的 held-out 隐藏 = 文件本体只进 oracle(SCHEMA §四第一层)。
    """
    exs = [Example(**e) for e in examples]
    if not any(e.input_file for e in exs):
        raise CompileError("LOCAL-TOOL 任务至少需要一个文件输入样例(确定性锚)")
    public, held = split_examples(exs)
    if not held:
        raise CompileError("held-out 为空 —— 防硬编码层失效,拒装配(adequacy T4 同律)")

    slug = re.sub(r"[^a-z0-9-]+", "-", tool.name.lower()).strip("-")
    n = 1
    while (root / "contracts" / f"tool-{slug}-v{n}.yaml").exists():
        n += 1
    task_id = f"tool-{slug}-v{n}"
    skel_rel = f"fixtures/tool_skeleton_{slug}" if n == 1 else f"fixtures/tool_skeleton_{slug}-v{n}"
    package = tool.name.replace("-", "_")

    files: dict[str, str] = {}
    copies: list[tuple[Path, str]] = []   # (源文件, 仓内相对目标)

    # ---- 契约 ----
    ex_lines = "; ".join(
        (f"{tool.name} {e.input_file} -> {e.expected!r}" if e.input_file and e.expected
         else f"{tool.name} {e.input_file} -> 见 {e.expected_file}" if e.input_file
         else f"{tool.name} {e.input} -> {e.expected!r}")
        for e in public[:3])
    statement = (
        f"{goal.strip()} 交付形态为标准工具包(TOOL_PACKAGE_LAYOUT):在骨架 "
        f"src/{package}/impl.py 实现 extract(),必须调用 pinned {distribution};"
        f"依赖锁进 requirements.lock.txt(replay 从它重建)。行为以公开样例为准"
        f"(例:{ex_lines});坏输入抛 UserInputError(→exit 1);重复调用确定;"
        "完全离线 CPU-only。骨架锚定件(main.py/bin/build.sh/tool.json/pyproject)"
        "不可改。公开样例与可运行公开测试位于骨架 public_tests/ 下,是本合同的一部分。"
    )
    tool_yaml = json.dumps(tool.model_dump(), ensure_ascii=False)  # 单行 JSON 即合法 YAML
    files[f"contracts/{task_id}.yaml"] = f"""task_id: {task_id}

source_repo:
  url: {repo_url}
  revision: guided
  resolved_commit: {resolved_commit}
  license: {license_id}
  distribution: {distribution}
  import_module: {import_module}

target_project:
  kind: local_tool
  path: {skel_rel}
  package: {package}
  entry_point: {tool.name}

requirement_spec_file: {task_id}.requirements.yaml
task_family: LOCAL-TOOL
adoption_shape: TOOL_ONBOARDING

tool: {tool_yaml}

capability:
  statement: >
    {statement}
  output_schema: {tool.interface.output.format}

environment: {{os: linux, arch: arm64, python: "3.12", cpu_only: true, network_install: true, network_test: false}}

constraints:
  forbidden: [gpu, privileged_container, oracle_write, model_download, network_at_test_time]
  editable_zones: [tool]
  forbidden_install_extras: []

budgets:
  max_agent_steps: 20
  max_wall_time_minutes: 30
  max_command_minutes: 5
  max_semantic_recoveries: 3
  max_same_action: 2
  max_patch_files: 12
  max_patch_lines: 600
  max_input_tokens_total: 400000
  max_output_tokens_total: 40000
  monetary_soft_cap_usd: 5.0

acceptance:
  capability_command: ["pytest", "-q", "/oracle/test_capability.py"]
  regression_command: ["pytest", "-q", "/oracle/test_regression.py"]
  probe_script: direct_tool_probe.py
"""

    # ---- RequirementSpec(NC_reimpl 不进 battery:判死在 provenance 层)----
    n_pub, n_held = len(public), len(held)
    cap_nodes = "\n".join(f'      - "test_capability::test_example_{i + 1}"' for i in range(n_pub))
    held_nodes = "\n".join(f'      - "test_capability::test_held_example_{i + 1}"' for i in range(n_held))
    files[f"contracts/{task_id}.requirements.yaml"] = f"""task_id: {task_id}

controls:
  positive: controls/{task_id}/positive
  negatives:
    - path: controls/{task_id}/negative_empty
      label: NC_empty
      must_fail_nodes: ["test_example"]
    - path: controls/{task_id}/negative_hardcode
      label: NC_hardcode
      must_fail_nodes: ["test_held_example"]
    - path: controls/{task_id}/negative_badexit
      label: NC_badexit
      must_fail_nodes: ["test_malformed_input_is_user_error"]
  # NC_reimpl(零 import 上游)不在此表:它在 oracle 上全绿,判死属
  # provenance 层(runner 验证阶段执法;harness 测试喂它自证查得出)。
  # 见 TOOL_READY_GATE §五。目录:controls/{task_id}/negative_reimpl

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
{cap_nodes}
{held_nodes}
  - id: interface-contract
    owner: ADAPTER
    severity: HARD
    source_field: capability.statement
    public_text: >
      坏输入内容抛 UserInputError(骨架转 exit 1);不得让异常裸奔到
      兜底层(exit 2);重复调用同一输入输出逐字节一致;成功路径不向
      stderr 泄漏 traceback。
    examples:
      - "exit: 0=成功 1=用户错误 2=内部错误"
    oracle_nodes:
      - "test_regression::test_malformed_input_is_user_error"
      - "test_regression::test_deterministic_output"
      - "test_regression::test_stdout_purity_on_success"
  - id: skeleton-anchors-untouched
    owner: HOST_INPUT_GUARD
    severity: HARD
    source_field: capability.statement
    public_text: >
      骨架锚定件(main.py / bin/ / build.sh / tool.json / pyproject.toml)
      与其 argparse/输入存在检查/exit 语义由 harness 预置,不可修改,
      不计 agent 能力。
    examples:
      - "{tool.name} --help -> usage"
    oracle_nodes:
      - "test_regression::test_help_reachable"
      - "test_regression::test_missing_input_is_user_error"
"""

    # ---- 工具骨架 ----
    io_in, io_out = tool.interface.input, tool.interface.output
    files[f"{skel_rel}/tool.json"] = _tool_json(
        tool, repo_url=repo_url, commit=resolved_commit,
        license_id=license_id, distribution=distribution)
    files[f"{skel_rel}/README.md"] = _README.format(
        name=tool.name, summary=tool.summary, usage=tool.interface.usage,
        repo_url=repo_url, commit=resolved_commit, license=license_id)
    files[f"{skel_rel}/bin/{tool.name}"] = _BIN_SH.format(package=package)
    files[f"{skel_rel}/build.sh"] = _BUILD_SH
    files[f"{skel_rel}/pyproject.toml"] = _PYPROJECT.format(
        package=package, summary=tool.summary)
    files[f"{skel_rel}/requirements.lock.txt"] = (
        f"# agent 填:全量 pinned(必须含 {distribution}=={{pinned 版本}});"
        "replay 从本文件重建 venv。\n")
    files[f"{skel_rel}/src/{package}/__init__.py"] = _INIT_PY
    files[f"{skel_rel}/src/{package}/__main__.py"] = _MAIN_MOD
    files[f"{skel_rel}/src/{package}/main.py"] = _MAIN_PY.format(
        name=tool.name, summary=tool.summary, in_format=io_in.format)
    files[f"{skel_rel}/src/{package}/impl.py"] = _IMPL_PY.format(
        distribution=distribution, in_format=io_in.format, out_format=io_out.format)

    # ---- 公开样例 + 公开测试(文件本体:仅公开子集)----
    files[f"{skel_rel}/public_examples/truth_table.json"] = json.dumps(
        {"note": "用户样例(公开子集)。文件样例的 held-out 本体只在 oracle 区。",
         "examples": [e.model_dump(exclude_none=True) for e in public]},
        ensure_ascii=False, indent=1)
    files[f"{skel_rel}/public_tests/test_public_contract.py"] = compile_pytest(
        public, header="公开合同测试 — agent 可运行自测", mode="cli")
    for e in public:
        for rel in (e.input_file, e.expected_file):
            if rel:
                copies.append((example_src_dir / rel,
                               f"{skel_rel}/public_tests/fixtures/{rel}"))

    # ---- oracle:capability(公开+held-out+文件本体全量)+ 接口契约 ----
    pub_src = compile_pytest(public, header="验收(公开样例)", mode="cli")
    held_src = compile_pytest(held, header="验收(held-out 样例,agent 不可见)",
                              mode="cli").replace("def test_example_",
                                                  "def test_held_example_")
    held_body = held_src.split('"""')[2]
    # held 段砍掉重复 prelude(公开段已含),只留测试函数
    held_tests = held_body[held_body.index("def test_held_example_"):]
    files[f"oracle/{task_id}/test_capability.py"] = pub_src + "\n\n" + held_tests
    first_file = next(e.input_file for e in exs if e.input_file)
    files[f"oracle/{task_id}/test_regression.py"] = _REGRESSION_TMPL.format(
        ext=input_ext, det_input=first_file)
    for e in [*public, *held]:
        for rel in (e.input_file, e.expected_file):
            if rel:
                copies.append((example_src_dir / rel, f"oracle/{task_id}/fixtures/{rel}"))
    files[f"oracle/{task_id}/fixtures/malformed{input_ext}"] = (
        "this is not a valid " + io_in.format + " payload\n")
    files[f"oracle/{task_id}/fixtures/public_documents.json"] = json.dumps(
        {"examples": [e.model_dump(exclude_none=True) for e in public]}, ensure_ascii=False)
    files[f"oracle/{task_id}/fixtures/held_out_documents.json"] = json.dumps(
        {"examples": [e.model_dump(exclude_none=True) for e in held]}, ensure_ascii=False)

    # ---- 控制组(impl.py 变体)----
    def _map(es: list[Example]) -> dict[str, str]:
        return {Path(e.input_file).name: _expected_text(e, example_src_dir)
                for e in es if e.input_file}

    full_map, pub_map = _map([*public, *held]), _map(public)
    files[f"controls/{task_id}/positive/impl.py"] = _CTRL_POSITIVE.format(
        label="正控:全样例硬编码 — 只证明样例测试自洽可满足", mapping=full_map)
    files[f"controls/{task_id}/negative_empty/impl.py"] = _CTRL_EMPTY
    files[f"controls/{task_id}/negative_hardcode/impl.py"] = _CTRL_POSITIVE.format(
        label="NC_hardcode:只硬编码公开样例 — held-out 必须杀它", mapping=pub_map)
    files[f"controls/{task_id}/negative_reimpl/impl.py"] = _CTRL_POSITIVE.format(
        label="NC_reimpl:全样例但零 import 上游 — provenance 必须抓", mapping=full_map)
    files[f"controls/{task_id}/negative_badexit/impl.py"] = _CTRL_BADEXIT.format(
        label="NC_badexit:坏输入不包装,裸奔→exit 2 — 接口契约必须抓", mapping=full_map)

    # ---- 落盘 ----
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    for src, rel in copies:
        if not src.is_file():
            raise CompileError(f"样例文件不存在:{src}(adequacy T3 同律,拒装配)")
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    for rel in (f"{skel_rel}/bin/{tool.name}", f"{skel_rel}/build.sh"):
        (root / rel).chmod(0o755)

    contract = root / "contracts" / f"{task_id}.yaml"
    sha = hashlib.sha256(contract.read_bytes()).hexdigest()
    (root / "contracts" / f"{task_id}.yaml.sha256").write_text(
        f"{sha}  {contract.name}\n", encoding="utf-8")

    return {"task_id": task_id, "files": sorted([*files, *(r for _, r in copies)]),
            "public": n_pub, "held": n_held,
            "next": f".venv/bin/python -m repoproof.cli freeze-task "
                    f"--contract contracts/{task_id}.yaml --full"}
