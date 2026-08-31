import hashlib
import os
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


def _run_case(tmp_path, example_id):
    source = _FIXTURES / example_id / "input"
    expected = _FIXTURES / example_id / "expected"
    output = tmp_path / f"{example_id}-output"
    process = subprocess.run(
        [_TOOL, str(source), "--out-dir", str(output)],
        capture_output=True, text=True, timeout=120,
    )
    assert process.returncode == 0, process.stderr
    assert output.is_dir()
    assert _tree_sha(output) == _tree_sha(expected)
    return output

def test_example_1(tmp_path):
    _run_case(tmp_path, 'web-service')

def test_example_2(tmp_path):
    _run_case(tmp_path, 'lab-notes')

def test_workspace_output_is_deterministic(tmp_path):
    first = _run_case(tmp_path / 'one', 'web-service')
    second = _run_case(tmp_path / 'two', 'web-service')
    assert _tree_sha(first) == _tree_sha(second)

def test_workspace_runtime_smoke(tmp_path):
    workspace = _run_case(tmp_path, 'web-service')
    argv = [str(workspace / 'project/run_tests.py'), *[]]
    process = subprocess.run(
        argv, cwd=workspace, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=120,
    )
    assert process.returncode == 0, process.stderr

def test_held_example_1(tmp_path):
    _run_case(tmp_path, 'punctuated-title')
