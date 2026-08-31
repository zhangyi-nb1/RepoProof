"""Read-only, Core-owned readiness for editable Product draft bundles.

The result in this module is the single Product boundary for deciding whether
an *unfrozen* draft is current, may still be edited, is ready for an explicit
human confirmation, or may enter the freeze gate.  It deliberately evaluates
only versioned contracts and Python protocols.  Repository names, file-format
labels, filename extensions, and domain vocabulary never select a policy.

Historical frozen contracts keep their existing loaders.  Historical v1/v2
drafts, however, are not upgraded in place: they remain readable evidence and
must be recreated through the current intake flow.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from repoproof.adoption.assembly.example_compiler import (
    CONTAINS,
    UPSTREAM_CONFIRMED,
    Example,
    truth_binding_sha256,
)
from repoproof.adoption.assembly.output_contract import (
    is_capability_output_invocation,
    validate_output_text,
)
from repoproof.adoption.assembly.workspace_tool_assembler import (
    WorkspaceGoldenExampleV1,
    workspace_truth_binding_sha256,
)
from repoproof.adoption.delivery.product_profile import (
    ProductProfileError,
    product_delivery_profile,
)
from repoproof.adoption.intake.intent_contract import (
    IntentContractDraftV1,
    validate_intent_contract,
)
from repoproof.adoption.intake.upstream_pin import derive_reference_lock
from repoproof.adoption.intake.workspace_fixtures import FixtureBlueprintV1
from repoproof.domain.models import ToolOutputContract, ToolSpec
from repoproof.execution.workspace_bundle import (
    WorkspaceBundleError,
    build_artifact_manifest,
    identify_input_path,
)

DRAFT_READINESS_SCHEMA_VERSION = 1
CURRENT_TOOL_SCHEMA_VERSION = 3
CURRENT_WORKSPACE_TOOL_SCHEMA_VERSION = 4
CURRENT_DELIVERY_PROFILE_SCHEMA_VERSION = 1
MINIMUM_EXAMPLES = 3

DRAFT_YAML = "draft.yaml"
EXAMPLES_YAML = "examples.yaml"
WORKSPACE_EXAMPLES_YAML = "workspace_examples.yaml"
REFERENCE_PY = "reference_impl.py"
REFERENCE_LOCK = "reference.lock.txt"
SEMANTIC_VERIFIER_PY = "semantic_verifier.py"
FIXTURE_BUILDER_PY = "fixture_builder.py"
FIXTURE_BLUEPRINTS_JSON = "fixture_blueprints.json"

_EXACT_PIN_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9][A-Za-z0-9._+!-]*"
)

ReadinessStatus = Literal[
    "INCOMPATIBLE",
    "INCOMPLETE",
    "READY_TO_CONFIRM",
    "READY_TO_FREEZE",
]
DependencyLockSource = Literal["draft", "derived", "missing", "invalid"]
CommitmentCoverage = Literal[
    "COMPLETE",
    "RUNTIME_PENDING",
    "INCOMPLETE",
    "UNAVAILABLE",
]


class DraftReadinessPublicSummaryV1(BaseModel):
    """Safe primary-flow facts; never contains oracle/reference source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_schema_version: int | None = None
    semantic_verifier_ready: bool = False
    semantic_commitment_count: int = Field(default=0, ge=0)
    verifier_declared_commitment_count: int = Field(default=0, ge=0)
    commitment_coverage: CommitmentCoverage = "UNAVAILABLE"
    dependency_lock_ready: bool = False
    dependency_lock_source: DependencyLockSource = "missing"
    example_count: int = Field(default=0, ge=0)
    minimum_examples: Literal[3] = 3


