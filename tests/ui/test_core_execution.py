"""M6 durable Product jobs and the Studio/Lab Core execution mutex."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from repoproof.execution.core_execution import (
    EXPECTED_ARTIFACT_MISSING,
    FAILED,
    INTERRUPTED,
    NONZERO_EXIT,
    RUNNING,
    STATE_INVALID,
    STATE_SCHEMA_VERSION,
    SUCCEEDED,
    WORKER_INTERRUPTED,
    CoreExecutionConflictError,
    core_execution_lease,
    core_lock_path,
    process_identity,
    process_matches,
)
from repoproof.ui.services import live_run, product_jobs


def _product_world(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    state_root = tmp_path / "ui-state"
    (root / "runs").mkdir(parents=True)
    monkeypatch.setattr(product_jobs, "_product_root", lambda: root)
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    return root, state_root


def _wait_product(timeout: float = 10) -> dict:
    deadline = time.monotonic() + timeout
    latest: dict | None = None
    while time.monotonic() < deadline:
        latest = product_jobs.product_job_state()
        if latest and latest.get("status") != RUNNING:
            return latest
        time.sleep(0.02)
    raise AssertionError(f"Product job did not finish: {latest}")


def _python_write(path: Path, *, delay: float = 0, exit_code: int = 0) -> list[str]:
    source = (
        "import sys,time; from pathlib import Path; "
        f"time.sleep({delay!r}); "
        "Path(sys.argv[1]).write_text('fresh', encoding='utf-8'); "
        f"raise SystemExit({exit_code})"
    )
    return [sys.executable, "-c", source, str(path)]


def test_product_job_state_v2_is_atomic_and_records_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root, state_root = _product_world(tmp_path, monkeypatch)
    artifact = tmp_path / "result.json"
    started = product_jobs._start_product_job(
        _python_write(artifact, delay=0.2),
        kind="tool-build",
        label="atomic build",
        expected_artifact=artifact,
    )
    assert started["ok"] and started["status"] == RUNNING

    state_path = state_root / product_jobs.PRODUCT_LOCK
    saw_running = False
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
        assert raw["schema_version"] == STATE_SCHEMA_VERSION
        assert raw["pid"] and raw["process_identity"]
        assert raw["job_id"] and raw["action"] == "tool-build"
        saw_running |= raw["status"] == RUNNING
        if raw["status"] != RUNNING:
            break
        time.sleep(0.01)
    state = _wait_product()
    assert saw_running
    assert state["status"] == SUCCEEDED
    assert state["exit_code"] == 0
    assert state["artifact_before"] is None
    assert state["artifact_after"]["sha256"]
    assert state["ok"] and state["finished"] and not state["alive"]
    assert not list(state_path.parent.glob(f".{state_path.name}.*.tmp"))


def test_terminal_job_binds_structured_result_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _product_world(tmp_path, monkeypatch)
    artifact = tmp_path / "tool.json"
    source = (
        "import json,sys; from pathlib import Path; "
        "Path(sys.argv[1]).write_text('tool', encoding='utf-8'); "
        "job_id=sys.argv[sys.argv.index('--job-id')+1]; "
        "result=Path(sys.argv[sys.argv.index('--result-json')+1]); "
        "result.write_text(json.dumps({'schema_version':1,'job_id':job_id,"
        "'action':'tool-build','ok':True}), encoding='utf-8')"
    )
    started = product_jobs._start_product_job(
        [sys.executable, "-c", source, str(artifact)],
        kind="tool-build",
        label="result binding",
        expected_artifact=artifact,
    )
    assert started["ok"]
    state = _wait_product()
    result_path = Path(state["result_json"])
    assert state["status"] == SUCCEEDED
    assert state["result_json_sha256"] == hashlib.sha256(
        result_path.read_bytes()
    ).hexdigest()
    assert product_jobs.product_job_action_result(state)["ok"] is True

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["ok"] = False
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    replaced = product_jobs.product_job_action_result(state)
    assert replaced["ok"] is False
    assert replaced["error_code"] == "ACTION_RESULT_HASH_MISMATCH"


def test_completed_durable_worker_is_reaped_by_long_lived_launcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal Studio job must not accumulate a zombie worker."""

    _product_world(tmp_path, monkeypatch)
    artifact = tmp_path / "reaped.json"
    started = product_jobs._start_product_job(
        _python_write(artifact),
        kind="tool-build",
        label="reaper probe",
        expected_artifact=artifact,
    )
    assert started["ok"]
    assert _wait_product()["status"] == SUCCEEDED

    deadline = time.monotonic() + 5
    worker_state = ""
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["ps", "-p", str(started["pid"]), "-o", "stat="],
            capture_output=True,
            text=True,
            check=False,
        )
        worker_state = result.stdout.strip()
        if result.returncode != 0 or not worker_state:
            break
        time.sleep(0.02)
    assert not worker_state, f"durable worker was not reaped: {worker_state}"


