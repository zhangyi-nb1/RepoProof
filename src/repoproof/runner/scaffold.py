"""Task scaffolding (Gate 8D): ``task init`` + ``task check``.

``task init`` writes a DRAFT task skeleton with explicit TODO markers —
it never guesses hard requirements, never freezes, never overwrites an
existing task, never calls a model, never touches the network.

``task check`` is a READ-ONLY adequacy pre-flight for draft tasks: it
reports READY_TO_FREEZE or INVALID_TASK_SPEC with concrete gaps, and
on success prints the existing ``freeze-task`` command (no second
freeze implementation).
"""

from __future__ import annotations

import re
from pathlib import Path

TODO = "TODO"

CONTRACT_TEMPLATE = """\
# DRAFT task contract — replace every TODO, then run:
#   repoproof task check --task-id {task_id}
# Normative semantics belong in capability.statement and the
# RequirementSpec, NEVER in comments.

task_id: {task_id}

source_repo:
  url: {source_repo_url}
  revision: TODO-tag-or-branch
  resolved_commit: {source_commit}
  license: TODO-license-id
  distribution: {distribution}
  import_module: TODO-import-name-if-different

target_project:
  kind: consumer_fixture
  path: {target_project}
  package: TODO-python-package
  entry_point: TODO-entry-function

requirement_spec_file: {task_id}.requirements.yaml

capability:
  statement: >
    {capability_statement}
    TODO: state the FULL public semantics here — output schema fields,
    boolean truth-table rules, error wrapping, ordering, determinism,
    offline constraint. The prompt is rendered from THIS text plus the
    RequirementSpec public_text entries.
  output_schema: TODO-RecordName

environment:
  os: linux
  arch: arm64
  python: "3.12"
  cpu_only: true
  network_install: true
  network_test: false

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
  probe_script: TODO-probe-script.py
"""

REQUIREMENTS_TEMPLATE = """\
task_id: {task_id}

controls:
  positive: controls/{task_id}/positive
  negatives:
    - path: controls/{task_id}/negative_nc1
      label: NC1_TODO_describe_cheat
      must_fail_nodes: ["TODO-oracle-node-substring"]

requirements:
  - id: TODO-first-requirement
    owner: ADAPTER
    severity: HARD
    source_field: capability.statement
    public_text: >
      TODO: one verifiable public rule, verbatim-renderable into the
      agent prompt.
    examples:
      - "TODO input -> TODO output"
    oracle_nodes:
      - "test_capability::TODO_node_name"

  - id: TODO-input-guard
    owner: HOST_INPUT_GUARD
    severity: HARD
    deterministic_input_boundary: true
    source_field: capability.statement
    public_text: >
      TODO: which malformed inputs the HOST guard rejects (stable
      error code), so agents never re-implement input validation.
    examples:
      - "TODO bad input -> stable error code"
    oracle_nodes:
      - "test_capability::TODO_guard_node"
"""

RESPONSIBILITY_TEMPLATE = """\
# Responsibility overview for {task_id} (DRAFT).
# The AUTHORITATIVE matrix is derived from {task_id}.requirements.yaml
# owners at freeze time and frozen into the TaskPackage. Use this file
# to PLAN ownership before writing requirements; keep them consistent.
task_id: {task_id}
planned_ownership:
  HOST_INPUT_GUARD: [TODO-list-input-boundary-requirements]
  ADAPTER: [TODO-list-agent-owned-requirements]
  HARNESS: [offline-enforcement, isolation, budgets, trace, replay]
  UPSTREAM: [pinned-behaviour-definition]
"""

ORACLE_README_TEMPLATE = """\
# Oracle for {task_id} (DRAFT)

Write test_capability.py / test_regression.py from the .template
files. Rules: reference-calibrate expected outputs from the PINNED
upstream inside the pinned container (never hand-write expectations);
held-out fixtures may only recombine PUBLIC semantics; node names here
must match RequirementSpec oracle_nodes.
"""