class DraftReadinessV1(BaseModel):
    """Stable readiness protocol consumed by CLI and Product Studio."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    status: ReadinessStatus
    compatible: bool
    current: bool
    ready: bool
    ready_to_confirm: bool
    reason_codes: list[str] = Field(default_factory=list)
    public_summary: DraftReadinessPublicSummaryV1
    recommended_action: str


@dataclass(frozen=True)
class _Issue:
    code: str
    problem: str
    confirmation_only: bool = False


@dataclass(frozen=True)
class _Evaluation:
    readiness: DraftReadinessV1
    problems: tuple[str, ...]
    dependency_lock_text: str


def _append(
    issues: list[_Issue],
    code: str,
    problem: str,
    *,
    confirmation_only: bool = False,
) -> None:
    issues.append(_Issue(code, problem, confirmation_only))


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _nonempty(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _imports_module(tree: ast.AST, module: str) -> bool:
    prefix = f"{module}."
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                alias.name == module or alias.name.startswith(prefix)
                for alias in node.names
            ):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == module or node.module.startswith(prefix):
                return True
    return False


def _sync_function(
    tree: ast.Module,
    name: str,
    *,
    positional_arguments: int,
) -> ast.FunctionDef | None:
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != name:
            continue
        positional = [*node.args.posonlyargs, *node.args.args]
        if (
            len(positional) == positional_arguments
            and node.args.vararg is None
            and node.args.kwarg is None
            and not node.args.kwonlyargs
        ):
            return node
    return None


def _scoped_function_nodes(function: ast.FunctionDef) -> tuple[ast.AST, ...]:
    """Walk one function body without attributing nested callables to it."""

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.nodes: list[ast.AST] = []

        def generic_visit(self, node: ast.AST) -> None:
            self.nodes.append(node)
            super().generic_visit(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            return

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            return

        def visit_Lambda(self, node: ast.Lambda) -> None:
            return

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            return

    visitor = _Visitor()
    for statement in function.body:
        visitor.visit(statement)
    return tuple(visitor.nodes)


def _has_value_return(function: ast.FunctionDef) -> bool:
    return any(
        isinstance(node, ast.Return)
        and node.value is not None
        and not (
            isinstance(node.value, ast.Constant)
            and node.value.value is None
        )
        for node in _scoped_function_nodes(function)
    )


def _dict_protocol_value(node: ast.AST | None, key_name: str) -> ast.AST | None:
    if not isinstance(node, ast.Dict):
        return None
    for key, value in zip(node.keys, node.values, strict=True):
        if (
            isinstance(key, ast.Constant)
            and key.value == key_name
        ):
            return value
    return None


def _helper_ok_parameter(
    tree: ast.Module,
    helper_name: str,
) -> str | None:
    """Resolve a tiny result helper such as ``_result(ok, reasons, ids)``.

    This intentionally recognises only a provable protocol projection. Unknown
    source styles remain runtime-pending; the gate must not reject a dynamic
    verifier merely because static analysis cannot understand it.
    """

    helper = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == helper_name
        ),
        None,
    )
    if helper is None:
        return None
    positional = [*helper.args.posonlyargs, *helper.args.args]
    parameters = {argument.arg for argument in positional}
    projected: set[str] = set()
    returns = [
        node
        for node in _scoped_function_nodes(helper)
        if isinstance(node, ast.Return) and node.value is not None
    ]
    if not returns:
        return None
    for returned in returns:
        ok_value = _dict_protocol_value(returned.value, "ok")
        if not isinstance(ok_value, ast.Name) or ok_value.id not in parameters:
            return None
        projected.add(ok_value.id)
    return next(iter(projected)) if len(projected) == 1 else None


def _call_argument_for_parameter(
    call: ast.Call,
    function: ast.FunctionDef,
    parameter_name: str,
) -> ast.AST | None:
    positional = [*function.args.posonlyargs, *function.args.args]
    for index, parameter in enumerate(positional):
        if parameter.arg == parameter_name and index < len(call.args):
            return call.args[index]
    for keyword in call.keywords:
        if keyword.arg == parameter_name:
            return keyword.value
    return None


def _returned_protocol_ok(
    tree: ast.Module,
    returned: ast.AST,
) -> ast.AST | None:
    direct = _dict_protocol_value(returned, "ok")
    if direct is not None:
        return direct
    if not isinstance(returned, ast.Call) or not isinstance(returned.func, ast.Name):
        return None
    helper_name = returned.func.id
    ok_parameter = _helper_ok_parameter(tree, helper_name)
    if ok_parameter is None:
        return None
    helper = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == helper_name
    )
    return _call_argument_for_parameter(returned, helper, ok_parameter)


def _verifier_is_provably_reject_only(
    tree: ast.Module,
    function: ast.FunctionDef,
) -> bool:
    """Reject only when every observable result hard-codes protocol ``ok=False``."""

    returns = [
        node.value
        for node in _scoped_function_nodes(function)
        if isinstance(node, ast.Return) and node.value is not None
    ]
    if not returns:
        return False
    for returned in returns:
        ok_value = _returned_protocol_ok(tree, returned)
        if not (
            isinstance(ok_value, ast.Constant)
            and ok_value.value is False
        ):
            return False
    return True


def _declared_commitment_ids(
    function: ast.FunctionDef,
    required_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Read only exact public IDs from the verifier result protocol.

    The task-specific meaning of an ID is never interpreted.  A declaration
    counts only when it is present in the value returned for the versioned
    ``checked_commitment_ids`` protocol field.
    """

    required = set(required_ids)
    observed: set[str] = set()
    assignments: dict[str, ast.AST] = {}
    scoped_nodes = _scoped_function_nodes(function)
    for node in scoped_nodes:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if value is None:
                continue
            for target in targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = value

    def collect(value: ast.AST) -> None:
        if isinstance(value, ast.Name) and value.id in assignments:
            value = assignments[value.id]
        if not isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            return
        for item in value.elts:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                if item.value in required:
                    observed.add(item.value)

    for node in scoped_nodes:
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values, strict=True):
            if (
                isinstance(key, ast.Constant)
                and key.value == "checked_commitment_ids"
            ):
                collect(value)
    return tuple(item for item in required_ids if item in observed)