def test_nonzero_exit_never_succeeds_even_when_artifact_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _product_world(tmp_path, monkeypatch)
    artifact = tmp_path / "made-despite-error.json"
    assert product_jobs._start_product_job(
        _python_write(artifact, exit_code=7),
        kind="tool-build",
        label="failing build",
        expected_artifact=artifact,
    )["ok"]
    state = _wait_product()
    assert artifact.is_file()
    assert state["status"] == FAILED
    assert state["exit_code"] == 7
    assert state["error_code"] == NONZERO_EXIT
    assert state["artifact_after"] is not None
    assert state["ok"] is False


def test_exit_zero_without_expected_artifact_is_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fail-closed:声明了产物却没形成 → 退出码 0 也判失败(证明不了不算数)。"""
    _product_world(tmp_path, monkeypatch)
    assert product_jobs._start_product_job(
        [sys.executable, "-c", "raise SystemExit(0)"],
        kind="tool-build",
        label="empty build",
        expected_artifact=tmp_path / "missing.json",
    )["ok"]
    state = _wait_product()
    assert state["status"] == FAILED
    assert state["exit_code"] == 0
    assert state["error_code"] == EXPECTED_ARTIFACT_MISSING
    assert state["artifact_after"] is None
    assert "预期产物" in state["note"]


def test_missing_expectation_is_refused_at_spawn_not_after_the_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**漏给预期产物是调用方缺陷** —— 当场拒绝,别让人等完再吃假失败。

    判定器 fail-closed(上一条),所以调用方漏给 expected_artifact 时,
    任务会跑完整整几分钟再报"未形成预期产物"。2026-08-28 实录:续跑真发
    正是这样 —— 跑出 PASS_ADAPTED、工具已装进 ~/tools,界面却写"失败",
    用户据此判断"又失败了",而真相是它成功了。原来的参数化把 None 当成
    合法输入来钉,现在 None 在更早的地方就被拒,语义没弱化、位置更靠前。
    """
    _product_world(tmp_path, monkeypatch)
    got = product_jobs._start_product_job(
        [sys.executable, "-c", "raise SystemExit(0)"],
        kind="tool-build", label="empty build", expected_artifact=None)
    assert not got["ok"]
    assert "预期产物" in got["error"]


def test_worker_kill_becomes_interrupted_not_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _product_world(tmp_path, monkeypatch)
    artifact = tmp_path / "never.json"
    started = product_jobs._start_product_job(
        _python_write(artifact, delay=5),
        kind="tool-build",
        label="kill probe",
        expected_artifact=artifact,
    )
    assert started["ok"]
    state_path = product_jobs.ui_state_root() / product_jobs.PRODUCT_LOCK
    deadline = time.monotonic() + 5
    running: dict = {}
    while time.monotonic() < deadline:
        running = json.loads(state_path.read_text(encoding="utf-8"))
        if running.get("child_pid"):
            break
        time.sleep(0.01)
    assert running.get("child_pid") and running.get("child_process_identity")
    os.kill(started["pid"], signal.SIGKILL)
    state = _wait_product()
    assert state["status"] == INTERRUPTED
    assert state["error_code"] == WORKER_INTERRUPTED
    assert state["ok"] is False
    assert state["process_identity"]
    assert state["child_cleanup"] == "TERMINATED"
    assert not process_matches(
        state["child_pid"], state["child_process_identity"]
    )
    time.sleep(0.1)
    assert not artifact.exists()


