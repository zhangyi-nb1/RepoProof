"""M6.2 assembler for one-input offline workspace-bundle tools.

The assembler is deliberately repository-blind.  Task-owned fixture builders,
reference implementations, and semantic verifiers carry domain behavior;
this module freezes the common CLI, atomic runtime, file-tree contract, public
examples, held-out examples, controls, and package layout.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from repoproof.adoption.assembly.example_compiler import CompileError
from repoproof.adoption.assembly.tool_assembler import next_tool_task_id
from repoproof.adoption.delivery import portable_workspace_runtime
from repoproof.adoption.intake.intent_contract import validate_frozen_intent_projection
from repoproof.adoption.intake.workspace_fixtures import FixtureBlueprintV1
from repoproof.domain.models import ToolSpec
from repoproof.execution.workspace_bundle import (
    build_artifact_manifest,
    identify_input_path,
    snapshot_admitted_path,
)


class WorkspaceGoldenExampleV1(BaseModel):
    """One exact user-confirmed input-directory-output binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    example_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    input_path: str
    expected_dir: str
    truth_provenance: Literal["UPSTREAM_DERIVED_USER_CONFIRMED"]
    truth_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("input_path", "expected_dir")
    @classmethod
    def _safe_relative_path(cls, value: str) -> str:
        candidate = Path(value)
        if (
            candidate.is_absolute()
            or not candidate.parts
            or any(part in {"", ".", ".."} for part in candidate.parts)
        ):
            raise ValueError("workspace example paths must be safe and relative")
        return candidate.as_posix()


def workspace_truth_binding_sha256(input_sha256: str, output_tree_sha256: str) -> str:
    digest = hashlib.sha256(b"REPOPROOF-WORKSPACE-TRUTH-BINDING-v1\x00")
    digest.update(bytes.fromhex(input_sha256))
    digest.update(bytes.fromhex(output_tree_sha256))
    return digest.hexdigest()


_MAIN = '''"""{name}: Harness-owned workspace CLI and failure semantics."""
import argparse
import json
import sys
from importlib.resources import files
from pathlib import Path

from . import impl
from .portable_workspace_runtime import WorkspaceRuntimeError, materialize_workspace


def _parser():
    parser = argparse.ArgumentParser(prog={name!r}, description={summary!r})
    parser.add_argument("input", help="one local input file or directory")
    parser.add_argument("--out-dir", required=True, help="new output directory")
    return parser


def cli(argv=None):
    args = _parser().parse_args(argv)
    source = Path(args.input)
    output = Path(args.out_dir)
    if source.is_symlink() or not (source.is_file() or source.is_dir()):
        print(f"error: input not found or unsafe: {{source}}", file=sys.stderr)
        return 1
    if output.exists() or output.is_symlink():
        print(f"error: output directory already exists: {{output}}", file=sys.stderr)
        return 1
    contract = json.loads(
        files(__package__).joinpath("workspace_contract.json").read_text(encoding="utf-8")
    )
    try:
        materialize_workspace(
            impl.build_workspace,
            source,
            output,
            contract,
            runtime_source_root=Path(__file__).resolve().parents[2],
        )
    except impl.UserInputError as exc:
        print(f"error: {{exc}}", file=sys.stderr)
        return 1
    except WorkspaceRuntimeError as exc:
        if exc.code.startswith("WORKSPACE_INPUT_") or exc.code == "WORKSPACE_OUTPUT_ALREADY_EXISTS":
            print(f"error: {{exc}}", file=sys.stderr)
            return 1
        print(f"internal error: {{exc}}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"internal error: {{type(exc).__name__}}: {{exc}}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
'''

_IMPL = '''"""Agent-owned composition slot; call pinned {distribution}."""
from pathlib import Path


class UserInputError(ValueError):
    pass


def build_workspace(input_path: Path, output_dir: Path) -> None:
    raise NotImplementedError("workspace composition is not implemented")
'''

_INIT = '''__all__ = ["cli"]
from .main import cli
'''

_MAIN_MOD = '''from .main import cli
raise SystemExit(cli())
'''

_BIN = '''#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/.venv/bin/python" -m {package} "$@"
'''

_BUILD = '''#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install --disable-pip-version-check -q --no-index \
  --find-links vendor/wheels -r requirements.lock.txt
.venv/bin/pip install --disable-pip-version-check -q --no-index \
  --find-links vendor/wheels -e .
echo "build ok: $(pwd)"
'''