def _parse_python(
    source: str,
    *,
    code: str,
    problem: str,
    issues: list[_Issue],
) -> ast.Module | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        _append(issues, code, problem)
        return None


def _read_text(path: Path) -> str | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _safe_example_file(root: Path, relative: str) -> Path | None:
    if root.is_symlink() or not root.is_dir():
        return None
    candidate = Path(relative)
    if candidate.is_absolute() or any(
        part in {"", ".", ".."} for part in candidate.parts
    ):
        return None
    try:
        resolved_root = root.resolve()
        resolved = (root / candidate).resolve()
        resolved.relative_to(resolved_root)
    except (OSError, ValueError):
        return None
    if (root / candidate).is_symlink() or not resolved.is_file():
        return None
    return resolved


def _read_examples(
    draft_dir: Path,
    issues: list[_Issue],
    *,
    output_contract: ToolOutputContract | None,
) -> list[Example]:
    path = draft_dir / EXAMPLES_YAML
    source = _read_text(path)
    if source is None:
        _append(issues, "EXAMPLES_DOCUMENT_MISSING", f"D:{EXAMPLES_YAML} 缺失")
        return []
    try:
        document = yaml.safe_load(source) or {}
    except yaml.YAMLError:
        _append(
            issues,
            "EXAMPLES_DOCUMENT_INVALID",
            f"D:{EXAMPLES_YAML} 不是合法 YAML",
        )
        return []
    if not isinstance(document, dict) or not isinstance(document.get("examples", []), list):
        _append(
            issues,
            "EXAMPLES_DOCUMENT_INVALID",
            f"D:{EXAMPLES_YAML}.examples 必须为列表",
        )
        return []
    raw_examples = document.get("examples") or []
    examples: list[Example] = []
    for index, raw in enumerate(raw_examples, start=1):
        try:
            examples.append(Example.model_validate(raw))
        except ValidationError as exc:
            _append(
                issues,
                "EXAMPLE_INVALID",
                f"D:example {index} 非法:{exc}",
            )
    if len(examples) < MINIMUM_EXAMPLES:
        _append(
            issues,
            "EXAMPLES_INSUFFICIENT",
            (
                f"D:examples 仅 {len(examples)} 组(需 >={MINIMUM_EXAMPLES},"
                "含文件样例;尾部自动切 held-out)"
            ),
        )

    examples_root = draft_dir / "examples"
    file_example_seen = False
    exact_structured_golden = False
    for index, example in enumerate(examples, start=1):
        capability_invocation = is_capability_output_invocation(example.input)
        input_bytes: bytes | None = None
        expected_bytes: bytes | None = None
        if example.input_file is not None:
            file_example_seen = True
            input_path = _safe_example_file(examples_root, example.input_file)
            if input_path is None:
                _append(
                    issues,
                    "EXAMPLE_INPUT_FILE_INVALID",
                    f"D:example {index} input_file 缺失、不安全或不是普通文件",
                )
            else:
                try:
                    input_bytes = input_path.read_bytes()
                except OSError:
                    _append(
                        issues,
                        "EXAMPLE_INPUT_FILE_UNREADABLE",
                        f"D:example {index} input_file 无法读取",
                    )

        golden: str | None = None
        if example.expected_file is not None:
            expected_path = _safe_example_file(
                examples_root,
                example.expected_file,
            )
            if expected_path is None:
                _append(
                    issues,
                    "EXAMPLE_EXPECTED_FILE_INVALID",
                    f"D:example {index} expected_file 缺失、不安全或不是普通文件",
                )
            else:
                try:
                    expected_bytes = expected_path.read_bytes()
                    golden = expected_bytes.decode("utf-8")
                except (OSError, UnicodeError):
                    _append(
                        issues,
                        "EXAMPLE_EXPECTED_FILE_UNREADABLE",
                        f"D:example {index} expected_file 不是可读 UTF-8 文件",
                    )
                else:
                    exact_structured_golden = (
                        exact_structured_golden or capability_invocation
                    )
        elif (
            example.expected is not None
            and not example.expected.startswith(CONTAINS)
        ):
            golden = example.expected
            exact_structured_golden = (
                exact_structured_golden or capability_invocation
            )

        if example.truth_provenance == UPSTREAM_CONFIRMED:
            if (
                example.input_file is None
                or example.expected_file is None
                or input_bytes is None
                or expected_bytes is None
                or truth_binding_sha256(input_bytes, expected_bytes)
                != example.truth_binding_sha256
            ):
                _append(
                    issues,
                    "EXAMPLE_TRUTH_BINDING_INVALID",
                    f"D:example {index} 上游派生输入/输出绑定缺失或已漂移",
                )

        if (
            golden is not None
            and output_contract is not None
            and capability_invocation
        ):
            for detail in validate_output_text(golden, output_contract):
                _append(
                    issues,
                    "GOLDEN_OUTPUT_INVALID",
                    f"D:example {index} golden output 非法:{detail}",
                )

    if examples and not file_example_seen:
        _append(
            issues,
            "FILE_EXAMPLE_MISSING",
            "D:LOCAL-TOOL 任务至少需要一个文件输入样例(确定性锚)",
        )
    if (
        output_contract is not None
        and output_contract.root_type != "text"
        and not exact_structured_golden
    ):
        _append(
            issues,
            "EXACT_STRUCTURED_GOLDEN_MISSING",
            "D:结构化输出至少需要一组完整精确真值",
        )
    return examples