def test_persisted_argv_is_redacted_but_actual_argv_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root, state_root = _product_world(tmp_path, monkeypatch)
    artifact = tmp_path / "redaction.json"
    argv = _python_write(artifact) + [
        "--api-keysecret123456",
        "super-secret-value",
        "ghp_abcdefghijklmno",
        "https://user:password@example.test/path",
        "-k",
        "another-secret",
    ]
    assert product_jobs._start_product_job(
        argv,
        kind="tool-build",
        label="redaction probe",
        expected_artifact=artifact,
    )["ok"]
    assert _wait_product()["status"] == SUCCEEDED
    raw = (state_root / product_jobs.PRODUCT_LOCK).read_text(encoding="utf-8")
    assert "super-secret-value" not in raw
    assert "ghp_abcdefghijklmno" not in raw
    assert "user:password" not in raw
    assert "another-secret" not in raw
    persisted = json.loads(raw)["argv"]
    assert persisted[0] == Path(sys.executable).name
    assert persisted.count("[REDACTED]") >= 6
    assert len(json.loads(raw)["argv_projection_sha256"]) == 64
    assert '"env"' not in raw


def test_studio_job_blocks_lab_run_with_shared_repo_mutex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, state_root = _product_world(tmp_path, monkeypatch)
    artifact = tmp_path / "studio-result.json"
    started = product_jobs._start_product_job(
        _python_write(artifact, delay=0.5),
        kind="tool-build",
        label="Studio build",
        expected_artifact=artifact,
    )
    assert started["ok"]
    core_lock = core_lock_path(root)
    assert core_lock.is_file()

    task_id = "tool-lock-probe-v1"
    contracts = root / "contracts"
    contracts.mkdir()
    (contracts / f"{task_id}.yaml").write_text("task_id: tool-lock-probe-v1\n")
    (contracts / f"{task_id}.package.json").write_text("{}\n")
    monkeypatch.setenv("REPOPROOF_API_KEY", "not-a-real-key")
    monkeypatch.setenv("REPOPROOF_API_BASE", "http://127.0.0.1:1")
    blocked = live_run.start_run(root, task_id)
    assert blocked["ok"] is False
    assert "已有 Core 任务" in blocked["error"]
    assert _wait_product()["status"] == SUCCEEDED
    deadline = time.monotonic() + 5
    while core_lock.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not core_lock.exists()


def test_studio_job_blocks_lab_sync_mutation_and_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, state_root = _product_world(tmp_path, monkeypatch)
    artifact = tmp_path / "studio-sync-result.json"
    assert product_jobs._start_product_job(
        _python_write(artifact, delay=0.5),
        kind="tool-build",
        label="Studio build",
        expected_artifact=artifact,
    )["ok"]

    with pytest.raises(CoreExecutionConflictError, match="已有 Core 任务"):
        with core_execution_lease(
            root,
            kind="lab-assemble-freeze",
            label="Lab assemble/freeze",
        ):
            raise AssertionError("contended Lab mutation must not start")

    run = root / "runs" / "completed-run"
    run.mkdir()
    blocked = live_run.export_bundle_for_run(root, run.name)
    assert blocked["ok"] is False
    assert "已有 Core 任务" in blocked["error"]
    assert _wait_product()["status"] == SUCCEEDED


