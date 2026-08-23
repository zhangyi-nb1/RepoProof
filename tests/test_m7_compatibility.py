"""M7 schema/prompt wiring without changing frozen v1/v2 semantics."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from repoproof.adoption.assembly.tool_assembler import (
    _tool_contract_projection,
    assemble_tool_task,
    next_tool_task_id,
)
from repoproof.adoption.intake.tool_confirm import check_draft_complete
from repoproof.domain.models import (
    TaskContract,
    ToolInterface,
    ToolInterfaceIO,
    ToolOutputContract,
    ToolRuntimeSpec,
    ToolSpec,
)
from repoproof.harness.contract_adequacy import evaluate_adequacy
from repoproof.harness.requirement_spec import load_requirement_spec
from repoproof.runner.host_guided import (
    HostContract,
    build_host_prompt,
    verify_frozen_files,
)
from repoproof.runner.tool_host_bridge import materialize_tool_task

REPO = Path(__file__).resolve().parents[1]

_RUNTIME_V1 = {
    "mode": "http_sidecar",
    "profile_id": "tool-http-sidecar-v1",
    "lifecycle": "per_invocation",
    "credentials": "none",
    "network": "loopback_only",
    "protocol": "repoproof-http-sidecar-v1",
    "startup_timeout_seconds": 10,
    "request_timeout_seconds": 120,
    "shutdown_timeout_seconds": 3,
}


def _interface(*, with_contract: bool = True) -> ToolInterface:
    contract = (
        ToolOutputContract(media_type="text/plain", root_type="text", required={})
        if with_contract else None
    )
    return ToolInterface(
        usage="m7-demo <input.txt>",
        input=ToolInterfaceIO(kind="file", format="text"),
        output=ToolInterfaceIO(kind="stdout", format="text", contract=contract),
        exit_codes={"0": "success", "1": "user_error", "2": "internal_error"},
    )


def _spec(schema_version: int) -> ToolSpec:
    values: dict = {
        "schema_version": schema_version,
        "name": "m7-demo",
        "summary": "compatibility fixture",
        "interface": _interface(with_contract=schema_version >= 2),
    }
    if schema_version == 3:
        values["runtime"] = ToolRuntimeSpec.model_validate(_RUNTIME_V1)
    return ToolSpec.model_validate(values)


@pytest.mark.parametrize("schema_version", [1, 2])
def test_v1_v2_must_omit_runtime_and_keep_old_projection(
    schema_version: int,
) -> None:
    spec = _spec(schema_version)
    assert spec.runtime is None
    assert "runtime" not in spec.model_fields_set

    projected = _tool_contract_projection(spec)
    expected = spec.model_dump()
    assert projected == expected
    assert "runtime" not in projected

    explicit_null = projected | {"runtime": None}
    with pytest.raises(ValidationError, match="runtime: null is not an omission"):
        ToolSpec.model_validate(explicit_null)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("startup_timeout_seconds", 11),
        ("request_timeout_seconds", 121),
        ("shutdown_timeout_seconds", 4),
        ("network", "internet"),
        ("lifecycle", "persistent"),
    ],
)
def test_v3_runtime_profile_is_complete_and_immutable(field: str, value: object) -> None:
    runtime = dict(_RUNTIME_V1)
    runtime[field] = value
    with pytest.raises(ValidationError):
        ToolRuntimeSpec.model_validate(runtime)

    missing = dict(_RUNTIME_V1)
    missing.pop(field)
    with pytest.raises(ValidationError):
        ToolRuntimeSpec.model_validate(missing)


def test_v3_requires_runtime_file_stdout_and_output_contract() -> None:
    valid = _spec(3).model_dump()
    for path, value, message in (
        (("runtime",), None, "requires tool.runtime"),
        (("interface", "input", "kind"), "stdin", "file input only"),
        (("interface", "output", "kind"), "out_file", "stdout output only"),
        (("interface", "output", "contract"), None, "executable output contract"),
    ):
        broken = json.loads(json.dumps(valid))
        cursor = broken
        for key in path[:-1]:
            cursor = cursor[key]
        cursor[path[-1]] = value
        with pytest.raises(ValidationError, match=message):
            ToolSpec.model_validate(broken)


def _example_source(root: Path) -> tuple[Path, list[dict]]:
    source = root / "example-source"
    source.mkdir(parents=True)
    examples: list[dict] = []
    for index in range(1, 4):
        input_name = f"input-{index}.txt"
        expected_name = f"expected-{index}.txt"
        (source / input_name).write_text(f"input {index}", encoding="utf-8")
        (source / expected_name).write_text(f"output {index}", encoding="utf-8")
        examples.append({
            "input_file": input_name,
            "expected_file": expected_name,
        })
    return source, examples


def _assemble(root: Path, schema_version: int) -> dict:
    source, examples = _example_source(root)
    return assemble_tool_task(
        root,
        goal="convert fixture text deterministically",
        repo_url="https://example.invalid/demo-upstream",
        resolved_commit="a" * 40,
        distribution="demo-upstream",
        import_module="json",
        license_id="MIT",
        tool=_spec(schema_version),
        examples=examples,
        example_src_dir=source,
        reference_impl=(
            "import json\nfrom pathlib import Path\n"
            "class UserInputError(ValueError): pass\n"
            "def extract(input_path: Path) -> str: "
            "return input_path.read_text(encoding='utf-8')\n"
        ),
        input_ext=".txt",
        malformed_applicable=False,
        capability_output_schema="text",
    )


def test_v2_assembly_does_not_add_runtime_null_bytes(tmp_path: Path) -> None:
    spec = _spec(2)
    info = _assemble(tmp_path, 2)
    raw = (tmp_path / "contracts" / f"{info['task_id']}.yaml").read_text(
        encoding="utf-8"
    )
    frozen_tool = yaml.safe_load(raw)["tool"]
    assert "runtime" not in frozen_tool
    assert '"runtime": null' not in raw
    expected_line = (
        "tool: "
        + json.dumps(_tool_contract_projection(spec), ensure_ascii=False)
        + "\n"
    )
    assert expected_line in raw


def test_max_plus_one_allocator_does_not_fill_history_gaps(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    runs = tmp_path / "runs"
    contracts.mkdir()
    runs.mkdir()
    (contracts / "tool-m7-demo-v1.yaml").write_text("old", encoding="utf-8")
    (runs / "tool-m7-demo-v4-run-1").mkdir()
    assert next_tool_task_id(tmp_path, "m7-demo") == "tool-m7-demo-v5"


def _draft(spec: ToolSpec) -> dict:
    return {
        "source_repo": {
            "distribution": "demo-upstream",
            "import_module": "json",
            "resolved_commit": "a" * 40,
            "license": "MIT",
            "url": "https://example.invalid/demo-upstream",
        },
        "tool": _tool_contract_projection(spec),
        "capability": {"statement": "convert text", "output_schema": "text"},
    }


def _complete_draft_files(root: Path) -> None:
    (root / "examples.yaml").write_text(
        yaml.safe_dump({
            "examples": [
                {"input": "a", "expected": "a"},
                {"input": "b", "expected": "b"},
                {"input": "c", "expected": "c"},
            ]
        }),
        encoding="utf-8",
    )
    (root / "reference_impl.py").write_text(
        "import json\nfrom pathlib import Path\n"
        "def extract(input_path: Path) -> str: return input_path.read_text()\n",
        encoding="utf-8",
    )


def test_draft_gate_rejects_v2_runtime_null_and_noncanonical_v3(
    tmp_path: Path,
) -> None:
    _complete_draft_files(tmp_path)
    v2 = _draft(_spec(2))
    v2["tool"]["runtime"] = None
    problems = check_draft_complete(v2, tmp_path)
    assert any("runtime:null" in problem for problem in problems)

    v3 = _draft(_spec(3))
    v3["tool"]["runtime"]["request_timeout_seconds"] = 121
    problems = check_draft_complete(v3, tmp_path)
    assert any("tool.runtime 非法" in problem for problem in problems)


def test_v3_adequacy_checks_fixed_runtime_and_file_stdout(tmp_path: Path) -> None:
    info = _assemble(tmp_path, 3)
    contract_path = tmp_path / "contracts" / f"{info['task_id']}.yaml"
    contract, _ = TaskContract.load_frozen(contract_path, require_sidecar=True)
    requirement_spec, _ = load_requirement_spec(
        tmp_path / "contracts" / f"{info['task_id']}.requirements.yaml"
    )
    fixtures = tmp_path / "oracle" / info["task_id"] / "fixtures"

    valid = evaluate_adequacy(
        spec=requirement_spec,
        capability_nodes=[],
        regression_nodes=[],
        rendered_prompt="",
        contract_path=contract_path,
        contract=contract,
        tool_example_docs_dir=fixtures,
    )
    assert valid.checked["tool_managed_runtime_present"] is True
    assert valid.checked["tool_managed_runtime_fixed"] is True
    assert valid.checked["tool_managed_file_stdout_interface"] is True

    broken = contract.model_copy(deep=True)
    assert broken.tool is not None and broken.tool.runtime is not None
    broken.tool.runtime.request_timeout_seconds = 121  # type: ignore[assignment]
    broken.tool.interface.input.kind = "stdin"
    invalid = evaluate_adequacy(
        spec=requirement_spec,
        capability_nodes=[],
        regression_nodes=[],
        rendered_prompt="",
        contract_path=contract_path,
        contract=broken,
        tool_example_docs_dir=fixtures,
    )
    assert invalid.checked["tool_managed_runtime_fixed"] is False
    assert invalid.checked["tool_managed_file_stdout_interface"] is False


def _host_anchor_hashes(tool_bin: str) -> dict[str, str]:
    digest = "0" * 64
    return {
        "src/inflect_tool/__init__.py": digest,
        "src/inflect_tool/__main__.py": digest,
        "src/inflect_tool/main.py": digest,
        "src/inflect_tool/sidecar_server.py": digest,
        "src/inflect_tool/sidecar_supervisor.py": digest,
        "src/inflect_tool/sidecar_contract.py": digest,
        tool_bin: digest,
        "build.sh": digest,
        "tool.json": digest,
        "pyproject.toml": digest,
    }


def test_local_tool_v2_host_profile_is_wired_without_runtime_profile_reuse() -> None:
    v1, _ = HostContract.load(
        REPO / "tool_tasks" / "tool-inflect-tool-v1" / "contract.yaml"
    )
    doc = v1.model_dump(mode="json")
    doc["prompt_profile"] = "local-tool-v2"
    doc["frozen_file_sha256"] = _host_anchor_hashes(v1.host.tool_bin)
    v2 = HostContract.model_validate(doc)

    assert v2.runtime_profile == v1.runtime_profile == "rt-inprocess-v1"
    v1_prompt = build_host_prompt(v1, wheel_note="fixture-wheelhouse")
    v2_prompt = build_host_prompt(v2, wheel_note="fixture-wheelhouse")
    assert v2_prompt.startswith(v1_prompt)
    for marker in (
        "MANAGED SIDECAR DELIVERY CONTRACT",
        "sidecar_server.py",
        "sidecar_supervisor.py",
        "sidecar_contract.py",
        "127.0.0.1",
        "no persistent daemon",
    ):
        assert marker in v2_prompt

    doc["frozen_file_sha256"] = {}
    with pytest.raises(ValidationError, match="缺机器冻结锚"):
        HostContract.model_validate(doc)

    doc["frozen_file_sha256"] = _host_anchor_hashes(v1.host.tool_bin)
    del doc["frozen_file_sha256"]["src/inflect_tool/__init__.py"]
    with pytest.raises(ValidationError, match="完整冻结"):
        HostContract.model_validate(doc)


def test_v3_bridge_freezes_the_actual_copied_entry_chain(tmp_path: Path) -> None:
    project = tmp_path / "project"
    info = _assemble(project, 3)
    host_contract_path = materialize_tool_task(
        project,
        project / "contracts" / f"{info['task_id']}.yaml",
        out_root=tmp_path / "tasks",
        host_copy_root=tmp_path / "hosts",
    )
    host_contract, _ = HostContract.load(host_contract_path)
    assert host_contract.prompt_profile == "local-tool-v2"
    assert len(host_contract.frozen_file_sha256) == 10
    copied_host = Path(host_contract.host.copy_path)
    assert verify_frozen_files(
        copied_host, host_contract.frozen_file_sha256
    )["ok"] is True
    init_path = copied_host / "src" / "m7_demo" / "__init__.py"
    init_path.write_text("# entry-chain drift\n", encoding="utf-8")
    drift = verify_frozen_files(copied_host, host_contract.frozen_file_sha256)
    assert drift["ok"] is False
    assert any(
        finding["path"] == "src/m7_demo/__init__.py"
        and finding["reason"] == "FROZEN_FILE_SHA256_MISMATCH"
        for finding in drift["findings"]
    )


def test_frozen_file_verifier_is_no_follow_and_fail_closed(tmp_path: Path) -> None:
    host = tmp_path / "host"
    path = host / "src" / "demo" / "main.py"
    path.parent.mkdir(parents=True)
    path.write_text("fixed\n", encoding="utf-8")
    expected = {"src/demo/main.py": hashlib.sha256(path.read_bytes()).hexdigest()}

    assert verify_frozen_files(host, {}) == {
        "ok": True,
        "checked": 0,
        "findings": [],
    }
    assert verify_frozen_files(host, expected)["ok"] is True

    path.write_text("drift\n", encoding="utf-8")
    drift = verify_frozen_files(host, expected)
    assert drift["ok"] is False
    assert drift["findings"][0]["reason"] == "FROZEN_FILE_SHA256_MISMATCH"

    target = tmp_path / "outside.py"
    target.write_text("fixed\n", encoding="utf-8")
    path.unlink()
    path.symlink_to(target)
    unsafe = verify_frozen_files(host, expected)
    assert unsafe["ok"] is False
    assert unsafe["findings"][0]["reason"] == "MISSING_OR_UNSAFE_FROZEN_FILE"
