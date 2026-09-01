"""ToolContract → host_guided 任务包的物化桥(M1 · 侦察 11.2/11.3)。

职责边界:
  - `tool_assembler` 产**出题面文件**(A 谱系布局:contracts/ oracle/
    fixtures/ controls/);
  - 本桥把它**物化**成 `HostGuidedRunner` 吃的任务包:
      <out_root>/<task_id>/contract.yaml     合成 HostContract(YAML)
      <out_root>/<task_id>/oracle/           ← copytree(oracle/<task_id>)
      <out_root>/<task_id>/public_tests/     ← 骨架 public_tests(运行期由
                                               _assemble 注回会话)
      <out_root>/<task_id>/controls/<name>/  impl.py + apply.patch +
                                               smoke_setup.txt(fake 用)
      <host_copy_root>/<task_id>/host/       骨架副本(减 public_tests,
                                               避免 _assemble copytree 冲突)
      <host_copy_root>/<task_id>/wheelhouse/ 轮仓(mkdir;内容调用方备)
  - host_guided 本体只认路径与 HostContract schema,一行不为本桥而改。

host.commit = 骨架树内容哈希 —— 骨架变了就是换了一道题(语义指纹同律)。
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

import yaml

from repoproof.adoption.intake.upstream_conformance import precheck_upstream_conformance
from repoproof.domain.models import TaskContract

_ANCHOR_RULE = ("skeleton anchor files (src/*/main.py, bin/, build.sh, tool.json, "
                "pyproject.toml) are FROZEN — modifying them is a policy violation")

_DEFAULT_SETUP = [
    ["python3", "-m", "venv", ".venv"],
    [".venv/bin/pip", "install", "-q", "--no-index", "-r", "requirements.lock.txt"],
    [".venv/bin/pip", "install", "-q", "--no-index", "-e", ".", "pytest"],
]

_CONTROL_BRIDGE_PROTOCOL = "tool-host-controls-v2"


class ToolBridgeError(RuntimeError):
    pass


def _tree_sha(root: Path) -> str:
    """骨架树内容哈希(路径+字节,排序确定)。"""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            h.update(str(p.relative_to(root)).encode())
            h.update(b"\0")
            h.update(p.read_bytes())
            h.update(b"\0")
    return h.hexdigest()


def _hard_requirements(project_root: Path, tc: TaskContract) -> list[dict]:
    from repoproof.harness.requirement_spec import load_requirement_spec

    spec_file = project_root / "contracts" / (tc.requirement_spec_file or "")
    if not spec_file.is_file():
        raise ToolBridgeError(f"RequirementSpec 不存在:{spec_file}")
    spec, _ = load_requirement_spec(spec_file)
    return [{"id": r.id, "text": " ".join(r.public_text.split())}
            for r in spec.requirements]


def synthesize_host_contract(
    tc: TaskContract,
    requirements: list[dict],
    *,
    host_copy: Path,
    wheelhouse: Path,
    skeleton_commit: str,
    setup_commands: list[list[str]] | None = None,
    max_rounds: int = 3,
    hook_min_calls: int = 1,
) -> dict:
    """ToolContract → HostContract 的 YAML-ready dict(纯数据,零 IO)。

    字段映射依据侦察报告 §11.3;预算映射 §11.4(per_round 语义,
    max_command_minutes / monetary_soft_cap 在 host_guided 不生效,不搬)。
    """
    if tc.task_family != "LOCAL-TOOL" or tc.tool is None:
        raise ToolBridgeError(
            f"{tc.task_id}: 不是 LOCAL-TOOL 契约(task_family={tc.task_family!r})")
    name = tc.tool.name
    b = tc.budgets
    doc: dict = {
        "task_id": tc.task_id,
        "task_version": "v1",
        "kind": "host_integrated",          # HostContract.load 硬校验值
        "prompt_profile": (
            "workspace-tool-v1"
            if tc.tool.delivery_profile_id == "workspace_bundle_v1"
            else "local-tool-v1"
        ),
        "task_family": "LOCAL-TOOL",
        "adoption_shape": "TOOL_ONBOARDING",
        "runtime_profile": tc.runtime_profile,
        "source_repo": {
            "url": tc.source_repo.url,
            "resolved_commit": tc.source_repo.resolved_commit,
            "distribution": tc.source_repo.distribution,
            "import_module": tc.source_repo.import_name,
            "license": tc.source_repo.license,
        },
        "host": {
            "repo": f"local-tool/{name}",   # 台账 host_id(append_run 硬要求非空)
            "commit": skeleton_commit,
            "copy_path": str(host_copy),
            "regression_command": [
                ".venv/bin/python", "-m", "pytest",
                "public_tests/test_interface_contract.py",
                "-q", "-p", "no:cacheprovider"],
            "regression_baseline": "",
            "setup_commands": setup_commands or _DEFAULT_SETUP,
            "health_checks": [
                {"command": [f"./bin/{name}", "--help"],
                 "pass_if_stdout_contains": "usage", "gating": True}],
            "host_root_env": "REPOPROOF_TOOL_ROOT",
            "wheelhouse_path": str(wheelhouse),
            "require_wheelhouse_manifest": False,
            "path_prepend_venv_bin": True,
            "pii_scan_profile": "public-oss-tree",   # 骨架 harness 生成,无用户数据
            "oracle_env_sanitized": True,            # oracle 走 subprocess,不 import 宿主
            "tool_bin": f"bin/{name}",               # → REPOPROOF_TOOL_BIN 注入
            # M2-c([D4] 运行时升级):验收期 import-hook 取证;min_calls 由
            # 调用方按文件样例数合成(materialize 数得出)。
            "import_hook_module": tc.source_repo.import_name,
            "import_hook_min_calls": max(1, hook_min_calls),
        },
        "capability": {
            "statement": tc.capability.statement,
            "requirements": requirements,
        },
        "constraints": {
            "editable_zones": ["."],                 # 骨架即 host 根,diff 全计
            "forbidden": [*tc.constraints.forbidden, _ANCHOR_RULE],
            "network_at_test_time": False,
        },
        "budgets": {
            "semantics": "per_round",
            "max_rounds": max_rounds,
            "max_model_calls": b.max_agent_steps,
            "max_commands": 100,
            "max_patch_files": b.max_patch_files,
            "max_patch_lines": b.max_patch_lines,
            "max_wall_time_minutes": b.max_wall_time_minutes,
            "max_input_tokens_total": b.max_input_tokens_total,
            "max_output_tokens_total": b.max_output_tokens_total,
        },
        "acceptance": {
            "public_test_command": [
                "python", "-m", "pytest", "public_tests", "-q",
                "-p", "no:cacheprovider"],
            # 声明如实;当前 host_guided 的 _run_oracle 硬编码 pytest 跑
            # oracle 快照(侦察 §11.5 M11 已知开口),本键暂无消费者。
            "hidden_oracle_command": [
                "python", "-m", "pytest", "<ORACLE_SNAPSHOT>", "-q"],
        },
        "failure_taxonomy_expected": [
            "UPSTREAM_CAPABILITY_REIMPLEMENTED", "IMPL_INCOMPLETE",
            "DEPENDENCY_NOT_REPRODUCIBLE", "INSTRUMENT_TAMPERED",
            "HARNESS_FAILURE", "PROVIDER_FAILURE"],
    }
    return doc


def _unified_patch(rel: str, old: str, new: str) -> str:
    """git-apply 兼容的单文件 unified diff。"""
    lines = difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"a/{rel}", tofile=f"b/{rel}")
    return "".join(lines)


def _workspace_reference_as_staging_adapter(reference_source: str) -> str:
    """Adapt a final-directory reference to the workspace adapter protocol.

    A workspace reference owns creation of a previously absent output path.
    The delivered adapter deliberately has a different boundary: Core creates
    an empty staging directory first, then asks ``impl.build_workspace`` to
    populate it before validation and atomic placement.  Reusing the reference
    source verbatim as the fake-positive adapter therefore makes every valid
    reference reject the Harness-owned staging directory.

    Keep the frozen reference implementation intact and append a tiny protocol
    bridge for the Harness-only positive control.  The reference still performs
    the real upstream call inside a fresh child directory; only its children are
    moved into the already-created staging directory afterwards.
    """

    bridge = r'''

# Harness-only protocol bridge: the reference above creates a new final
# directory, while the adapter slot receives an existing empty staging root.
_repoproof_reference_build_workspace_v1 = build_workspace


def build_workspace(input_path, output_dir) -> None:
    if not output_dir.is_dir() or any(output_dir.iterdir()):
        raise RuntimeError("REPOPROOF_WORKSPACE_STAGING_NOT_EMPTY")
    reference_output = output_dir / ".repoproof-reference-output"
    _repoproof_reference_build_workspace_v1(input_path, reference_output)
    if not reference_output.is_dir():
        raise RuntimeError("REPOPROOF_REFERENCE_OUTPUT_MISSING")
    for child in sorted(reference_output.iterdir(), key=lambda item: item.name):
        child.replace(output_dir / child.name)
    reference_output.rmdir()
'''
    return reference_source.rstrip() + "\n" + bridge.lstrip("\n")


def _write_host_control_groups(
    *,
    tc: TaskContract,
    skeleton: Path,
    controls_src: Path,
    destination: Path,
) -> None:
    """Materialize Harness-only controls from frozen task sources."""

    if destination.exists():
        raise ToolBridgeError(f"控制组物化目标已存在:{destination}")
    destination.mkdir(parents=True)
    skel_impl_rel = f"src/{tc.target_project.package}/impl.py"
    skel_impl = (skeleton / skel_impl_rel).read_text(encoding="utf-8")
    skel_lock = (skeleton / "requirements.lock.txt").read_text(encoding="utf-8")
    src_of = {"positive": "reference", "negative_reimpl": "positive"}
    wanted = ["positive", "negative_empty", "negative_hardcode", "negative_reimpl"]
    if (controls_src / "negative_badexit" / "impl.py").is_file():
        wanted.append("negative_badexit")
    for host_name in wanted:
        ctrl = controls_src / src_of.get(host_name, host_name)
        if not (ctrl / "impl.py").is_file():
            raise ToolBridgeError(f"{tc.task_id}: 控制源缺失:{ctrl}/impl.py")
        dst = destination / host_name
        dst.mkdir()
        control_source = (ctrl / "impl.py").read_text(encoding="utf-8")
        if (
            host_name == "positive"
            and tc.tool is not None
            and tc.tool.delivery_profile_id == "workspace_bundle_v1"
        ):
            control_source = _workspace_reference_as_staging_adapter(control_source)
        (dst / "impl.py").write_text(control_source, encoding="utf-8")
        patch = _unified_patch(skel_impl_rel, skel_impl, control_source)
        ctrl_lock = ctrl / "requirements.lock.txt"
        if ctrl_lock.is_file():
            patch += _unified_patch(
                "requirements.lock.txt",
                skel_lock,
                ctrl_lock.read_text(encoding="utf-8"),
            )
        (dst / "apply.patch").write_text(patch, encoding="utf-8")
        smoke = ["# 环境由契约 host.setup_commands 建;补丁后依赖见下。"]
        if host_name == "positive" and ctrl_lock.is_file():
            pins = [
                line.strip()
                for line in ctrl_lock.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            if pins:
                smoke.append(
                    ".venv/bin/pip install -q --no-index " + " ".join(pins)
                )
        smoke.append("echo rp-tool-smoke-ready")
        (dst / "smoke_setup.txt").write_text(
            "\n".join(smoke) + "\n", encoding="utf-8"
        )


def _write_control_bridge_marker(
    task_dir: Path,
    *,
    tool_contract_sha256: str,
) -> None:
    marker = task_dir / "control_materialization.json"
    document = {
        "schema_version": 1,
        "protocol": _CONTROL_BRIDGE_PROTOCOL,
        "tool_contract_sha256": tool_contract_sha256,
        "controls_tree_sha256": _tree_sha(task_dir / "controls"),
    }
    temporary = marker.with_name(f".{marker.name}.tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, marker)


def ensure_materialized_tool_controls_current(
    project_root: Path,
    tool_contract_path: Path,
    host_contract_path: Path,
) -> bool:
    """Refresh stale derived controls without changing frozen task truth.

    ``tool_tasks/<task>/controls`` is a disposable bridge product, not an
    append-only contract or historical run.  A frozen-task resume used to keep
    this directory forever, so a generic Harness fix could be silently bypassed
    by an older materialization.  Bind it to the current bridge protocol and
    frozen contract digest, then rebuild it atomically when either identity is
    absent, stale, or damaged.
    """

    project_root = Path(project_root)
    tool_contract_path = Path(tool_contract_path)
    host_contract_path = Path(host_contract_path)
    tc, digest = TaskContract.load_frozen(tool_contract_path, require_sidecar=True)
    if tc.tool is None:
        raise ToolBridgeError(f"{tc.task_id}: 缺少工具合同")
    task_dir = host_contract_path.parent
    controls = task_dir / "controls"
    marker = task_dir / "control_materialization.json"
    try:
        current = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        current = {}
    if (
        current.get("protocol") == _CONTROL_BRIDGE_PROTOCOL
        and current.get("tool_contract_sha256") == digest
        and controls.is_dir()
        and current.get("controls_tree_sha256") == _tree_sha(controls)
    ):
        return False

    skeleton = project_root / tc.target_project.path
    controls_src = project_root / "controls" / tc.task_id
    if not skeleton.is_dir() or not controls_src.is_dir():
        raise ToolBridgeError(
            f"{tc.task_id}: 无法从冻结骨架和控制源刷新物化控制组"
        )
    temporary_root = Path(
        tempfile.mkdtemp(prefix=f".{tc.task_id}-controls-", dir=task_dir)
    )
    generated = temporary_root / "controls"
    backup = task_dir / f".controls-backup-{os.getpid()}"
    try:
        _write_host_control_groups(
            tc=tc,
            skeleton=skeleton,
            controls_src=controls_src,
            destination=generated,
        )
        if backup.exists():
            raise ToolBridgeError(f"控制组刷新备份位已存在:{backup}")
        if controls.exists():
            os.replace(controls, backup)
        os.replace(generated, controls)
        _write_control_bridge_marker(task_dir, tool_contract_sha256=digest)
        if backup.exists():
            shutil.rmtree(backup)
    except BaseException:
        if not controls.exists() and backup.exists():
            os.replace(backup, controls)
        raise
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
    return True


def materialize_tool_task(
    project_root: Path,
    contract_path: Path,
    *,
    out_root: Path,
    host_copy_root: Path,
    setup_commands: list[list[str]] | None = None,
    max_rounds: int = 3,
    upstream_conformance: list[str] | None = None,
    conformance_python: Path | None = None,
    upstream_conformance_record: dict | None = None,
) -> Path:
    """装配产物 → host_guided 任务包 + 宿主副本。返回合成 contract.yaml 路径。

    冻结纪律:只吃带 .sha256 sidecar 的 ToolContract(改题面必先重冻结)。
    幂等性:目标已存在则拒绝 —— 物化产物按任务包对待,不静默覆盖。
    """
    tc, contract_digest = TaskContract.load_frozen(
        contract_path, require_sidecar=True
    )
    if tc.task_family != "LOCAL-TOOL" or tc.tool is None:
        raise ToolBridgeError(f"{tc.task_id}: 不是 LOCAL-TOOL 契约")

    skeleton = project_root / tc.target_project.path
    oracle_src = project_root / "oracle" / tc.task_id
    controls_src = project_root / "controls" / tc.task_id
    for p, what in ((skeleton, "骨架"), (oracle_src, "oracle"), (controls_src, "控制组")):
        if not p.is_dir():
            raise ToolBridgeError(f"{tc.task_id}: {what}目录不存在:{p}")
    if not (skeleton / "public_tests").is_dir():
        raise ToolBridgeError(f"{tc.task_id}: 骨架缺 public_tests/")

    task_dir = Path(out_root) / tc.task_id
    host_base = Path(host_copy_root) / tc.task_id
    for p in (task_dir, host_base):
        if p.exists():
            raise ToolBridgeError(f"物化目标已存在,拒绝覆盖:{p}")

    # 宿主副本 = 骨架 - public_tests(运行期由 _assemble 从任务包注回,
    # 若骨架自带则 copytree(dirs_exist_ok=False) 当场冲突)
    host_copy = host_base / "host"
    shutil.copytree(skeleton, host_copy,
                    ignore=shutil.ignore_patterns("public_tests"))
    wheelhouse = host_base / "wheelhouse"
    wheelhouse.mkdir(parents=True)

    shutil.copytree(oracle_src, task_dir / "oracle")
    shutil.copytree(skeleton / "public_tests", task_dir / "public_tests")

    # 控制组物化(host 任务包 controls/ 专供 fake 全链;与 A 谱系 controls/
    # 的 battery 角色分离):
    #   positive        ← A 谱系 reference(真 import 上游 —— 弱档 provenance
    #                     执法下唯一能通关的正控;硬编码件必死,不能充当)
    #   negative_reimpl ← A 谱系 positive(硬编码全样例零 import,正是
    #                     NC_reimpl 的定义 —— 一物一名,不造第二份)
    #   其余同名搬运。apply.patch 供 _fake_script 的 git-apply 形态;
    #   控制目录若带 requirements.lock.txt(reference 常带,锁上游 pinned),
    #   diff 一并入 patch —— agent 真实工作=改 impl+锁依赖,正控必须同构。
    _write_host_control_groups(
        tc=tc,
        skeleton=skeleton,
        controls_src=controls_src,
        destination=task_dir / "controls",
    )
    _write_control_bridge_marker(
        task_dir, tool_contract_sha256=contract_digest
    )

    requirements = _hard_requirements(project_root, tc)
    # hook 最低调用数 = 文件样例数(公开+held-out;每个文件样例至少应
    # 触发一次上游调用 —— 弱 U3,如实弱于 sidecar 逐项对应)
    import json as _json

    n_file_examples = 0
    for doc_name in ("public_documents.json", "held_out_documents.json"):
        p = oracle_src / "fixtures" / doc_name
        if p.is_file():
            n_file_examples += sum(
                1
                for e in _json.loads(p.read_text(encoding="utf-8"))["examples"]
                if e.get("input_file") or e.get("input_path")
            )
    # M2-e 物化期预检:选中子集在 harness 侧解释器上必须绿(供给问题
    # 早暴露);记录落任务包 conformance.json。未给解释器 = 只记选取。
    conf_record = (
        dict(upstream_conformance_record)
        if upstream_conformance_record is not None
        else {"selected": upstream_conformance or [], "status": "SKIPPED"}
    )
    if (
        upstream_conformance_record is None
        and upstream_conformance
        and conformance_python is not None
    ):
        up_dir = (project_root / "upstream-cache"
                  / f"upstream-{tc.source_repo.resolved_commit[:12]}")
        try:
            conf_record = precheck_upstream_conformance(
                up_dir, upstream_conformance, conformance_python)
        except RuntimeError as e:
            raise ToolBridgeError(str(e)) from e
    doc = synthesize_host_contract(
        tc, requirements, host_copy=host_copy, wheelhouse=wheelhouse,
        skeleton_commit=_tree_sha(skeleton), setup_commands=setup_commands,
        max_rounds=max_rounds, hook_min_calls=n_file_examples)
    (task_dir / "conformance.json").write_text(
        _json.dumps(conf_record, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    out_contract = task_dir / "contract.yaml"
    out_contract.write_text(
        "# 由 tool_host_bridge 从冻结 ToolContract 合成;手改此文件=换题。\n"
        f"# 源契约:contracts/{tc.task_id}.yaml(sha256 见其 sidecar)\n"
        + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    return out_contract