@pytest.mark.parametrize("legacy_kind", ["lab", "product"])
def test_sync_mutation_respects_legacy_execution_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    legacy_kind: str,
) -> None:
    root, state_root = _product_world(tmp_path, monkeypatch)
    monkeypatch.setenv("REPOPROOF_UI_STATE_ROOT", str(state_root))
    path = (
        root / live_run.LOCK
        if legacy_kind == "lab"
        else state_root / product_jobs.PRODUCT_LOCK
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "pid": os.getpid()}))

    with pytest.raises(CoreExecutionConflictError, match="旧执行状态"):
        with core_execution_lease(
            root,
            kind="lab-assemble-freeze",
            label="must not start",
        ):
            raise AssertionError("legacy execution must block")
    assert not core_lock_path(root).exists()


def test_stale_core_lock_fails_closed_and_rejects_pid_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _state_root = _product_world(tmp_path, monkeypatch)
    lock = core_lock_path(root)
    identity = process_identity(os.getpid())
    assert identity is not None
    reused = {**identity, "start_token": f"{identity['start_token']}-old"}
    lock.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "job_id": "old-job",
                "lease_id": "old-lease",
                "kind": "lab-run",
                "label": "stale lab run",
                "pid": os.getpid(),
                "process_identity": reused,
            }
        ),
        encoding="utf-8",
    )
    blocked = product_jobs._start_product_job(
        [sys.executable, "-c", "raise SystemExit(0)"],
        kind="tool-build",
        label="must not launch",
        expected_artifact=tmp_path / "never-created.json",
    )
    assert blocked["ok"] is False
    assert "fail-closed" in blocked["error"]
    assert lock.is_file(), "stale mutex must not be silently deleted"
    assert not (tmp_path / "never-created.json").exists()


def test_invalid_product_state_has_stable_fail_closed_error_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root, state_root = _product_world(tmp_path, monkeypatch)
    state_root.mkdir()
    (state_root / product_jobs.PRODUCT_LOCK).write_text(
        "{not-json", encoding="utf-8"
    )
    state = product_jobs.product_job_state()
    assert state is not None
    assert state["status"] == INTERRUPTED
    assert state["error_code"] == STATE_INVALID
    assert state["ok"] is False


@pytest.mark.parametrize("tamper", ["exit_code", "artifact_after"])
def test_forged_succeeded_state_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    _root, state_root = _product_world(tmp_path, monkeypatch)
    artifact = tmp_path / "verified-artifact.json"
    assert product_jobs._start_product_job(
        _python_write(artifact),
        kind="tool-build",
        label="success before tamper",
        expected_artifact=artifact,
    )["ok"]
    assert _wait_product()["status"] == SUCCEEDED
    path = state_root / product_jobs.PRODUCT_LOCK
    state = json.loads(path.read_text(encoding="utf-8"))
    state[tamper] = 7 if tamper == "exit_code" else None
    path.write_text(json.dumps(state), encoding="utf-8")

    projected = product_jobs.product_job_state()
    assert projected is not None
    assert projected["status"] == INTERRUPTED
    assert projected["error_code"] == STATE_INVALID
    assert projected["ok"] is False


def test_state_symlink_is_never_followed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root, state_root = _product_world(tmp_path, monkeypatch)
    state_root.mkdir()
    outside = tmp_path / "outside-state.json"
    outside.write_text('{"schema_version":2,"status":"SUCCEEDED"}\n')
    (state_root / product_jobs.PRODUCT_LOCK).symlink_to(outside)

    projected = product_jobs.product_job_state()
    assert projected is not None
    assert projected["status"] == INTERRUPTED
    assert projected["error_code"] == STATE_INVALID
    assert outside.read_text() == '{"schema_version":2,"status":"SUCCEEDED"}\n'


