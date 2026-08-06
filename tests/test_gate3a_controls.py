"""Gate 3A — oracle calibration controls + admission negatives.

Positive control (trusted reference adapter) must PASS the v3 oracle;
three cheating negative controls must FAIL it for semantic reasons.
Container-backed tests skip when no docker daemon is reachable.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from repoproof.domain.models import AdmissionError, Budgets, SourceRepo
from repoproof.execution.docker_backend import DockerExecutionBackend
from repoproof.harness.wheelhouse import compute_manifest, select_wheel, verify_wheelhouse
from repoproof.verification.junit import check_test_completion, parse_junit_xml

REPO = Path(__file__).resolve().parent.parent
UPSTREAM = REPO / "upstream-cache" / "upstream-0a6baea1a42c"
WHEELHOUSE = REPO / "upstream-cache" / "wheelhouse-0a6baea1a42c"
ORACLE_V3 = REPO / "oracle" / "adopt-chonkie-local-chunking-v3"
CONSUMER = REPO / "fixtures" / "consumer_rag"
USER = f"{os.getuid()}:{os.getgid()}"

docker_ok, _ = DockerExecutionBackend.available()
needs_docker = pytest.mark.skipif(
    not (docker_ok and UPSTREAM.exists() and WHEELHOUSE.exists()),
    reason="docker daemon or pinned caches unavailable",
)


def _run_control(adapter_dir: Path) -> dict:
    from repoproof.runner.calibration import run_oracle_with_adapter

    return run_oracle_with_adapter(
        project_root=REPO,
        upstream=UPSTREAM,
        wheelhouse=WHEELHOUSE,
        oracle_dir=ORACLE_V3,
        adapter_dir=adapter_dir,
        consumer_dir=CONSUMER,
        user=USER,
    )


@needs_docker
def test_positive_control_reference_adapter_passes() -> None:
    result = _run_control(REPO / "tests" / "calibration")
    assert result["exit_code"] == 0, result.get("stdout_tail")
    assert result["totals"]["tests"] == 33
    assert result["totals"]["failures"] == 0 and result["totals"]["errors"] == 0


@needs_docker
def test_negative_control_1_one_block_passthrough_fails() -> None:
    result = _run_control(REPO / "fixtures" / "negative_control_adapter")
    assert result["exit_code"] != 0
    failed = {n["node_id"] for n in result.get("nodes", []) if n["outcome"] != "passed"}
    assert any("test_boundaries_match_chonkie_reference" in n for n in failed)


@needs_docker
def test_negative_control_2_fixed_slicer_fails() -> None:
    result = _run_control(REPO / "fixtures" / "negative_control_slicer")
    assert result["exit_code"] != 0
    failed = {n["node_id"] for n in result.get("nodes", []) if n["outcome"] != "passed"}
    assert any("test_boundaries_match_chonkie_reference" in n for n in failed)
    assert any("test_strategies_differ_on_run_on_document" in n for n in failed)


@needs_docker
def test_negative_control_3_wrong_strategy_fails() -> None:
    result = _run_control(REPO / "fixtures" / "negative_control_wrong_strategy")
    assert result["exit_code"] != 0
    failed = {n["node_id"] for n in result.get("nodes", []) if n["outcome"] != "passed"}
    # sentence requests match; recursive requests must diverge on the
    # strategy-sensitive fixtures.
    assert any("recursive" in n and "test_boundaries_match_chonkie_reference" in n for n in failed)


def test_reference_adapter_not_leaked() -> None:
    """The trusted reference adapter must never reach agent-visible or
    deliverable locations."""
    ref = (REPO / "tests" / "calibration" / "adapter.py").read_text(encoding="utf-8")
    marker = "POSITIVE CONTROL"
    assert marker in ref
    for forbidden_root in (REPO / "fixtures" / "consumer_rag", REPO / "src"):
        for p in forbidden_root.rglob("*.py"):
            assert marker not in p.read_text(encoding="utf-8", errors="replace"), f"leaked into {p}"


# ---------------- test-completion manifest negatives (C) ----------------

GOOD_XML = b"""<testsuites><testsuite tests="2" failures="0" errors="0" skipped="0">
<testcase classname="test_capability" name="test_a"/><testcase classname="test_capability" name="test_b"/>
</testsuite></testsuites>"""


def test_completion_rejects_missing_and_corrupt_junit() -> None:
    exp = ["test_capability::test_a", "test_capability::test_b"]
    assert not check_test_completion(exit_code=0, junit=parse_junit_xml(None), expected_node_ids=exp).ok
    assert not check_test_completion(
        exit_code=0, junit=parse_junit_xml(b"<not-xml"), expected_node_ids=exp
    ).ok


def test_completion_rejects_skips_missing_extra_and_count_mismatch() -> None:
    exp = ["test_capability::test_a", "test_capability::test_b"]
    ok = check_test_completion(exit_code=0, junit=parse_junit_xml(GOOD_XML), expected_node_ids=exp)
    assert ok.ok

    skipped = GOOD_XML.replace(
        b'<testcase classname="test_capability" name="test_b"/>',
        b'<testcase classname="test_capability" name="test_b"><skipped/></testcase>',
    ).replace(b'skipped="0"', b'skipped="1"')
    r = check_test_completion(exit_code=0, junit=parse_junit_xml(skipped), expected_node_ids=exp)
    assert not r.ok and "skipped" in r.detail

    missing_one = check_test_completion(
        exit_code=0,
        junit=parse_junit_xml(GOOD_XML),
        expected_node_ids=exp + ["test_capability::test_c"],
    )
    assert not missing_one.ok and missing_one.extra["missing_nodes"]

    extra_unknown = check_test_completion(
        exit_code=0, junit=parse_junit_xml(GOOD_XML), expected_node_ids=["test_capability::test_a"]
    )
    assert not extra_unknown.ok and extra_unknown.extra["extra_nodes"]


def test_completion_rejects_os_exit_cheat(tmp_path: Path) -> None:
    """An adapter that os._exit(0)s during import kills pytest with rc=0
    and NO junit — the completion check must fail on the missing junit."""
    adapter = tmp_path / "adapter.py"
    adapter.write_text("import os\nos._exit(0)\n")
    test = tmp_path / "test_cheat.py"
    test.write_text(
        "import importlib.util, os\n"
        "spec = importlib.util.spec_from_file_location('a', os.environ['CHEAT_ADAPTER'])\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        "def test_never_runs():\n    assert True\n"
    )
    junit_path = tmp_path / "junit.xml"
    env = os.environ.copy()
    env["CHEAT_ADAPTER"] = str(adapter)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(test), f"--junitxml={junit_path}"],
        capture_output=True,
        env=env,
        timeout=120,
    )
    data = junit_path.read_bytes() if junit_path.exists() else None
    r = check_test_completion(
        exit_code=proc.returncode,
        junit=parse_junit_xml(data),
        expected_node_ids=["test_cheat::test_never_runs"],
    )
    assert not r.ok, "os._exit(0) cheat must not satisfy the completion check"


# ---------------- source & wheelhouse admission negatives (D) ----------------


def _mk_wheelhouse(tmp_path: Path) -> tuple[Path, dict]:
    wh = tmp_path / "wh"
    wh.mkdir()
    (wh / "pkg_a-1.0-py3-none-any.whl").write_bytes(b"wheel-a")
    (wh / "pkg_b-2.0-py3-none-any.whl").write_bytes(b"wheel-b")
    return wh, compute_manifest(wh)


def test_wheelhouse_admission_negatives(tmp_path: Path) -> None:
    wh, manifest = _mk_wheelhouse(tmp_path)
    verify_wheelhouse(wh, expected_wheels=manifest["wheels"], expected_root=manifest["root"])

    (wh / "extra-9.9-py3-none-any.whl").write_bytes(b"sneaky")
    with pytest.raises(AdmissionError, match="unexpected wheel"):
        verify_wheelhouse(wh, expected_wheels=manifest["wheels"], expected_root=manifest["root"])
    (wh / "extra-9.9-py3-none-any.whl").unlink()

    (wh / "pkg_a-1.0-py3-none-any.whl").write_bytes(b"tampered")
    with pytest.raises(AdmissionError, match="hash mismatch"):
        verify_wheelhouse(wh, expected_wheels=manifest["wheels"], expected_root=manifest["root"])
    (wh / "pkg_a-1.0-py3-none-any.whl").write_bytes(b"wheel-a")

    (wh / "pkg_b-2.0-py3-none-any.whl").unlink()
    with pytest.raises(AdmissionError, match="missing wheel"):
        verify_wheelhouse(wh, expected_wheels=manifest["wheels"], expected_root=manifest["root"])


def test_select_wheel_exact() -> None:
    wheels = {"chonkie-1.7.0-py3-none-any.whl": "aa", "chonkie_core-0.10.2-x.whl": "bb"}
    name, sha = select_wheel(wheels, "chonkie")
    assert name == "chonkie-1.7.0-py3-none-any.whl" and sha == "aa"
    with pytest.raises(AdmissionError):
        select_wheel({}, "chonkie")


def test_dirty_upstream_admission_fail(tmp_path: Path) -> None:
    from repoproof.runner.baseline import ensure_upstream

    up = tmp_path / "upstream-src"
    up.mkdir()
    (up / "a.py").write_text("X = 1\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=up, check=True)
    subprocess.run(["git", "add", "-A"], cwd=up, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"],
        cwd=up,
        check=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=up, capture_output=True, text=True, check=True
    ).stdout.strip()
    cache = tmp_path / "cache"
    dest = cache / f"upstream-{commit[:12]}"
    dest.parent.mkdir(parents=True)
    subprocess.run(["git", "clone", "-q", str(up), str(dest)], check=True)
    subprocess.run(["git", "-C", str(dest), "checkout", "-q", commit], check=True)
    (dest / "untracked_pollution.txt").write_text("dirty\n")
    src = SourceRepo(url=str(up), revision="main", resolved_commit=commit, license="MIT")
    with pytest.raises(AdmissionError, match="not clean"):
        ensure_upstream(cache, src)


def test_patch_budget_defaults_still_frozen() -> None:
    b = Budgets()
    assert (b.max_patch_files, b.max_patch_lines) == (8, 400)


def test_collection_manifest_frozen_counts() -> None:
    coll = json.loads((REPO / "contracts" / "adopt-chonkie-local-chunking-v3.collection.json").read_text())
    assert len(coll["capability_nodes"]) == 33
    assert len(coll["regression_nodes"]) == 4
    assert all(n.startswith("test_capability::") for n in coll["capability_nodes"])