_PYPROJECT = '''[project]
name = "{package}"
version = "1.0.0"
description = {summary!r}
requires-python = ">=3.12"

[tool.setuptools.package-data]
"{package}" = ["workspace_contract.json"]

[tool.setuptools.packages.find]
where = ["src"]
'''

_README = '''# {name}

{summary}

```bash
./build.sh
./bin/{name} <input-file-or-directory> --out-dir <new-directory>
```

The output path must not already exist.  The tool runs locally, atomically
publishes a validated directory, and removes partial output on failure.

Source: {repo_url} @ {commit} (license: {license_id}).
'''

_TEST_PRELUDE = r'''import hashlib
import os
import runpy
import stat
import subprocess
from pathlib import Path

_TOOL = os.environ["REPOPROOF_TOOL_BIN"]
_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _tree_sha(root):
    digest = hashlib.sha256(b"REPOPROOF-WORKSPACE-TREE-V1\0")
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        assert stat.S_ISREG(info.st_mode) and not path.is_symlink()
        payload = path.read_bytes()
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big")); digest.update(relative)
        digest.update(stat.S_IMODE(info.st_mode).to_bytes(4, "big"))
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(hashlib.sha256(payload).digest())
    return digest.hexdigest()


def _golden_sha(root):
    """Bind product bytes and executable semantics, not Oracle hardening.

    Frozen Oracle fixtures are intentionally chmod read-only.  The workspace
    contract separately checks whether each artifact is executable, so rw
    permission bits are storage protection rather than product truth.
    """
    digest = hashlib.sha256(b"REPOPROOF-WORKSPACE-GOLDEN-V1\0")
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        assert stat.S_ISREG(info.st_mode) and not path.is_symlink()
        payload = path.read_bytes()
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big")); digest.update(relative)
        digest.update(int(bool(stat.S_IMODE(info.st_mode) & 0o111)).to_bytes(1, "big"))
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(hashlib.sha256(payload).digest())
    return digest.hexdigest()


def _semantic_acceptance(source, output):
    verifier_path = Path(__file__).resolve().parent / "semantic_verifier.py"
    namespace = runpy.run_path(str(verifier_path))
    verify = namespace.get("verify")
    assert callable(verify), "frozen semantic verifier has no callable verify"
    result = verify(source, output)
    assert isinstance(result, dict), "semantic verifier returned a non-object"
    reasons = result.get("reason_codes") or []
    assert result.get("ok") is True, "semantic verifier rejected artifact: " + ",".join(
        str(item) for item in reasons
    )


def _run_case(tmp_path, example_id, *, exact=True):
    source = _FIXTURES / example_id / "input"
    expected = _FIXTURES / example_id / "expected"
    output = tmp_path / f"{example_id}-output"
    process = subprocess.run(
        [_TOOL, str(source), "--out-dir", str(output)],
        capture_output=True, text=True, timeout=120,
    )
    assert process.returncode == 0, process.stderr
    assert output.is_dir()
    if exact:
        assert _golden_sha(output) == _golden_sha(expected)
    else:
        _semantic_acceptance(source, output)
    return output
'''


def _test_source(
    examples: list[WorkspaceGoldenExampleV1],
    *,
    held: bool,
    smoke_command: tuple[str, ...] = (),
) -> str:
    body = [_TEST_PRELUDE]
    prefix = "held_example" if held else "example"
    for index, example in enumerate(examples, start=1):
        exact_argument = ", exact=False" if held else ""
        body.append(
            f"\ndef test_{prefix}_{index}(tmp_path):\n"
            f"    _run_case(tmp_path, {example.example_id!r}{exact_argument})\n"
        )
    if not held and examples:
        identifier = examples[0].example_id
        body.append(
            "\ndef test_workspace_output_is_deterministic(tmp_path):\n"
            f"    first = _run_case(tmp_path / 'one', {identifier!r})\n"
            f"    second = _run_case(tmp_path / 'two', {identifier!r})\n"
            "    assert _tree_sha(first) == _tree_sha(second)\n"
        )
        if smoke_command:
            entrypoint = smoke_command[0].removeprefix("./")
            arguments = list(smoke_command[1:])
            body.append(
                "\ndef test_workspace_runtime_smoke(tmp_path):\n"
                f"    workspace = _run_case(tmp_path, {identifier!r})\n"
                f"    argv = [str(workspace / {entrypoint!r}), *{arguments!r}]\n"
                "    process = subprocess.run(\n"
                "        argv, cwd=workspace, stdin=subprocess.DEVNULL,\n"
                "        capture_output=True, text=True, timeout=120,\n"
                "    )\n"
                "    assert process.returncode == 0, process.stderr\n"
            )
    return "".join(body)