def test_examples_symlink_cannot_escape_managed_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root, state_root = _product_world(tmp_path, monkeypatch)
    draft = state_root / "drafts" / "escape"
    draft.mkdir(parents=True)
    (draft / "draft.yaml").write_text("tool:\n  name: escape-tool\n")
    (draft / "reference_impl.py").write_text("def extract(path): return path\n")
    (draft / "examples.yaml").write_text("examples: []\n")
    outside = tmp_path / "outside-examples"
    outside.mkdir()
    (draft / "examples").symlink_to(outside, target_is_directory=True)

    added = product_jobs.add_golden_example(
        draft,
        input_name="input.txt",
        input_bytes=b"input",
        expected_name="expected.txt",
        expected_bytes=b"expected",
    )
    assert added["ok"] is False
    assert "样例目录" in added["error"]
    built = product_jobs.start_tool_build(
        draft_dir=draft,
        dest_root=tmp_path / "tools",
        rehearsal_only=True,
    )
    assert built["ok"] is False
    assert not list(outside.iterdir())


def test_live_v2_nonzero_report_never_projects_success(tmp_path: Path) -> None:
    task_id = "tool-failed-report-v1"
    run = tmp_path / "runs" / f"{task_id}-20260824-010101"
    run.mkdir(parents=True)
    (run / "report.json").write_text(
        '{"final_verdict":"PASS_ADAPTED"}\n', encoding="utf-8"
    )
    (tmp_path / live_run.LOCK).write_text(
        json.dumps(
                {
                    "schema_version": STATE_SCHEMA_VERSION,
                    "job_id": "failed-job",
                    "status": FAILED,
                    "kind": "lab-agent-run",
                    "action": "lab-agent-run",
                    "pid": 999999,
                    "process_identity": {
                        "pid": 999999,
                        "start_token": "dead",
                        "command_sha256": "0" * 64,
                    },
                    "exit_code": 7,
                    "argv": ["python", "-m", "repoproof.cli"],
                    "argv_projection_sha256": "0" * 64,
                    "error_code": NONZERO_EXIT,
                    "error": "命令退出码为 7",
                    "task_id": task_id,
                    "started_at": "20260824-010100",
                    "started_at_utc": "2026-08-24T01:01:00Z",
                    "finished_at": "2026-08-24T01:01:01Z",
                    "artifact_expectation": {
                        "kind": "glob",
                        "root": str(tmp_path),
                        "pattern": f"runs/{task_id}-2*/report.json",
                    },
                    "artifact_before": {"kind": "glob", "matches": []},
                    "artifact_after": {"kind": "glob", "matches": []},
                    "label": "failed lab run",
                }
        ),
        encoding="utf-8",
    )
    state = live_run.active_run(tmp_path)
    assert state is not None
    assert state["status"] == FAILED
    assert state["report_ready"] is False
    assert "verdict" not in state


def test_live_legacy_product_or_lab_state_blocks_v2_studio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, state_root = _product_world(tmp_path, monkeypatch)
    product_state = state_root / product_jobs.PRODUCT_LOCK
    state_root.mkdir()
    product_state.write_text(
        json.dumps({"schema_version": 1, "pid": os.getpid()}), encoding="utf-8"
    )
    monkeypatch.setenv("REPOPROOF_UI_STATE_ROOT", str(state_root))
    monkeypatch.setenv("REPOPROOF_API_KEY", "not-a-real-key")
    monkeypatch.setenv("REPOPROOF_API_BASE", "http://127.0.0.1:1")
    task_id = "legacy-product-blocks-lab-v1"
    contracts = root / "contracts"
    contracts.mkdir()
    (contracts / f"{task_id}.yaml").write_text(f"task_id: {task_id}\n")
    (contracts / f"{task_id}.package.json").write_text("{}\n")
    lab_blocked = live_run.start_run(root, task_id)
    assert lab_blocked["ok"] is False and "旧执行状态" in lab_blocked["error"]

    kwargs = {
        "kind": "tool-build",
        "label": "must not launch",
        "expected_artifact": tmp_path / "never.json",
    }
    blocked = product_jobs._start_product_job(
        [sys.executable, "-c", "raise SystemExit(0)"], **kwargs
    )
    assert blocked["ok"] is False and "旧执行状态" in blocked["error"]

    product_state.unlink()
    lab_state = root / live_run.LOCK
    lab_state.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    blocked = product_jobs._start_product_job(
        [sys.executable, "-c", "raise SystemExit(0)"], **kwargs
    )
    assert blocked["ok"] is False and "旧执行状态" in blocked["error"]
    assert not core_lock_path(root).exists()

    lab_state.write_text("{not-json", encoding="utf-8")
    lab_blocked = live_run.start_run(root, task_id)
    assert lab_blocked["ok"] is False
    assert "旧执行状态损坏" in lab_blocked["error"]
    assert not core_lock_path(root).exists()