def _read_workspace_examples(
    draft_dir: Path,
    issues: list[_Issue],
    tool: ToolSpec | None,
) -> list[WorkspaceGoldenExampleV1]:
    path = draft_dir / WORKSPACE_EXAMPLES_YAML
    source = _read_text(path)
    if source is None:
        _append(
            issues,
            "WORKSPACE_EXAMPLES_DOCUMENT_MISSING",
            f"D:{WORKSPACE_EXAMPLES_YAML} 缺失",
        )
        return []
    try:
        document = yaml.safe_load(source) or {}
    except yaml.YAMLError:
        document = None
    if not isinstance(document, dict) or not isinstance(document.get("examples"), list):
        _append(
            issues,
            "WORKSPACE_EXAMPLES_DOCUMENT_INVALID",
            f"D:{WORKSPACE_EXAMPLES_YAML}.examples 必须为列表",
        )
        return []
    examples: list[WorkspaceGoldenExampleV1] = []
    for index, raw in enumerate(document["examples"], start=1):
        try:
            example = WorkspaceGoldenExampleV1.model_validate(raw)
        except ValidationError as exc:
            _append(
                issues,
                "WORKSPACE_EXAMPLE_INVALID",
                f"D:workspace example {index} 非法:{exc}",
            )
            continue
        examples.append(example)
        if tool is None or tool.workspace_contract is None:
            continue
        try:
            input_identity = identify_input_path(
                draft_dir / "examples" / example.input_path
            )
            expected = build_artifact_manifest(
                draft_dir / "examples" / example.expected_dir,
                tool.workspace_contract.limits,
            )
        except WorkspaceBundleError as exc:
            _append(
                issues,
                "WORKSPACE_EXAMPLE_PATH_INVALID",
                f"D:workspace example {index} 不安全或不可读取:{exc.code}",
            )
            continue
        binding = workspace_truth_binding_sha256(
            input_identity.sha256,
            expected.tree_sha256,
        )
        if binding != example.truth_binding_sha256:
            _append(
                issues,
                "WORKSPACE_EXAMPLE_TRUTH_BINDING_INVALID",
                f"D:workspace example {index} 输入/期望目录绑定已漂移",
            )
    if len(examples) < MINIMUM_EXAMPLES:
        _append(
            issues,
            "EXAMPLES_INSUFFICIENT",
            f"D:workspace examples 仅 {len(examples)} 组(需 >={MINIMUM_EXAMPLES})",
        )
    return examples


def _check_workspace_fixture_assets(
    draft_dir: Path,
    issues: list[_Issue],
    tool: ToolSpec | None,
) -> None:
    """Require one frozen builder protocol and 3-4 typed scenario blueprints."""

    builder_source = _read_text(draft_dir / FIXTURE_BUILDER_PY)
    if builder_source is None:
        _append(
            issues,
            "FIXTURE_BUILDER_MISSING",
            f"D:{FIXTURE_BUILDER_PY} 缺失",
        )
    else:
        builder_tree = _parse_python(
            builder_source,
            code="FIXTURE_BUILDER_INVALID_PYTHON",
            problem="D:fixture builder 不是合法 Python",
            issues=issues,
        )
        if builder_tree is not None and _sync_function(
            builder_tree,
            "build",
            positional_arguments=2,
        ) is None:
            _append(
                issues,
                "FIXTURE_BUILDER_PROTOCOL_INVALID",
                "D:fixture builder 必须定义同步 build(blueprint, output_path)",
            )

    source = _read_text(draft_dir / FIXTURE_BLUEPRINTS_JSON)
    if source is None:
        _append(
            issues,
            "FIXTURE_BLUEPRINTS_MISSING",
            f"D:{FIXTURE_BLUEPRINTS_JSON} 缺失",
        )
        return
    try:
        document = json.loads(source)
        rows = document.get("blueprints") if isinstance(document, dict) else None
        if not isinstance(rows, list) or not 3 <= len(rows) <= 4:
            raise ValueError("fixture blueprints must contain 3-4 rows")
        blueprints = [FixtureBlueprintV1.model_validate(item) for item in rows]
    except (ValueError, ValidationError, json.JSONDecodeError):
        _append(
            issues,
            "FIXTURE_BLUEPRINTS_INVALID",
            "D:fixture blueprints 必须是 3-4 个安全、类型化的自然场景",
        )
        return
    if tool is not None and any(
        item.input_kind != tool.interface.input.kind for item in blueprints
    ):
        _append(
            issues,
            "FIXTURE_BLUEPRINT_INPUT_KIND_MISMATCH",
            "D:fixture blueprint 的 file/directory 类型与工具输入合同不一致",
        )