TEST_TEMPLATE = """\
# TODO: rename to {name} (drop .template) once written.
# Node ids must match the RequirementSpec oracle_nodes entries.
# Reference-calibrate expectations from the pinned upstream.
"""

TASK_DOC_TEMPLATE = """\
# {task_id} (DRAFT)

- Status: DRAFT — not frozen, not runnable
- TODO: solvability rationale (why the pinned upstream is the path of
  least resistance), calibration notes, control design.
"""


def task_init(
    project_root: Path,
    *,
    task_id: str,
    source_repo_url: str = TODO,
    source_commit: str = TODO,
    distribution: str = TODO,
    target_project: str = "",
    capability_statement: str = TODO,
    dry_run: bool = False,
) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", task_id):
        return {"ok": False, "error": f"task_id {task_id!r} must be kebab-case [a-z0-9-]"}
    contract = project_root / "contracts" / f"{task_id}.yaml"
    if contract.exists():
        return {"ok": False, "error": f"refusing to overwrite existing task: {contract.name}"}
    target = target_project or f"fixtures/consumer_{task_id.replace('-', '_')}"
    files: dict[Path, str] = {
        contract: CONTRACT_TEMPLATE.format(
            task_id=task_id, source_repo_url=source_repo_url, source_commit=source_commit,
            distribution=distribution, target_project=target,
            capability_statement=capability_statement,
        ),
        project_root / "contracts" / f"{task_id}.requirements.yaml": REQUIREMENTS_TEMPLATE.format(task_id=task_id),
        project_root / "contracts" / f"{task_id}.responsibility.yaml": RESPONSIBILITY_TEMPLATE.format(task_id=task_id),
        project_root / "oracle" / task_id / "README.md": ORACLE_README_TEMPLATE.format(task_id=task_id),
        project_root / "oracle" / task_id / "test_capability.py.template":
            TEST_TEMPLATE.format(name="test_capability.py"),
        project_root / "oracle" / task_id / "test_regression.py.template":
            TEST_TEMPLATE.format(name="test_regression.py"),
        project_root / "docs" / "tasks" / f"{task_id}.md": TASK_DOC_TEMPLATE.format(task_id=task_id),
    }
    dirs = [
        project_root / "oracle" / task_id / "fixtures",
        project_root / Path(target),
        project_root / "controls" / task_id / "positive",
        project_root / "controls" / task_id / "negative_nc1",
    ]
    plan = {"files": [str(p.relative_to(project_root)) for p in files],
            "dirs": [str(d.relative_to(project_root)) for d in dirs]}
    if dry_run:
        return {"ok": True, "dry_run": True, "state": "DRAFT", **plan}
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        (d / ".gitkeep").touch()
    return {"ok": True, "dry_run": False, "state": "DRAFT", **plan}


