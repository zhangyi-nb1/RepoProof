from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from repoproof.adoption.assembly.tool_assembler import assemble_tool_task
from repoproof.domain.models import (
    ToolInterface,
    ToolInterfaceIO,
    ToolOutputContract,
    ToolRuntimeSpec,
    ToolSpec,
)
from repoproof.runner.tool_mcp import write_mcp_server
from repoproof.runner.tool_release import ACTIVE, append_release_decision


def _runtime(**overrides) -> dict:
    values = {
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
    values.update(overrides)
    return values


def _spec(*, root_type: str = "text") -> ToolSpec:
    contract = (
        ToolOutputContract(
            media_type="text/plain", root_type="text", required={}
        )
        if root_type == "text"
        else ToolOutputContract(
            media_type="application/json", root_type="object", required={"ok": "boolean"}
        )
    )
    return ToolSpec(
        schema_version=3,
        name="sidecar-demo",
        summary="managed sidecar fixture",
        interface=ToolInterface(
            usage="sidecar-demo <input.txt>",
            input=ToolInterfaceIO(kind="file", format="text"),
            output=ToolInterfaceIO(
                kind="stdout",
                format="text" if root_type == "text" else "json-object",
                contract=contract,
            ),
            exit_codes={"0": "success", "1": "user_error", "2": "internal_error"},
        ),
        runtime=ToolRuntimeSpec.model_validate(_runtime()),
    )


def test_toolspec_v3_runtime_is_strict_and_separate() -> None:
    spec = _spec()
    assert spec.runtime is not None
    assert spec.runtime.profile_id == "tool-http-sidecar-v1"

    doc = spec.model_dump()
    doc.pop("runtime")
    with pytest.raises(ValidationError, match="requires tool.runtime"):
        ToolSpec.model_validate(doc)

    doc = spec.model_dump()
    doc["runtime"]["network"] = "internet"
    with pytest.raises(ValidationError):
        ToolSpec.model_validate(doc)

    doc = spec.model_dump()
    doc["runtime"]["launch_command"] = ["sh", "-c", "anything"]
    with pytest.raises(ValidationError, match="Extra inputs"):
        ToolSpec.model_validate(doc)

    doc = spec.model_dump()
    doc["runtime"]["runtime_profile"] = "rt-upstream-sidecar-v1"
    with pytest.raises(ValidationError, match="Extra inputs"):
        ToolSpec.model_validate(doc)

    doc = spec.model_dump()
    doc["interface"]["output"]["contract"] = None
    with pytest.raises(ValidationError, match="executable output contract"):
        ToolSpec.model_validate(doc)


def test_v1_v2_compatibility_and_v3_file_stdout_boundary() -> None:
    v2 = _spec().model_dump()
    v2["schema_version"] = 2
    v2.pop("runtime")
    assert ToolSpec.model_validate(v2).runtime is None

    bad = _spec().model_dump()
    bad["interface"]["input"]["kind"] = "stdin"
    with pytest.raises(ValidationError, match="file input only"):
        ToolSpec.model_validate(bad)

    bad = _spec().model_dump()
    bad["interface"]["output"]["kind"] = "out_file"
    with pytest.raises(ValidationError, match="stdout output only"):
        ToolSpec.model_validate(bad)


def _assembled_runtime(tmp_path: Path, *, root_type: str = "text") -> tuple[Path, Path]:
    examples = tmp_path / "example-source"
    examples.mkdir(parents=True)
    rows: list[dict] = []
    for index, text in enumerate(("alpha", "beta", "gamma"), start=1):
        inp = f"input-{index}.txt"
        expected = f"expected-{index}.txt"
        (examples / inp).write_text(text, encoding="utf-8")
        output = text.upper() if root_type == "text" else json.dumps({"ok": True})
        (examples / expected).write_text(output, encoding="utf-8")
        rows.append({"input_file": inp, "expected_file": expected})
    info = assemble_tool_task(
        tmp_path,
        goal="convert the input deterministically",
        repo_url="https://example.invalid/upstream",
        resolved_commit="a" * 40,
        distribution="demo-upstream",
        import_module="json",
        license_id="MIT",
        tool=_spec(root_type=root_type),
        examples=rows,
        example_src_dir=examples,
        reference_impl="from pathlib import Path\nimport json\n"
        "class UserInputError(ValueError): pass\n"
        "def extract(input_path: Path) -> str: return input_path.read_text().upper()\n",
        input_ext=".txt",
        malformed_applicable=False,
        capability_output_schema="text" if root_type == "text" else "json object",
    )
    skeleton = tmp_path / "fixtures" / "tool_skeleton_sidecar-demo"
    assert info["task_id"] == "tool-sidecar-demo-v1"
    return skeleton, skeleton / "src" / "sidecar_demo" / "impl.py"


def _run(
    skeleton: Path,
    input_path: Path,
    *,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(skeleton / "src")
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "sidecar_demo", str(input_path)],
        cwd=skeleton,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def _assert_pid_gone(pid: int, *, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.02)
    pytest.fail(f"managed sidecar process survived cleanup: pid={pid}")


def test_generated_sidecar_uses_loopback_protocol_and_cleans_up(tmp_path: Path) -> None:
    skeleton, impl = _assembled_runtime(tmp_path)
    impl.write_text(
        "from pathlib import Path\n"
        "class UserInputError(ValueError): pass\n"
        "def extract(input_path: Path) -> str:\n"
        "    text = input_path.read_text()\n"
        "    if text == 'bad': raise UserInputError('bad fixture')\n"
        "    return text.upper()\n",
        encoding="utf-8",
    )
    good = tmp_path / "good.txt"
    good.write_text("hello", encoding="utf-8")
    result = _run(skeleton, good)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "HELLO\n"
    assert result.stderr == ""

    bad = tmp_path / "bad.txt"
    bad.write_text("bad", encoding="utf-8")
    result = _run(skeleton, bad)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "bad fixture" in result.stderr

    server = (skeleton / "src" / "sidecar_demo" / "sidecar_server.py").read_text()
    supervisor = (
        skeleton / "src" / "sidecar_demo" / "sidecar_supervisor.py"
    ).read_text()
    assert '("127.0.0.1", 0)' in server
    assert '"/healthz"' in server and '"/v1/invoke"' in server
    assert "_wait_group_gone" in supervisor
    assert "proc.poll()" in supervisor
    assert "_signal_group(pgid, signal.SIGKILL)" in supervisor
    assert "shell=True" not in supervisor


def test_generated_supervisor_enforces_output_contract(tmp_path: Path) -> None:
    skeleton, impl = _assembled_runtime(tmp_path, root_type="object")
    impl.write_text(
        "from pathlib import Path\n"
        "class UserInputError(ValueError): pass\n"
        "def extract(input_path: Path) -> str: return 'not-json'\n",
        encoding="utf-8",
    )
    source = tmp_path / "source.txt"
    source.write_text("anything", encoding="utf-8")
    result = _run(skeleton, source)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "tool-output-contract" in result.stderr


def test_generated_output_contract_cannot_be_disabled_by_python_optimize(
    tmp_path: Path,
) -> None:
    skeleton, impl = _assembled_runtime(tmp_path, root_type="object")
    impl.write_text(
        "from pathlib import Path\n"
        "class UserInputError(ValueError): pass\n"
        "def extract(input_path: Path) -> str: return 'not-json'\n",
        encoding="utf-8",
    )
    source = tmp_path / "source.txt"
    source.write_text("anything", encoding="utf-8")
    result = _run(
        skeleton,
        source,
        env_overrides={"PYTHONOPTIMIZE": "1"},
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "tool-output-contract" in result.stderr
    contract_source = (
        skeleton / "src" / "sidecar_demo" / "sidecar_contract.py"
    ).read_text(encoding="utf-8")
    assert "assert not errors" not in contract_source
    assert "raise OutputContractViolation" in contract_source


def test_child_environment_is_allowlisted_and_uses_ephemeral_home(
    tmp_path: Path,
) -> None:
    skeleton, impl = _assembled_runtime(tmp_path, root_type="object")
    impl.write_text(
        "from pathlib import Path\nimport json, os\n"
        "class UserInputError(ValueError): pass\n"
        "def extract(input_path: Path) -> str:\n"
        "    return json.dumps({\n"
        "        'ok': True,\n"
        "        'aws': os.environ.get('AWS_SECRET_ACCESS_KEY'),\n"
        "        'custom': os.environ.get('REPOPROOF_TEST_CREDENTIAL'),\n"
        "        'home': os.environ.get('HOME'),\n"
        "        'path': os.environ.get('PATH'),\n"
        "        'pythonpath': os.environ.get('PYTHONPATH'),\n"
        "        'tmpdir': os.environ.get('TMPDIR'),\n"
        "    }, sort_keys=True)\n",
        encoding="utf-8",
    )
    source = tmp_path / "source.txt"
    source.write_text("anything", encoding="utf-8")
    ambient_home = str(tmp_path / "ambient-home")
    result = _run(
        skeleton,
        source,
        env_overrides={
            "AWS_SECRET_ACCESS_KEY": "must-not-reach-capability",
            "HOME": ambient_home,
            "PATH": "/credential-bearing/ambient-path",
            "PYTHONPATH": os.pathsep.join(
                ("/ambient/module-injection", str(skeleton / "src"))
            ),
            "REPOPROOF_TEST_CREDENTIAL": "must-not-reach-capability",
        },
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["aws"] is None
    assert payload["custom"] is None
    assert payload["home"] != ambient_home
    assert payload["home"].endswith("/home")
    assert "repoproof-sidecar-" in payload["home"]
    assert payload["tmpdir"].endswith("/tmp")
    assert payload["path"] != "/credential-bearing/ambient-path"
    assert payload["pythonpath"] == str(skeleton / "src")
    assert not Path(payload["home"]).exists()


def test_generated_sidecar_denies_non_loopback_connect(tmp_path: Path) -> None:
    skeleton, impl = _assembled_runtime(tmp_path)
    impl.write_text(
        "from pathlib import Path\nimport socket\n"
        "class UserInputError(ValueError): pass\n"
        "def extract(input_path: Path) -> str:\n"
        "    socket.create_connection(('198.51.100.1', 80), timeout=0.1)\n"
        "    return 'unexpected'\n",
        encoding="utf-8",
    )
    source = tmp_path / "source.txt"
    source.write_text("anything", encoding="utf-8")
    result = _run(skeleton, source)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "PermissionError" in result.stderr


def test_network_guard_is_installed_before_agent_owned_impl_import(
    tmp_path: Path,
) -> None:
    skeleton, impl = _assembled_runtime(tmp_path)
    impl.write_text(
        "from pathlib import Path\nimport socket\n"
        "socket.create_connection(('198.51.100.1', 80), timeout=0.1)\n"
        "class UserInputError(ValueError): pass\n"
        "def extract(input_path: Path) -> str: return 'unexpected'\n",
        encoding="utf-8",
    )
    source = tmp_path / "source.txt"
    source.write_text("anything", encoding="utf-8")
    result = _run(skeleton, source)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "exited during startup" in result.stderr


def test_loopback_protocol_ignores_ambient_http_proxy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skeleton, impl = _assembled_runtime(tmp_path)
    impl.write_text(
        "from pathlib import Path\n"
        "class UserInputError(ValueError): pass\n"
        "def extract(input_path: Path) -> str: return input_path.read_text().upper()\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    source = tmp_path / "source.txt"
    source.write_text("local", encoding="utf-8")
    result = _run(skeleton, source)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "LOCAL\n"


def test_dynamic_ports_allow_concurrent_invocations(tmp_path: Path) -> None:
    skeleton, impl = _assembled_runtime(tmp_path)
    impl.write_text(
        "from pathlib import Path\n"
        "class UserInputError(ValueError): pass\n"
        "def extract(input_path: Path) -> str: return input_path.read_text().upper()\n",
        encoding="utf-8",
    )
    source = tmp_path / "source.txt"
    source.write_text("parallel", encoding="utf-8")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _index: _run(skeleton, source), range(4)))
    assert [result.returncode for result in results] == [0, 0, 0, 0]
    assert [result.stdout for result in results] == ["PARALLEL\n"] * 4


def test_startup_timeout_reaps_the_child_process(tmp_path: Path) -> None:
    skeleton, _impl = _assembled_runtime(tmp_path)
    package = skeleton / "src" / "sidecar_demo"
    pid_file = tmp_path / "sleeping-sidecar.pid"
    (package / "sidecar_server.py").write_text(
        "import os, time\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    supervisor = package / "sidecar_supervisor.py"
    supervisor.write_text(
        supervisor.read_text(encoding="utf-8").replace(
            "STARTUP_TIMEOUT_SECONDS = 10", "STARTUP_TIMEOUT_SECONDS = 1"
        ),
        encoding="utf-8",
    )
    source = tmp_path / "source.txt"
    source.write_text("anything", encoding="utf-8")
    started = time.monotonic()
    result = _run(skeleton, source)
    assert time.monotonic() - started < 8
    assert result.returncode == 2
    assert "startup timed out" in result.stderr
    pid = int(pid_file.read_text(encoding="utf-8"))
    _assert_pid_gone(pid)


def test_leader_early_exit_still_reaps_its_helper_process(tmp_path: Path) -> None:
    skeleton, _impl = _assembled_runtime(tmp_path)
    package = skeleton / "src" / "sidecar_demo"
    helper_pid = tmp_path / "early-exit-helper.pid"
    (package / "sidecar_server.py").write_text(
        "from pathlib import Path\n"
        "import subprocess, sys, time\n"
        "helper_code = "
        + repr(
            "from pathlib import Path\n"
            "import os, signal, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            f"Path({str(helper_pid)!r}).write_text(str(os.getpid()))\n"
            "time.sleep(30)\n"
        )
        + "\n"
        "subprocess.Popen([sys.executable, '-c', helper_code])\n"
        f"marker = Path({str(helper_pid)!r})\n"
        "deadline = time.monotonic() + 5\n"
        "while not marker.exists() and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "raise SystemExit(17)\n",
        encoding="utf-8",
    )
    supervisor = package / "sidecar_supervisor.py"
    supervisor.write_text(
        supervisor.read_text(encoding="utf-8").replace(
            "SHUTDOWN_TIMEOUT_SECONDS = 3", "SHUTDOWN_TIMEOUT_SECONDS = 1"
        ),
        encoding="utf-8",
    )
    source = tmp_path / "source.txt"
    source.write_text("anything", encoding="utf-8")
    result = _run(skeleton, source)
    assert result.returncode == 2
    assert "exited during startup: 17" in result.stderr
    _assert_pid_gone(int(helper_pid.read_text(encoding="utf-8")))


def test_shutdown_timeout_kills_an_uncooperative_process(tmp_path: Path) -> None:
    skeleton, impl = _assembled_runtime(tmp_path)
    package = skeleton / "src" / "sidecar_demo"
    pid_file = tmp_path / "uncooperative-sidecar.pid"
    impl.write_text(
        "from pathlib import Path\nimport os\n"
        "class UserInputError(ValueError): pass\n"
        f"def extract(input_path: Path) -> str:\n"
        f"    Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
        "    return input_path.read_text().upper()\n",
        encoding="utf-8",
    )
    server = package / "sidecar_server.py"
    server.write_text(
        server.read_text(encoding="utf-8")
        .replace("import os\n", "import os\nimport signal\n")
        .replace(
            "server = _Server((\"127.0.0.1\", 0), _Handler)",
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "    server = _Server((\"127.0.0.1\", 0), _Handler)",
        ),
        encoding="utf-8",
    )
    supervisor = package / "sidecar_supervisor.py"
    supervisor.write_text(
        supervisor.read_text(encoding="utf-8").replace(
            "SHUTDOWN_TIMEOUT_SECONDS = 3", "SHUTDOWN_TIMEOUT_SECONDS = 1"
        ),
        encoding="utf-8",
    )
    source = tmp_path / "source.txt"
    source.write_text("shutdown", encoding="utf-8")
    started = time.monotonic()
    result = _run(skeleton, source)
    assert time.monotonic() - started < 8
    assert result.returncode == 0, result.stderr
    assert result.stdout == "SHUTDOWN\n"
    pid = int(pid_file.read_text(encoding="utf-8"))
    _assert_pid_gone(pid)


def test_request_timeout_and_malformed_response_are_internal_errors(
    tmp_path: Path,
) -> None:
    skeleton, impl = _assembled_runtime(tmp_path)
    package = skeleton / "src" / "sidecar_demo"
    child_pid = tmp_path / "request-sidecar.pid"
    impl.write_text(
        "from pathlib import Path\nimport os, time\n"
        "class UserInputError(ValueError): pass\n"
        f"def extract(input_path: Path) -> str:\n"
        f"    Path({str(child_pid)!r}).write_text(str(os.getpid()))\n"
        "    time.sleep(30)\n"
        "    return 'late'\n",
        encoding="utf-8",
    )
    supervisor = package / "sidecar_supervisor.py"
    supervisor.write_text(
        supervisor.read_text(encoding="utf-8").replace(
            "REQUEST_TIMEOUT_SECONDS = 120", "REQUEST_TIMEOUT_SECONDS = 1"
        ),
        encoding="utf-8",
    )
    source = tmp_path / "source.txt"
    source.write_text("anything", encoding="utf-8")
    result = _run(skeleton, source)
    assert result.returncode == 2
    assert "timed out or failed" in result.stderr
    pid = int(child_pid.read_text(encoding="utf-8"))
    _assert_pid_gone(pid)

    skeleton, _impl = _assembled_runtime(tmp_path / "malformed")
    server = skeleton / "src" / "sidecar_demo" / "sidecar_server.py"
    original_json_encoder = (
        'raw = json.dumps(\n'
        '            body, ensure_ascii=False, sort_keys=True, '
        'separators=(",", ":")\n'
        '        ).encode("utf-8")'
    )
    server.write_text(
        server.read_text(encoding="utf-8").replace(
            original_json_encoder,
            'raw = b"{"',
        ),
        encoding="utf-8",
    )
    source = tmp_path / "malformed" / "source.txt"
    source.write_text("anything", encoding="utf-8")
    result = _run(skeleton, source)
    assert result.returncode == 2
    assert "not valid JSON" in result.stderr


def test_health_and_invoke_share_one_request_timeout_budget(
    tmp_path: Path,
) -> None:
    skeleton, impl = _assembled_runtime(tmp_path)
    package = skeleton / "src" / "sidecar_demo"
    impl.write_text(
        "from pathlib import Path\nimport time\n"
        "class UserInputError(ValueError): pass\n"
        "def extract(input_path: Path) -> str:\n"
        "    time.sleep(0.7)\n"
        "    return 'late'\n",
        encoding="utf-8",
    )
    server = package / "sidecar_server.py"
    server.write_text(
        server.read_text(encoding="utf-8")
        .replace("import tempfile\n", "import tempfile\nimport time\n")
        .replace(
            "    def do_GET(self):\n",
            "    def do_GET(self):\n        time.sleep(0.7)\n",
        ),
        encoding="utf-8",
    )
    supervisor = package / "sidecar_supervisor.py"
    supervisor.write_text(
        supervisor.read_text(encoding="utf-8").replace(
            "REQUEST_TIMEOUT_SECONDS = 120", "REQUEST_TIMEOUT_SECONDS = 1"
        ),
        encoding="utf-8",
    )
    source = tmp_path / "source.txt"
    source.write_text("anything", encoding="utf-8")
    started = time.monotonic()
    result = _run(skeleton, source)
    elapsed = time.monotonic() - started
    assert result.returncode == 2
    assert "timed out or failed" in result.stderr
    assert elapsed < 3


def test_request_timeout_reaps_sidecar_descendants(tmp_path: Path) -> None:
    skeleton, impl = _assembled_runtime(tmp_path)
    package = skeleton / "src" / "sidecar_demo"
    child_pid = tmp_path / "helper.pid"
    impl.write_text(
        "from pathlib import Path\nimport subprocess, sys, time\n"
        "class UserInputError(ValueError): pass\n"
        "def extract(input_path: Path) -> str:\n"
        "    child = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(30)'])\n"
        f"    Path({str(child_pid)!r}).write_text(str(child.pid))\n"
        "    time.sleep(30)\n"
        "    return 'late'\n",
        encoding="utf-8",
    )
    supervisor = package / "sidecar_supervisor.py"
    supervisor.write_text(
        supervisor.read_text(encoding="utf-8").replace(
            "REQUEST_TIMEOUT_SECONDS = 120", "REQUEST_TIMEOUT_SECONDS = 1"
        ),
        encoding="utf-8",
    )
    source = tmp_path / "source.txt"
    source.write_text("anything", encoding="utf-8")
    result = _run(skeleton, source)
    assert result.returncode == 2
    pid = int(child_pid.read_text(encoding="utf-8"))
    _assert_pid_gone(pid)


def test_response_request_id_must_bind_to_invocation(tmp_path: Path) -> None:
    skeleton, impl = _assembled_runtime(tmp_path)
    impl.write_text(
        "from pathlib import Path\n"
        "class UserInputError(ValueError): pass\n"
        "def extract(input_path: Path) -> str: return input_path.read_text().upper()\n",
        encoding="utf-8",
    )
    server = skeleton / "src" / "sidecar_demo" / "sidecar_server.py"
    server.write_text(
        server.read_text(encoding="utf-8").replace(
            '"request_id": request_id,\n            "stdout": result,',
            '"request_id": "wrong-request",\n            "stdout": result,',
        ),
        encoding="utf-8",
    )
    source = tmp_path / "source.txt"
    source.write_text("anything", encoding="utf-8")
    result = _run(skeleton, source)
    assert result.returncode == 2
    assert "request binding mismatch" in result.stderr


def test_response_size_limit_maps_to_internal_error(tmp_path: Path) -> None:
    skeleton, impl = _assembled_runtime(tmp_path)
    package = skeleton / "src" / "sidecar_demo"
    server = package / "sidecar_server.py"
    server.write_text(
        server.read_text(encoding="utf-8").replace(
            "MAX_RESPONSE_CHARS = 16 * 1024 * 1024", "MAX_RESPONSE_CHARS = 32"
        ),
        encoding="utf-8",
    )
    impl.write_text(
        "from pathlib import Path\n"
        "class UserInputError(ValueError): pass\n"
        "def extract(input_path: Path) -> str: return 'x' * 64\n",
        encoding="utf-8",
    )
    source = tmp_path / "source.txt"
    source.write_text("anything", encoding="utf-8")
    result = _run(skeleton, source)
    assert result.returncode == 2
    assert "RESPONSE_TOO_LARGE" in result.stderr

    skeleton, impl = _assembled_runtime(tmp_path / "envelope")
    package = skeleton / "src" / "sidecar_demo"
    impl.write_text(
        "from pathlib import Path\n"
        "class UserInputError(ValueError): pass\n"
        "def extract(input_path: Path) -> str: return 'x' * 256\n",
        encoding="utf-8",
    )
    supervisor = package / "sidecar_supervisor.py"
    supervisor.write_text(
        supervisor.read_text(encoding="utf-8").replace(
            "MAX_ENVELOPE_BYTES = 20 * 1024 * 1024", "MAX_ENVELOPE_BYTES = 64"
        ),
        encoding="utf-8",
    )
    source = tmp_path / "envelope" / "source.txt"
    source.write_text("anything", encoding="utf-8")
    result = _run(skeleton, source)
    assert result.returncode == 2
    assert "response envelope too large" in result.stderr


def test_managed_sidecar_mcp_stays_blocked_while_trust_is_pending(
    tmp_path: Path,
) -> None:
    skeleton, impl = _assembled_runtime(tmp_path / "build")
    managed_root = tmp_path / "installed"
    tool_dir = managed_root / "sidecar-demo"
    shutil.copytree(skeleton, tool_dir)
    impl = tool_dir / "src" / "sidecar_demo" / "impl.py"
    impl.write_text(
        "from pathlib import Path\n"
        "class UserInputError(ValueError): pass\n"
        "def extract(input_path: Path) -> str: return input_path.read_text().upper()\n",
        encoding="utf-8",
    )
    interpreter = tool_dir / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8"
    )
    interpreter.chmod(0o755)

    manifest_path = tool_dir / "tool.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["verification"] = {
        "verdict": "VERIFIED_TOOL_READY",
        "run_id": "sidecar-demo-run-1",
        "contract_sha256": "a" * 64,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    evidence = tool_dir / "evidence"
    evidence.mkdir()
    (evidence / "provenance.json").write_text(
        json.dumps(
            {
                "tool": "sidecar-demo",
                "task_id": "tool-sidecar-demo-v1",
                "run_id": "sidecar-demo-run-1",
                "tool_contract_sha256": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
    append_release_decision(
        managed_root,
        tool="sidecar-demo",
        task_id="tool-sidecar-demo-v1",
        run_id="sidecar-demo-run-1",
        decision=ACTIVE,
        reason_code="FRESH_INPUT_PASS",
        reason="managed sidecar fixture passed fresh audit",
        evidence_sha256="b" * 64,
        decided_at="2026-08-24T00:00:00Z",
        actor="operator",
    )
    source = tmp_path / "input.txt"
    source.write_text("same-chain", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(tool_dir / "src")}

    direct_ok = subprocess.run(
        [str(tool_dir / "bin" / "sidecar-demo"), str(source)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert direct_ok.returncode == 0
    assert direct_ok.stdout == "SAME-CHAIN\n"
    with pytest.raises(RuntimeError, match="MANAGED_SIDECAR_TRUST_PENDING"):
        write_mcp_server(tool_dir)


def test_exported_runtime_runs_without_repo_runtime_or_credentials(
    tmp_path: Path,
) -> None:
    skeleton, impl = _assembled_runtime(tmp_path / "assembly")
    impl.write_text(
        "from pathlib import Path\n"
        "class UserInputError(ValueError): pass\n"
        "def extract(input_path: Path) -> str: return input_path.read_text().upper()\n",
        encoding="utf-8",
    )
    exported = tmp_path / "clean-export" / "sidecar-demo"
    shutil.copytree(skeleton, exported)
    source = tmp_path / "fresh.txt"
    source.write_text("clean replay", encoding="utf-8")
    clean_home = tmp_path / "clean-home"
    clean_home.mkdir()
    env = {
        "HOME": str(clean_home),
        "LANG": "C.UTF-8",
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(exported / "src"),
    }
    result = subprocess.run(
        [sys.executable, "-m", "sidecar_demo", str(source)],
        cwd=exported,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "CLEAN REPLAY\n"
    generated = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((exported / "src" / "sidecar_demo").glob("*.py"))
    )
    assert str(Path(__file__).resolve().parents[1]) not in generated
    assert "REPOPROOF_API_KEY" not in generated
    assert "receipt_signature" not in generated