def _resolve_dependency_lock(
    draft: dict,
    draft_dir: Path,
    project_root: Path | None,
    issues: list[_Issue],
) -> tuple[DependencyLockSource, str]:
    path = draft_dir / REFERENCE_LOCK
    lock_text = _read_text(path)
    source: DependencyLockSource = "draft"
    if lock_text is None or not lock_text.strip():
        lock_text = ""
        source = "missing"
        if project_root is not None:
            source_repo = _mapping(draft.get("source_repo"))
            try:
                lock_text = derive_reference_lock(
                    Path(project_root),
                    distribution=str(source_repo.get("distribution") or ""),
                    resolved_commit=str(source_repo.get("resolved_commit") or ""),
                    import_module=str(source_repo.get("import_module") or ""),
                    requested_revision=str(source_repo.get("revision") or ""),
                )
            except OSError:
                lock_text = ""
            if lock_text.strip():
                source = "derived"
    pins = [
        line.strip()
        for line in lock_text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not pins:
        _append(
            issues,
            "DEPENDENCY_LOCK_MISSING",
            (
                f"D:{REFERENCE_LOCK} 缺失且无法从固定上游声明版本派生"
            ),
        )
        return "missing", ""
    if any(_EXACT_PIN_RE.fullmatch(pin) is None for pin in pins):
        _append(
            issues,
            "DEPENDENCY_LOCK_INVALID",
            f"D:{REFERENCE_LOCK} 必须只含 包名==精确版本",
        )
        return "invalid", lock_text
    return source, lock_text


def _compatibility(draft: dict) -> tuple[bool, bool, list[_Issue]]:
    issues: list[_Issue] = []
    tool = _mapping(draft.get("tool"))
    raw_version = tool.get("schema_version")
    delivery = _mapping(draft.get("_delivery_profile"))
    expected_version = (
        CURRENT_WORKSPACE_TOOL_SCHEMA_VERSION
        if delivery.get("profile_id") == "workspace_bundle_v1"
        else CURRENT_TOOL_SCHEMA_VERSION
    )
    current = raw_version == expected_version
    if not current:
        _append(
            issues,
            "TOOL_SPEC_VERSION_NOT_CURRENT",
            (
                f"D:tool.schema_version 必须为 {expected_version} —— "
                "旧版本只保留历史语义，不得原地升级"
            ),
        )

    intent_document = draft.get("_intent_contract")
    intent_compatible = True
    if intent_document is None:
        intent_compatible = False
        _append(
            issues,
            "INTENT_CONTRACT_MISSING",
            "D:_intent_contract 缺失 —— 旧/过渡草稿不得原地补成当前任务",
        )
    else:
        try:
            IntentContractDraftV1.model_validate(intent_document)
        except ValidationError:
            intent_compatible = False
            _append(
                issues,
                "INTENT_CONTRACT_INVALID",
                "D:_intent_contract 不是当前 v1 结构",
            )

    delivery_compatible = delivery.get("schema_version") == (
        CURRENT_DELIVERY_PROFILE_SCHEMA_VERSION
    )
    if not delivery_compatible:
        _append(
            issues,
            "DELIVERY_PROFILE_VERSION_NOT_CURRENT",
            (
                "D:_delivery_profile.schema_version 必须为 "
                f"{CURRENT_DELIVERY_PROFILE_SCHEMA_VERSION}"
            ),
        )
    return current and intent_compatible and delivery_compatible, current, issues


def _evaluate(
    draft: dict,
    draft_dir: Path,
    *,
    project_root: Path | None,
) -> _Evaluation:
    draft_dir = Path(draft_dir)
    compatible, current, issues = _compatibility(draft)

    delivery = _mapping(draft.get("_delivery_profile"))
    profile = None
    if delivery.get("schema_version") == CURRENT_DELIVERY_PROFILE_SCHEMA_VERSION:
        try:
            profile = product_delivery_profile(str(delivery.get("profile_id") or ""))
        except ProductProfileError as exc:
            _append(
                issues,
                "DELIVERY_PROFILE_INVALID",
                f"D:_delivery_profile 非法:{exc}",
            )

    if draft.get("_intent_contract") is not None:
        base_intent_problems = validate_intent_contract(
            draft,
            require_confirmation=False,
        )
        for code in base_intent_problems:
            if code not in {issue.code for issue in issues}:
                _append(issues, code, f"D:_intent_contract {code}")
        if not base_intent_problems:
            confirmed_problems = validate_intent_contract(
                draft,
                require_confirmation=True,
            )
            for code in confirmed_problems:
                _append(
                    issues,
                    code,
                    f"D:_intent_contract {code}",
                    confirmation_only=code in {
                        "INTENT_CONFIRMATION_MISSING",
                        "INTENT_CONFIRMATION_STALE",
                    },
                )

    try:
        intent = IntentContractDraftV1.model_validate(draft.get("_intent_contract"))
    except ValidationError:
        intent = None
    if (
        intent is not None
        and intent.delivery is not None
        and intent.delivery.profile_id != str(delivery.get("profile_id") or "")
    ):
        _append(
            issues,
            "DELIVERY_PROFILE_INTENT_MISMATCH",
            "D:_delivery_profile 与 _intent_contract.delivery 的 profile_id 分叉",
        )

    source_repo = _mapping(draft.get("source_repo"))
    for field in ("distribution", "import_module", "resolved_commit", "license", "url"):
        if not _nonempty(source_repo.get(field)):
            _append(
                issues,
                f"SOURCE_REPO_{field.upper()}_MISSING",
                f"D:source_repo.{field} 为空 —— 见 GAPS.md 对应缺口",
            )

    tool = _mapping(draft.get("tool"))
    interface = _mapping(tool.get("interface"))
    input_interface = _mapping(interface.get("input"))
    output_interface = _mapping(interface.get("output"))
    capability = _mapping(draft.get("capability"))
    for path, value, code in (
        ("tool.name", tool.get("name"), "TOOL_NAME_MISSING"),
        ("tool.summary", tool.get("summary"), "TOOL_SUMMARY_MISSING"),
        (
            "tool.interface.input.format",
            input_interface.get("format"),
            "TOOL_INPUT_FORMAT_MISSING",
        ),
        (
            "tool.interface.output.format",
            output_interface.get("format"),
            "TOOL_OUTPUT_FORMAT_MISSING",
        ),
        (
            "capability.statement",
            capability.get("statement"),
            "CAPABILITY_STATEMENT_MISSING",
        ),
        (
            "capability.output_schema",
            capability.get("output_schema"),
            "CAPABILITY_OUTPUT_SCHEMA_MISSING",
        ),
    ):
        if not _nonempty(value):
            _append(issues, code, f"D:{path} 为空 —— 见 GAPS.md 对应缺口")

    try:
        parsed_tool = ToolSpec.model_validate(tool)
    except ValidationError as exc:
        parsed_tool = None
        _append(issues, "TOOL_SPEC_INVALID", f"D:tool 分节非法:{exc}")
    output_contract: ToolOutputContract | None = None
    workspace_profile = str(delivery.get("profile_id") or "") == (
        "workspace_bundle_v1"
    )
    if current:
        raw_contract = output_interface.get("contract")
        if workspace_profile:
            output_contract = None
        elif not _nonempty(raw_contract):
            _append(
                issues,
                "OUTPUT_CONTRACT_MISSING",
                "D:tool.interface.output.contract 为空 —— 见 GAPS.md 对应缺口",
            )
        else:
            try:
                output_contract = ToolOutputContract.model_validate(raw_contract)
            except ValidationError as exc:
                _append(
                    issues,
                    "OUTPUT_CONTRACT_INVALID",
                    f"D:tool.interface.output.contract 非法:{exc}",
                )
        if profile is not None and _nonempty(input_interface.get("format")):
            try:
                profile.assert_interface(interface)
            except ProductProfileError as exc:
                _append(
                    issues,
                    "DELIVERY_INTERFACE_UNSUPPORTED",
                    f"D:交付接口超出声明支持面:{exc}",
                )
        expected_schema = (
            CURRENT_WORKSPACE_TOOL_SCHEMA_VERSION
            if workspace_profile
            else CURRENT_TOOL_SCHEMA_VERSION
        )
        if parsed_tool is not None and parsed_tool.schema_version != expected_schema:
            # ToolSpec intentionally loads historical versions.  Product draft
            # currentness remains the explicit policy above.
            parsed_tool = None

    examples = (
        _read_workspace_examples(draft_dir, issues, parsed_tool)
        if workspace_profile
        else _read_examples(
            draft_dir,
            issues,
            output_contract=output_contract,
        )
    )
    if workspace_profile:
        _check_workspace_fixture_assets(draft_dir, issues, parsed_tool)

    import_module = str(source_repo.get("import_module") or "")
    reference_source = _read_text(draft_dir / REFERENCE_PY)
    if reference_source is None:
        _append(issues, "REFERENCE_MISSING", f"D:{REFERENCE_PY} 缺失")
    else:
        reference_tree = _parse_python(
            reference_source,
            code="REFERENCE_INVALID_PYTHON",
            problem="D:reference_impl 不是合法 Python",
            issues=issues,
        )
        if reference_tree is not None:
            reference_name = "build_workspace" if workspace_profile else "extract"
            reference_arguments = 2 if workspace_profile else 1
            reference_function = _sync_function(
                reference_tree,
                reference_name,
                positional_arguments=reference_arguments,
            )
            incomplete = reference_function is None or (
                not workspace_profile and not _has_value_return(reference_function)
            )
            if incomplete:
                _append(
                    issues,
                    "REFERENCE_PROTOCOL_INVALID",
                    (
                        "D:reference_impl 仍是骨架或协议不完整 —— "
                        + (
                            "必须定义同步 build_workspace(input_path, output_dir)"
                            if workspace_profile
                            else "必须定义有返回值的同步 extract(input_path)"
                        )
                    ),
                )
            if import_module and not _imports_module(reference_tree, import_module):
                _append(
                    issues,
                    "REFERENCE_UPSTREAM_IMPORT_MISSING",
                    (
                        f"D:reference_impl 未 import {import_module} —— "
                        "通关正控必须真调 pinned 上游"
                    ),
                )

    required_commitment_ids: tuple[str, ...] = ()
    if intent is not None:
        required_commitment_ids = tuple(
            commitment.commitment_id for commitment in intent.commitments
        )

    verifier_ready = True
    declared_commitment_ids: tuple[str, ...] = ()
    verifier_source = _read_text(draft_dir / SEMANTIC_VERIFIER_PY)
    if verifier_source is None:
        verifier_ready = False
        _append(
            issues,
            "SEMANTIC_VERIFIER_MISSING",
            f"D:{SEMANTIC_VERIFIER_PY} 缺失",
        )
    else:
        verifier_tree = _parse_python(
            verifier_source,
            code="SEMANTIC_VERIFIER_INVALID_PYTHON",
            problem="D:semantic_verifier 不是合法 Python",
            issues=issues,
        )
        if verifier_tree is None:
            verifier_ready = False
        else:
            verify = _sync_function(
                verifier_tree,
                "verify",
                positional_arguments=2,
            )
            if verify is None or not _has_value_return(verify):
                verifier_ready = False
                _append(
                    issues,
                    "SEMANTIC_VERIFIER_PROTOCOL_INVALID",
                    (
                        "D:semantic_verifier 仍是骨架或协议不完整 —— 必须定义"
                        "有返回值的同步 verify(input_path, artifact_path)"
                    ),
                )
            else:
                if _verifier_is_provably_reject_only(verifier_tree, verify):
                    verifier_ready = False
                    _append(
                        issues,
                        "SEMANTIC_VERIFIER_REJECT_ONLY",
                        (
                            "D:semantic_verifier 的所有可见返回路径都固定为 "
                            "ok=False —— 当前公开合同没有可验证的成功产物"
                        ),
                    )
                declared_commitment_ids = _declared_commitment_ids(
                    verify,
                    required_commitment_ids,
                )
            if import_module and not _imports_module(verifier_tree, import_module):
                verifier_ready = False
                _append(
                    issues,
                    "SEMANTIC_VERIFIER_UPSTREAM_IMPORT_MISSING",
                    (
                        f"D:semantic_verifier 未 import {import_module} —— "
                        "独立复核必须通过固定上游重算"
                    ),
                )
            if _imports_module(verifier_tree, "reference_impl"):
                verifier_ready = False
                _append(
                    issues,
                    "SEMANTIC_VERIFIER_REFERENCE_COUPLED",
                    (
                        "D:semantic_verifier 不得 import reference_impl —— "
                        "参考实现和独立判定器不能共因"
                    ),
                )
    lock_source, dependency_lock_text = _resolve_dependency_lock(
        draft,
        draft_dir,
        project_root,
        issues,
    )
    dependency_ready = lock_source in {"draft", "derived"}

    if not required_commitment_ids:
        coverage: CommitmentCoverage = "UNAVAILABLE"
    elif verifier_ready and set(declared_commitment_ids) == set(
        required_commitment_ids
    ):
        coverage = "COMPLETE"
    elif verifier_ready:
        # Exact coverage is enforced by the runtime verifier protocol.  Static
        # readiness must not require one particular source-code literal style.
        coverage = "RUNTIME_PENDING"
    else:
        coverage = "INCOMPLETE"

    blocking = [issue for issue in issues if not issue.confirmation_only]
    ready_to_confirm = compatible and not blocking
    ready = ready_to_confirm and not issues
    if not compatible:
        status: ReadinessStatus = "INCOMPATIBLE"
        recommended_action = (
            "该未冻结草稿不是当前可编辑结构；保留它供只读审计，"
            "请从原仓库和用户目标创建一项新任务。"
        )
    elif ready:
        status = "READY_TO_FREEZE"
        recommended_action = "草稿已通过 Core 冻结前检查，可以进入构建。"
    elif ready_to_confirm:
        status = "READY_TO_CONFIRM"
        recommended_action = "请显式确认当前用户目标、公开行为承诺和交付接口。"
    else:
        status = "INCOMPLETE"
        recommended_action = "请按 reason_codes 补全草稿；Core 复核通过前不会发车。"

    readiness = DraftReadinessV1(
        status=status,
        compatible=compatible,
        current=current,
        ready=ready,
        ready_to_confirm=ready_to_confirm,
        reason_codes=_dedupe([issue.code for issue in issues]),
        public_summary=DraftReadinessPublicSummaryV1(
            tool_schema_version=(
                int(tool["schema_version"])
                if isinstance(tool.get("schema_version"), int)
                else None
            ),
            semantic_verifier_ready=verifier_ready,
            semantic_commitment_count=len(required_commitment_ids),
            verifier_declared_commitment_count=len(declared_commitment_ids),
            commitment_coverage=coverage,
            dependency_lock_ready=dependency_ready,
            dependency_lock_source=lock_source,
            example_count=len(examples),
        ),
        recommended_action=recommended_action,
    )
    return _Evaluation(
        readiness=readiness,
        problems=tuple(issue.problem for issue in issues),
        dependency_lock_text=dependency_lock_text,
    )


def evaluate_draft_readiness(
    draft: dict,
    draft_dir: Path,
    *,
    project_root: Path | None = None,
) -> DraftReadinessV1:
    """Evaluate an already parsed draft without mutating the bundle."""

    if not isinstance(draft, dict):
        return DraftReadinessV1(
            status="INCOMPATIBLE",
            compatible=False,
            current=False,
            ready=False,
            ready_to_confirm=False,
            reason_codes=["DRAFT_DOCUMENT_INVALID"],
            public_summary=DraftReadinessPublicSummaryV1(),
            recommended_action=(
                "草稿根节点无效；保留原文件供审计，并从原仓库和用户目标创建新任务。"
            ),
        )
    return _evaluate(
        draft,
        Path(draft_dir),
        project_root=project_root,
    ).readiness


def draft_completion_problems(
    draft: dict,
    draft_dir: Path,
    *,
    project_root: Path | None = None,
) -> list[str]:
    """Legacy D-gate messages projected from the same readiness evaluation."""

    if not isinstance(draft, dict):
        return ["D:draft.yaml 根节点必须为对象"]
    return list(
        _evaluate(
            draft,
            Path(draft_dir),
            project_root=project_root,
        ).problems
    )


def resolved_dependency_lock(
    draft: dict,
    draft_dir: Path,
    *,
    project_root: Path | None = None,
) -> str:
    """Return the exact validated lock selected by readiness, or ``""``."""

    if not isinstance(draft, dict):
        return ""
    evaluation = _evaluate(
        draft,
        Path(draft_dir),
        project_root=project_root,
    )
    if not evaluation.readiness.public_summary.dependency_lock_ready:
        return ""
    return evaluation.dependency_lock_text


def read_draft_readiness(
    draft_dir: Path,
    *,
    project_root: Path | None = None,
) -> DraftReadinessV1:
    """Safely parse ``draft.yaml`` and return a structured result, never mutate."""

    draft_dir = Path(draft_dir)
    draft_path = draft_dir / DRAFT_YAML
    source = _read_text(draft_path)
    if source is None:
        return DraftReadinessV1(
            status="INCOMPATIBLE",
            compatible=False,
            current=False,
            ready=False,
            ready_to_confirm=False,
            reason_codes=["DRAFT_DOCUMENT_MISSING"],
            public_summary=DraftReadinessPublicSummaryV1(),
            recommended_action="草稿不可安全读取；请检查路径，且不要绕过受管任务目录。",
        )
    try:
        draft = yaml.safe_load(source) or {}
    except yaml.YAMLError:
        draft = None
    if not isinstance(draft, dict):
        return evaluate_draft_readiness(draft, draft_dir, project_root=project_root)  # type: ignore[arg-type]
    return evaluate_draft_readiness(draft, draft_dir, project_root=project_root)


# Concise public alias for callers that already have a parsed draft.
draft_readiness = evaluate_draft_readiness