def task_check(project_root: Path, task_id: str) -> dict:
    """Read-only draft adequacy pre-flight. Never writes, never fixes,
    never freezes, never calls a model."""
    import yaml

    from repoproof.domain.models import TaskContract
    from repoproof.harness.contract_adequacy import evaluate_adequacy
    from repoproof.harness.requirement_spec import SpecError, load_requirement_spec
    from repoproof.runner.agent_run import render_task_prompt
    from repoproof.verification.redaction import scan_file

    gaps: list[str] = []
    notes: list[str] = []
    contract_path = project_root / "contracts" / f"{task_id}.yaml"
    if not contract_path.exists():
        return {"state": "INVALID_TASK_SPEC", "ready": False, "gaps": [f"contract missing: {contract_path.name}"]}

    # TODO sweep over the task's own files
    todo_files: list[str] = []
    task_files = [
        contract_path,
        project_root / "contracts" / f"{task_id}.requirements.yaml",
        project_root / "contracts" / f"{task_id}.responsibility.yaml",
        *(project_root / "oracle" / task_id).rglob("*"),
    ]
    for p in task_files:
        if p.is_file() and p.suffix in (".yaml", ".yml", ".py", ".md", ".template", ".json"):
            if TODO in p.read_text(encoding="utf-8", errors="ignore"):
                todo_files.append(str(p.relative_to(project_root)))
    if todo_files:
        gaps.append(f"unresolved TODOs in: {todo_files}")

    # schemas
    contract = spec = None
    try:
        contract = TaskContract.model_validate(yaml.safe_load(contract_path.read_text(encoding="utf-8")))
    except Exception as exc:  # noqa: BLE001
        gaps.append(f"contract schema: {type(exc).__name__}: {str(exc)[:200]}")
    if contract is not None and not contract.requirement_spec_file:
        gaps.append("contract.requirement_spec_file not set")
    spec_name = (
        contract.requirement_spec_file
        if contract and contract.requirement_spec_file
        else f"{task_id}.requirements.yaml"
    )
    spec_path = project_root / "contracts" / spec_name
    try:
        spec, _sha = load_requirement_spec(spec_path)
    except FileNotFoundError:
        gaps.append(f"requirement spec missing: {spec_path.name}")
    except SpecError as exc:
        gaps.append(f"requirement spec: {exc}")
    except Exception as exc:  # noqa: BLE001
        gaps.append(f"requirement spec parse: {type(exc).__name__}: {str(exc)[:200]}")

    # adequacy subset (pre-freeze): prompt projection + structural checks
    if contract is not None and spec is not None:
        try:
            prompt, _s, _sha2 = render_task_prompt(contract, environment_constraints=None, project_root=project_root)
            from repoproof.harness.task_package import collection_path_for

            cpath = collection_path_for(contract_path)
            if cpath.exists():
                import json as _json

                coll = _json.loads(cpath.read_text(encoding="utf-8"))
                cap_nodes, reg_nodes = coll.get("capability_nodes", []), coll.get("regression_nodes", [])
            else:
                # pre-freeze: node EXISTENCE is freeze-task's job; check
                # the spec side self-consistently and note it, no gap
                cap_nodes, reg_nodes = sorted(spec.all_oracle_nodes()), []
                notes.append("oracle collection not frozen yet (node existence verified at freeze-task)")
            result = evaluate_adequacy(
                spec=spec, capability_nodes=cap_nodes, regression_nodes=reg_nodes,
                rendered_prompt=prompt, contract_path=contract_path,
                contract=contract,
                tool_example_docs_dir=(
                    project_root / "oracle" / contract.task_id / "fixtures"
                    if contract.task_family == "LOCAL-TOOL" else None
                ),
            )
            gaps.extend(result.failures)
        except Exception as exc:  # noqa: BLE001
            gaps.append(f"prompt projection: {type(exc).__name__}: {str(exc)[:200]}")

        if spec.controls is None:
            gaps.append("controls: spec.controls missing (positive + negatives required before freeze)")
        else:
            for rel in [spec.controls.positive] + [n.path for n in spec.controls.negatives]:
                if not (project_root / rel / "adapter.py").exists():
                    gaps.append(f"controls: {rel}/adapter.py not written")

        if not (project_root / "oracle" / task_id / "test_capability.py").exists():
            gaps.append("oracle: test_capability.py not written (template still pending)")

    # secret / path scan over the task's own text files
    findings = []
    for p in task_files:
        if p.is_file() and p.suffix in (".yaml", ".yml", ".py", ".md", ".json"):
            findings.extend(scan_file(p))
    if findings:
        gaps.append(f"secret/path scan: {findings[:3]}")

    ready = not gaps
    out = {"state": "READY_TO_FREEZE" if ready else "INVALID_TASK_SPEC", "ready": ready, "gaps": gaps, "notes": notes}
    if ready:
        out["next"] = f"repoproof freeze-task --contract contracts/{task_id}.yaml --full"
    return out