def _interface_test_source(first_example_id: str) -> str:
    return f'''import os
import subprocess
from pathlib import Path

_TOOL = os.environ["REPOPROOF_TOOL_BIN"]
_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_help_reachable():
    result = subprocess.run([_TOOL, "--help"], capture_output=True, text=True)
    assert result.returncode == 0 and "usage" in result.stdout.lower()


def test_missing_input_is_user_error(tmp_path):
    result = subprocess.run(
        [_TOOL, str(tmp_path / "missing"), "--out-dir", str(tmp_path / "out")],
        capture_output=True, text=True,
    )
    assert result.returncode == 1 and result.stderr and not result.stdout


def test_existing_output_is_not_overwritten(tmp_path):
    output = tmp_path / "existing"; output.mkdir()
    marker = output / "marker"; marker.write_text("keep")
    result = subprocess.run(
        [_TOOL, str(_FIXTURES / {first_example_id!r} / "input"),
         "--out-dir", str(output)], capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert marker.read_text() == "keep"
'''


def _embedded_control(
    examples: list[WorkspaceGoldenExampleV1],
    source_root: Path,
) -> str:
    mapping: dict[str, list[dict[str, object]]] = {}
    for example in examples:
        expected = source_root / example.expected_dir
        entries: list[dict[str, object]] = []
        for path in sorted(expected.rglob("*")):
            if path.is_dir():
                continue
            info = path.lstat()
            entries.append(
                {
                    "path": path.relative_to(expected).as_posix(),
                    "mode": info.st_mode & 0o777,
                    "payload": base64.b64encode(path.read_bytes()).decode("ascii"),
                }
            )
        key = identify_input_path(source_root / example.input_path).sha256
        if key in mapping:
            raise CompileError("workspace examples must have distinct input identities")
        mapping[key] = entries
    return f'''"""Harness control; never delivered."""
import base64
import hashlib
import stat
from pathlib import Path

class UserInputError(ValueError):
    pass

_MAPPING = {mapping!r}

def _identity(path: Path) -> str:
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256(b"REPOPROOF-WORKSPACE-TREE-V1\\0")
    for item in sorted(path.rglob("*"), key=lambda value: value.relative_to(path).as_posix()):
        info = item.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        payload = item.read_bytes()
        relative = item.relative_to(path).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big")); digest.update(relative)
        digest.update(stat.S_IMODE(info.st_mode).to_bytes(4, "big"))
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(hashlib.sha256(payload).digest())
    return digest.hexdigest()

def build_workspace(input_path: Path, output_dir: Path) -> None:
    rows = _MAPPING.get(_identity(input_path))
    if rows is None:
        raise UserInputError("unexpected input")
    for row in rows:
        target = output_dir / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(row["payload"]))
        target.chmod(row["mode"])
'''


_EMPTY_CONTROL = '''from pathlib import Path
class UserInputError(ValueError):
    pass
def build_workspace(input_path: Path, output_dir: Path) -> None:
    return None
'''


def _assert_function(source: str, name: str) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise CompileError(f"{name} is not valid Python") from exc
    if not any(
        isinstance(node, ast.FunctionDef)
        and node.name == name
        and len(node.args.args) == 2
        for node in tree.body
    ):
        raise CompileError(f"missing {name}(input_path, output_dir)")