def test_rehearsal_expected_artifact_uses_assembler_version_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, state_root = _product_world(tmp_path, monkeypatch)
    contracts = root / "contracts"
    contracts.mkdir()
    (contracts / "tool-alpha-tool-v1.yaml").write_text(
        "historical: frozen\n", encoding="utf-8"
    )
    draft_dir = state_root / "drafts" / "draft"
    draft_dir.mkdir(parents=True)
    (draft_dir / "draft.yaml").write_text(
        yaml.safe_dump(
            {
                "task_id": "tool-alpha-tool-v1",
                "tool": {"name": "alpha-tool"},
            }
        ),
        encoding="utf-8",
    )
    (draft_dir / "reference_impl.py").write_text("def extract(path): return path\n")
    (draft_dir / "examples.yaml").write_text("examples: []\n")
    (draft_dir / "examples").mkdir()
    captured: dict = {}

    def _capture(_argv: list[str], **kwargs: object) -> dict:
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(product_jobs, "_start_product_job", _capture)
    monkeypatch.setattr(
        product_jobs,
        "_core_draft_readiness",
        lambda *_args, **_kwargs: SimpleNamespace(ready=True),
    )
    result = product_jobs.start_tool_build(
        draft_dir=draft_dir,
        dest_root=tmp_path / "tools",
        rehearsal_only=True,
    )
    assert result["ok"]
    assert captured["expected_artifact"] == (
        contracts / "tool-alpha-tool-v2.yaml"
    )
    assert captured["metadata"]["journey_stage"] == 3


def test_frozen_task_can_resume_zero_model_rehearsal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, state_root = _product_world(tmp_path, monkeypatch)
    task_id = "tool-alpha-tool-v1"
    contracts = root / "contracts"
    contracts.mkdir()
    (contracts / f"{task_id}.yaml").write_text(
        "tool:\n  name: alpha-tool\n", encoding="utf-8"
    )
    captured: dict = {}

    def _capture(argv: list[str], **kwargs: object) -> dict:
        captured["argv"] = argv
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(product_jobs, "_start_product_job", _capture)
    result = product_jobs.start_tool_build_real(
        task_id,
        tmp_path / "tools",
        rehearsal_only=True,
    )

    assert result["ok"]
    assert "--rehearsal-only" in captured["argv"]
    assert captured["expected_artifact"] is None
    assert captured["expected_action_result"] is True
    assert captured["metadata"]["journey_stage"] == 3

    draft = state_root / "drafts" / "alpha"
    draft.mkdir(parents=True)
    (draft / "draft.yaml").write_text("tool: {name: alpha-tool}\n")
    (draft / "reference_impl.py").write_text(
        "def extract(path):\n    return path.read_text()\n",
        encoding="utf-8",
    )
    (draft / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    (draft / "examples").mkdir()
    captured.clear()
    result = product_jobs.start_tool_build_real(
        task_id,
        tmp_path / "tools",
        rehearsal_only=True,
        draft_dir=draft,
    )
    assert result["ok"]
    assert "--draft-dir" in captured["argv"]
    assert str(draft) in captured["argv"]

    captured.clear()
    result = product_jobs.start_tool_build_real(
        task_id,
        tmp_path / "tools",
        rehearsal_only=False,
    )
    assert result["ok"]
    assert "--rehearsal-only" not in captured["argv"]
    assert captured["metadata"]["journey_stage"] == 4