def assemble_workspace_tool_task(
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
    reference_impl: str,
    semantic_verifier_source: str,
    fixture_builder_source: str,
    fixture_blueprints: list[dict],
    reference_lock: str,
    intent_contract: dict,
    output_schema: str,
) -> dict:
    """Freeze a v4 workspace task without running a model."""

    root = Path(root)
    if tool.schema_version != 4 or tool.delivery_profile_id != "workspace_bundle_v1":
        raise CompileError("workspace assembler requires ToolSpec v4")
    if tool.workspace_contract is None:
        raise CompileError("workspace contract is required")
    workspace_contract = tool.workspace_contract
    parsed = [WorkspaceGoldenExampleV1.model_validate(item) for item in examples]
    if len(parsed) < 3:
        raise CompileError("at least three workspace examples are required")
    _assert_function(reference_impl, "build_workspace")
    _assert_function(semantic_verifier_source, "verify")
    _assert_function(fixture_builder_source, "build")
    parsed_blueprints = [
        FixtureBlueprintV1.model_validate(item) for item in fixture_blueprints
    ]
    if not 3 <= len(parsed_blueprints) <= 4:
        raise CompileError("workspace fixture builder requires 3-4 blueprints")
    expected_input_kind = tool.interface.input.kind
    if any(item.input_kind != expected_input_kind for item in parsed_blueprints):
        raise CompileError("workspace fixture blueprint input kind mismatch")
    for example in parsed:
        input_identity = identify_input_path(example_src_dir / example.input_path)
        expected_manifest = build_artifact_manifest(
            example_src_dir / example.expected_dir,
            workspace_contract.limits,
        )
        binding = workspace_truth_binding_sha256(
            input_identity.sha256, expected_manifest.tree_sha256
        )
        if binding != example.truth_binding_sha256:
            raise CompileError(f"workspace example binding drift: {example.example_id}")
    public = parsed[:-max(1, len(parsed) // 4)]
    held = parsed[-max(1, len(parsed) // 4):]
    if len(public) < 2:
        raise CompileError("workspace anti-hardcode layer requires two public examples")

    projection_errors = validate_frozen_intent_projection(
        intent_contract=intent_contract,
        compiled_statement=goal.strip(),
        input_contract=tool.interface.input.model_dump(mode="json"),
        output_contract=tool.interface.output.model_dump(mode="json"),
        output_schema=output_schema,
    )
    if projection_errors:
        raise CompileError(f"CURRENT_PRODUCT_INTENT_INVALID:{projection_errors[0]}")

    task_id = next_tool_task_id(root, tool.name)
    slug, version_text = task_id.removeprefix("tool-").rsplit("-v", 1)
    version = int(version_text)
    skeleton_rel = (
        f"fixtures/tool_skeleton_{slug}"
        if version == 1
        else f"fixtures/tool_skeleton_{slug}-v{version}"
    )
    package = tool.name.replace("-", "_")
    semantic_rel = f"oracle/{task_id}/semantic_verifier.py"
    semantic_id = f"{tool.name}-workspace-semantic-v1"
    semantic_spec = {
        "protocol": "repoproof-workspace-semantic-verifier-v2",
        "verifier_id": semantic_id,
        "source_file": semantic_rel,
        "source_sha256": hashlib.sha256(
            semantic_verifier_source.encode("utf-8")
        ).hexdigest(),
        "required_for_operational_active": True,
    }

    contract_doc = {
        "task_id": task_id,
        "source_repo": {
            "url": repo_url,
            "revision": "guided",
            "resolved_commit": resolved_commit,
            "license": license_id,
            "distribution": distribution,
            "import_module": import_module,
        },
        "target_project": {
            "kind": "local_tool",
            "path": skeleton_rel,
            "package": package,
            "entry_point": tool.name,
        },
        "requirement_spec_file": f"{task_id}.requirements.yaml",
        "task_family": "LOCAL-TOOL",
        "adoption_shape": "WORKSPACE_ONBOARDING",
        "tool": tool.model_dump(mode="json"),
        "capability": {
            "statement": goal.strip(),
            "output_schema": output_schema,
            "intent_contract": intent_contract,
        },
        "environment": {
            "os": "linux",
            "arch": "arm64",
            "python": "3.12",
            "cpu_only": True,
            "network_install": True,
            "network_test": False,
        },
        "constraints": {
            "forbidden": [
                "gpu", "privileged_container", "oracle_write",
                "model_download", "network_at_test_time",
            ],
            "editable_zones": ["tool"],
            "forbidden_install_extras": [],
        },
        "budgets": {
            "max_agent_steps": 20,
            "max_wall_time_minutes": 30,
            "max_command_minutes": 5,
            "max_semantic_recoveries": 3,
            "max_same_action": 2,
            "max_patch_files": 16,
            "max_patch_lines": 1200,
            "max_input_tokens_total": 400000,
            "max_output_tokens_total": 40000,
            "monetary_soft_cap_usd": 5.0,
        },
        "acceptance": {
            "capability_command": ["pytest", "-q", "/oracle/test_capability.py"],
            "regression_command": [
                "pytest", "-q", "public_tests/test_interface_contract.py"
            ],
            "probe_script": "direct_tool_probe.py",
            "semantic_verifier": semantic_spec,
        },
    }

    public_nodes = [f"test_capability::test_example_{i}" for i in range(1, len(public) + 1)]
    held_nodes = [f"test_capability::test_held_example_{i}" for i in range(1, len(held) + 1)]
    requirements = [
        {
            "id": "workspace-examples",
            "owner": "ADAPTER",
            "severity": "HARD",
            "source_field": "capability.statement",
            "public_text": "Generate the user-confirmed workspace for every admitted input.",
            "examples": [item.example_id for item in public],
            "oracle_nodes": [*public_nodes, *held_nodes],
        },
        {
            "id": "workspace-interface",
            "owner": "HOST_INPUT_GUARD",
            "severity": "HARD",
            "source_field": "tool.interface",
            "public_text": "Accept one local path and atomically create only a new --out-dir.",
            "examples": [tool.interface.usage],
            "oracle_nodes": [
                "test_interface_contract::test_help_reachable",
                "test_interface_contract::test_missing_input_is_user_error",
                "test_interface_contract::test_existing_output_is_not_overwritten",
            ],
        },
        {
            "id": "workspace-structure",
            "owner": "HARNESS",
            "severity": "HARD",
            "source_field": "tool.workspace_contract",
            "public_text": "Every output must satisfy the confirmed directory structure and format contract.",
            "examples": [],
            "oracle_nodes": [],
            "verified_by": "workspace-structure-validator-v1",
        },
    ]
    for commitment in intent_contract.get("commitments") or []:
        requirements.append(
            {
                "id": f"intent-{commitment['commitment_id']}",
                "owner": "ADAPTER",
                "severity": "HARD",
                "source_field": "capability.intent_contract.commitments",
                "public_text": commitment["public_text"],
                "examples": [],
                "oracle_nodes": [],
                "verified_by": f"semantic-verifier:{semantic_id}",
            }
        )
    requirement_doc = {
        "task_id": task_id,
        "controls": {
            "positive": f"controls/{task_id}/positive",
            "negatives": [
                {
                    "path": f"controls/{task_id}/negative_empty",
                    "label": "NC_empty",
                    "must_fail_nodes": ["test_example"],
                },
                {
                    "path": f"controls/{task_id}/negative_hardcode",
                    "label": "NC_hardcode",
                    "must_fail_nodes": ["test_held_example"],
                },
            ],
        },
        "requirements": requirements,
    }

    contract_json = workspace_contract.model_dump(mode="json")
    portable_source = Path(str(portable_workspace_runtime.__file__)).read_text(
        encoding="utf-8"
    )
    manifest = {
        "manifest_version": 1,
        "name": tool.name,
        "version": "1.0.0",
        "summary": tool.summary,
        "source": {
            "url": repo_url,
            "resolved_commit": resolved_commit,
            "license": license_id,
            "distribution": distribution,
        },
        "contract_schema_version": 4,
        "delivery_profile_id": "workspace_bundle_v1",
        "workspace_contract": contract_json,
        "interface": tool.interface.model_dump(mode="json"),
        "capability": {"output_schema": output_schema},
        "runtime": {"python": "3.12", "cpu_only": True, "offline": True},
        "verification": None,
    }
    files: dict[str, str] = {
        f"contracts/{task_id}.yaml": yaml.safe_dump(
            contract_doc, allow_unicode=True, sort_keys=False
        ),
        f"contracts/{task_id}.requirements.yaml": yaml.safe_dump(
            requirement_doc, allow_unicode=True, sort_keys=False
        ),
        f"{skeleton_rel}/tool.json": json.dumps(
            manifest, ensure_ascii=False, indent=2
        ) + "\n",
        f"{skeleton_rel}/README.md": _README.format(
            name=tool.name,
            summary=tool.summary,
            repo_url=repo_url,
            commit=resolved_commit,
            license_id=license_id,
        ),
        f"{skeleton_rel}/bin/{tool.name}": _BIN.format(package=package),
        f"{skeleton_rel}/build.sh": _BUILD,
        f"{skeleton_rel}/pyproject.toml": _PYPROJECT.format(
            package=package, summary=tool.summary
        ),
        f"{skeleton_rel}/requirements.lock.txt": reference_lock,
        f"{skeleton_rel}/.gitignore": (
            ".venv/\n*venv*/\n__pycache__/\n*.pyc\n*.egg-info/\nevidence/\n"
        ),
        f"{skeleton_rel}/vendor/wheels/.gitkeep": "",
        f"{skeleton_rel}/src/{package}/__init__.py": _INIT,
        f"{skeleton_rel}/src/{package}/__main__.py": _MAIN_MOD,
        f"{skeleton_rel}/src/{package}/main.py": _MAIN.format(
            name=tool.name, summary=tool.summary
        ),
        f"{skeleton_rel}/src/{package}/impl.py": _IMPL.format(
            distribution=distribution
        ),
        f"{skeleton_rel}/src/{package}/portable_workspace_runtime.py": portable_source,
        f"{skeleton_rel}/src/{package}/workspace_contract.json": json.dumps(
            contract_json, ensure_ascii=False, indent=2
        ) + "\n",
        f"{skeleton_rel}/public_tests/test_public_contract.py": _test_source(
            public,
            held=False,
            smoke_command=workspace_contract.smoke_command,
        ),
        f"{skeleton_rel}/public_tests/test_interface_contract.py": (
            _interface_test_source(public[0].example_id)
        ),
        f"oracle/{task_id}/test_capability.py": "",
        f"oracle/{task_id}/semantic_verifier.py": semantic_verifier_source,
        f"oracle/{task_id}/fixture_builder.py": fixture_builder_source,
        f"oracle/{task_id}/fixture_blueprints.json": json.dumps(
            {
                "schema_version": 1,
                "blueprints": [
                    item.model_dump(mode="json") for item in parsed_blueprints
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        f"controls/{task_id}/positive/impl.py": _embedded_control(parsed, example_src_dir),
        f"controls/{task_id}/negative_empty/impl.py": _EMPTY_CONTROL,
        f"controls/{task_id}/negative_hardcode/impl.py": _embedded_control(
            public, example_src_dir
        ),
        f"controls/{task_id}/negative_reimpl/impl.py": _embedded_control(
            parsed, example_src_dir
        ),
        f"controls/{task_id}/reference/impl.py": reference_impl,
        f"controls/{task_id}/reference/requirements.lock.txt": reference_lock,
    }
    # Generate one oracle module with public and explicitly named held-out tests.
    oracle_source = _test_source(
        public,
        held=False,
        smoke_command=workspace_contract.smoke_command,
    )
    held_source = _test_source(held, held=True)
    held_functions = held_source[held_source.index("def test_held_example_"):]
    files[f"oracle/{task_id}/test_capability.py"] = oracle_source + "\n" + held_functions
    example_docs = {
        "examples": [item.model_dump(mode="json") for item in parsed]
    }
    files[f"{skeleton_rel}/public_examples/truth_table.json"] = json.dumps(
        {"examples": [item.model_dump(mode="json") for item in public]},
        ensure_ascii=False,
        indent=2,
    )
    files[f"oracle/{task_id}/fixtures/public_documents.json"] = json.dumps(
        {"examples": [item.model_dump(mode="json") for item in public]}
    )
    files[f"oracle/{task_id}/fixtures/held_out_documents.json"] = json.dumps(
        {"examples": [item.model_dump(mode="json") for item in held]}
    )
    del example_docs

    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def copy_example(example: WorkspaceGoldenExampleV1, destination_root: Path) -> None:
        snapshot_admitted_path(
            example_src_dir / example.input_path,
            destination_root / example.example_id / "input",
        )
        snapshot_admitted_path(
            example_src_dir / example.expected_dir,
            destination_root / example.example_id / "expected",
            limits=workspace_contract.limits,
        )

    for example in public:
        copy_example(example, root / skeleton_rel / "public_tests" / "fixtures")
        snapshot_admitted_path(
            example_src_dir / example.input_path,
            root / skeleton_rel / "public_examples" / example.example_id / "input",
        )
    for example in parsed:
        copy_example(example, root / "oracle" / task_id / "fixtures")

    for executable in (
        root / skeleton_rel / "bin" / tool.name,
        root / skeleton_rel / "build.sh",
    ):
        executable.chmod(0o755)
    contract_path = root / "contracts" / f"{task_id}.yaml"
    digest = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    (root / "contracts" / f"{task_id}.yaml.sha256").write_text(
        f"{digest}  {contract_path.name}\n", encoding="utf-8"
    )
    return {
        "task_id": task_id,
        "files": sorted(files),
        "public": len(public),
        "held": len(held),
        "delivery_profile_id": "workspace_bundle_v1",
        "next": (
            ".venv/bin/python -m repoproof.cli freeze-task "
            f"--contract contracts/{task_id}.yaml --full"
        ),
    }
