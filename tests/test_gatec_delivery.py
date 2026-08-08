"""Gate C(RFC-008)— 期望草稿 / Staging / ApplyManifest / Integration Bundle。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from repoproof.adoption.delivery.apply_manifest import (
    RESULT_EXPORT_READY,
    build_apply_manifest,
)
from repoproof.adoption.delivery.expectation_draft import (
    BOUNDARY,
    ERROR,
    HOST_SCHEMA,
    NORMAL,
    SUGGESTED_NEW,
    UNCERTAIN,
    UPSTREAM_NATIVE,
    DraftNotConfirmed,
    build_expectation_draft,
)
from repoproof.adoption.delivery.integration_bundle import BundleError, export_bundle
from repoproof.adoption.delivery.staging import (
    StagingError,
    create_staging,
    detect_drift,
    remove_staging,
)

REPO = Path(__file__).resolve().parent.parent


def _probe(mapping: dict[str, tuple[str | None, str | None]]):
    return lambda text: mapping.get(text, (None, "no probe result"))


def _draft(**overrides):
    inputs = [
        {"input": "正常输入", "case_kind": NORMAL},
        {"input": "", "case_kind": BOUNDARY},
        {"input": "坏输入", "case_kind": ERROR},
    ]
    probe = _probe({
        "正常输入": ("DocumentResult(title=x)", None),
        "": ("[]", None),
        "坏输入": (None, "ValueError: bad input"),
    })
    kw = dict(goal="接入解析能力", upstream_ref="demo@abc123",
              inputs=inputs, probe=probe,
              host_schema_names=["DocumentResult (pydantic)"])
    kw.update(overrides)
    return build_expectation_draft(**kw)


# ---------- 期望草稿(§八) ----------

def test_upstream_output_is_evidence_not_expectation() -> None:
    """未确认 → to_examples 必须拒绝:上游输出不能自动变成期望。"""
    d = _draft()
    assert d.cases[0].upstream_output == "DocumentResult(title=x)"
    with pytest.raises(DraftNotConfirmed, match="未经你确认"):
        d.to_examples()


def test_field_origin_marking() -> None:
    d = _draft()
    assert d.cases[0].field_origin == HOST_SCHEMA        # 命中宿主 Schema 名
    assert d.cases[1].field_origin == UPSTREAM_NATIVE    # 纯上游输出
    assert d.cases[2].field_origin == SUGGESTED_NEW      # 错误输入需定义包装行为
    assert d.cases[2].candidate_expected == ""           # 预期异常必须用户给出


def test_missing_error_case_blocks_freeze() -> None:
    d = build_expectation_draft(
        goal="g", upstream_ref="r",
        inputs=[{"input": "a", "case_kind": NORMAL},
                {"input": "b", "case_kind": BOUNDARY}],
        probe=_probe({"a": ("out-a", None), "b": ("out-b", None)}))
    for c in d.cases:
        c.user_confirmed = True
    d.user_reviewed_upstream_evidence = True
    with pytest.raises(DraftNotConfirmed, match="error"):
        d.to_examples()


def test_confirmed_draft_exports_examples() -> None:
    d = _draft()
    d.cases[0].candidate_expected = "contains:DocumentResult"
    d.cases[2].candidate_expected = "contains:输入不合法"
    for c in d.cases:
        c.user_confirmed = True
    d.user_reviewed_upstream_evidence = True
    exs = d.to_examples()
    assert exs[0] == {"input": "正常输入", "expected": "contains:DocumentResult"}
    assert len(exs) == 3


def test_review_ack_required_even_if_all_confirmed() -> None:
    d = _draft()
    d.cases[2].candidate_expected = "contains:异常"
    for c in d.cases:
        c.user_confirmed = True
    with pytest.raises(DraftNotConfirmed, match="核对上游实际输出"):
        d.to_examples()


def test_probe_failure_yields_uncertain_and_soft() -> None:
    d = build_expectation_draft(
        goal="g", upstream_ref="r",
        inputs=[{"input": "x", "case_kind": NORMAL}],
        probe=_probe({}))
    assert d.cases[0].field_origin == UNCERTAIN and d.cases[0].candidate_expected == ""


def test_probe_from_baseline_junit_extracts_real_outputs() -> None:
    """Upstream Calibration 真实来源:直连基线 JUnit 的「实际: …」片段。"""
    from repoproof.adoption.delivery.expectation_draft import probe_from_baseline_junit

    nodes = [
        {"node_id": "public_tests/test_public_contract.py::test_example_1",
         "outcome": "failed", "message": "期望包含 'X',实际: 上游真实输出A"},
        {"node_id": "public_tests/test_public_contract.py::test_example_2",
         "outcome": "passed", "message": ""},
        {"node_id": "public_tests/test_public_contract.py::test_example_3",
         "outcome": "error", "message": "ModuleNotFoundError: no module named demo"},
    ]
    examples = [{"input": "甲", "expected": "contains:X"},
                {"input": "乙", "expected": "contains:Y"},
                {"input": "丙", "expected": "contains:Z"}]
    probe = probe_from_baseline_junit(nodes, examples)
    assert probe("甲") == ("上游真实输出A", None)
    assert probe("乙") == ("contains:Y", None)          # 直连已通过:期望即被满足
    out, err = probe("丙")
    assert out is None and "ModuleNotFoundError" in err
    assert probe("不存在")[1] == "no probe result"


# ---------- Staging(§9.2) ----------

def _make_project(root: Path, git: bool = False) -> Path:
    proj = root / "proj"
    proj.mkdir()
    (proj / "app.py").write_text("print('v1')\n", encoding="utf-8")
    (proj / "data.txt").write_text("keep\n", encoding="utf-8")
    if git:
        for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                    ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                     "commit", "-qm", "init"]):
            subprocess.run(cmd, cwd=proj, check=True, capture_output=True, timeout=30)
    return proj


def test_staging_git_worktree_mode(tmp_path: Path) -> None:
    proj = _make_project(tmp_path, git=True)
    info = create_staging(proj, tmp_path / "stg")
    try:
        assert info.mode == "git_worktree" and len(info.base_git_commit) == 40
        staged = Path(info.staging_path)
        assert (staged / "app.py").read_text() == "print('v1')\n"
        # 改 staging 不影响原项目
        (staged / "app.py").write_text("print('v2')\n", encoding="utf-8")
        assert (proj / "app.py").read_text() == "print('v1')\n"
        assert detect_drift(info) is False
        (proj / "new.txt").write_text("drift", encoding="utf-8")
        assert detect_drift(info) is True
    finally:
        remove_staging(info)
    assert not Path(info.staging_path).exists()


def test_staging_copy_mode_records_hashes(tmp_path: Path) -> None:
    proj = _make_project(tmp_path, git=False)
    info = create_staging(proj, tmp_path / "stg")
    assert info.mode == "full_copy"
    assert set(info.file_hashes) == {"app.py", "data.txt"}
    assert detect_drift(info) is False
    remove_staging(info)


def test_staging_refuses_existing_dir(tmp_path: Path) -> None:
    proj = _make_project(tmp_path)
    (tmp_path / "stg" / f"staging-{proj.name}").mkdir(parents=True)
    with pytest.raises(StagingError, match="不覆盖"):
        create_staging(proj, tmp_path / "stg")


# ---------- ApplyManifest(§9.4) ----------

def test_apply_manifest_diff_and_rollback(tmp_path: Path) -> None:
    orig = _make_project(tmp_path)
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "app.py").write_text("print('v2')\n", encoding="utf-8")   # modified
    (staged / "adapter.py").write_text("def run(): ...\n", encoding="utf-8")  # created
    # data.txt 在 staged 中不存在 → 记录为 deleted,但不生成删除动作
    m = build_apply_manifest(orig, staged, base_git_commit="c" * 40)
    assert m.files_created == ["adapter.py"]
    assert m.files_modified == ["app.py"]
    assert m.files_deleted == ["data.txt"]
    assert "app.py" in m.before_hashes and "adapter.py" in m.after_hashes
    kinds = {(a.kind, a.path) for a in m.rollback_actions}
    assert ("delete_created", "adapter.py") in kinds
    assert ("restore_preimage", "app.py") in kinds
    # 铁律:不存在任何针对 data.txt(用户文件)的删除/恢复动作
    assert not any(a.path == "data.txt" for a in m.rollback_actions)
    assert m.result_state == RESULT_EXPORT_READY


# ---------- Integration Bundle(§9.1) ----------

def _fake_run(tmp_path: Path, verdict: str = "PASS_ADAPTED", with_adapter: bool = True) -> Path:
    run = tmp_path / "runs" / "adopt-demo-guided-v1-20260101-000000"
    (run / "adaptation").mkdir(parents=True)
    if with_adapter:
        (run / "adaptation" / "adapter.py").write_text("def run(v): return v\n", encoding="utf-8")
    (run / "adaptation_manifest.json").write_text("{}", encoding="utf-8")
    (run / "report.json").write_text(json.dumps({
        "task_id": "adopt-demo-guided-v1", "final_verdict": verdict,
        "capability": {"passed_checks": 5, "failed_checks": 0, "total_checks": 5},
        "regression": {"passed_checks": 2, "failed_checks": 0, "total_checks": 2},
        "policy": {"status": "PASS"},
        "agent": {"exit_status": "Submitted", "model_call_count": 9},
        "gate_reasons": ["capability PASS", "replay clean_adoption PASS"],
        "image_digest": "sha256:deadbeef", "contract_sha256": "ab" * 32,
    }), encoding="utf-8")
    return run


def _fake_project_root(tmp_path: Path) -> Path:
    root = tmp_path
    (root / "contracts").mkdir(exist_ok=True)
    (root / "contracts" / "adopt-demo-guided-v1.yaml").write_text(
        "task_id: adopt-demo-guided-v1\ntarget_project:\n  kind: consumer_fixture\n"
        "  path: fixtures/assembled_demo\n", encoding="utf-8")
    (root / "contracts" / "adopt-demo-guided-v1.package.json").write_text(json.dumps(
        {"distribution": "demo", "source_repo": {"resolved_commit": "f" * 40}}),
        encoding="utf-8")
    pub = root / "fixtures" / "assembled_demo" / "public_tests"
    pub.mkdir(parents=True)
    (pub / "test_public_contract.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    # held-out 所在的 oracle 目录:绝不允许进 bundle
    orc = root / "oracle" / "adopt-demo-guided-v1"
    orc.mkdir(parents=True)
    (orc / "test_capability.py").write_text(
        "def test_held_example_1(): assert run('secret') == 'hidden'\n", encoding="utf-8")
    (orc / "fixtures").mkdir()
    (orc / "fixtures" / "held_out_documents.json").write_text("{}", encoding="utf-8")
    return root


def test_bundle_layout_and_heldout_exclusion(tmp_path: Path) -> None:
    root = _fake_project_root(tmp_path)
    run = _fake_run(tmp_path)
    out = export_bundle(root, run)
    b = Path(out["bundle_dir"])
    for rel in ("adapter/adapter.py", "patches/adaptation_manifest.json",
                "dependencies/DEPENDENCIES.md", "tests/public_tests/test_public_contract.py",
                "runtime/adopt-demo-guided-v1.yaml", "integration_guide.md",
                "apply_manifest.json", "rollback_plan.md", "report.md",
                "bundle_manifest.json"):
        assert (b / rel).exists(), rel
    dumped = "\n".join(str(p.relative_to(b)) for p in b.rglob("*"))
    assert "held_out" not in dumped and "test_capability" not in dumped
    manifest = json.loads((b / "bundle_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "EXPORT_READY" and manifest["verdict"] == "PASS_ADAPTED"
    # manifest 哈希可独立复核
    import hashlib
    for rel, digest in manifest["files"].items():
        assert hashlib.sha256((b / rel).read_bytes()).hexdigest() == digest


def test_symlink_into_oracle_never_leaks(tmp_path: Path) -> None:
    """独立验证反例:公开测试目录里指向 oracle 的符号链接曾被解引用,
    把 held-out 内容拷进结果包。现在既不跟随链接,导出后还做内容扫描。"""
    root = _fake_project_root(tmp_path)
    run = _fake_run(tmp_path)
    held = root / "oracle" / "adopt-demo-guided-v1" / "fixtures" / "held_out_documents.json"
    held.write_text('{"secret_case": "hidden expected value"}', encoding="utf-8")
    (root / "fixtures" / "assembled_demo" / "public_tests" / "sneaky.json").symlink_to(held)
    out = export_bundle(root, run)
    b = Path(out["bundle_dir"])
    blob = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                     for p in b.rglob("*") if p.is_file())
    assert "hidden expected value" not in blob
    assert (b / "tests" / "public_tests" / "sneaky.json.SKIPPED_SYMLINK.txt").exists()


def test_direct_oracle_copy_aborts_export(tmp_path: Path) -> None:
    """兜底扫描:若某条路径把 oracle 文件真拷进包,导出必须中止并清理。"""
    import shutil as _sh

    from repoproof.adoption.delivery import integration_bundle as ib

    root = _fake_project_root(tmp_path)
    run = _fake_run(tmp_path)
    held = root / "oracle" / "adopt-demo-guided-v1" / "fixtures" / "held_out_documents.json"
    held.write_text('{"secret_case": "hidden expected value for held-out"}', encoding="utf-8")
    # 模拟一条被绕过的拷贝路径:adaptation 中混入 oracle 文件副本
    _sh.copy2(held, run / "adaptation" / "copied_oracle.json")
    dest = tmp_path / "leaky_bundle"
    with pytest.raises(ib.BundleError, match="隐藏验收内容"):
        export_bundle(root, run, dest)
    assert not dest.exists()  # 中止即清理,不留半成品


def test_real_flat_report_shape_exports(tmp_path: Path) -> None:
    """反例(真实演练发现):真实 runner 的 report.json 把 capability/
    regression/policy 写成扁平字符串、调用数键名是 model_calls——
    fixture 曾只按 dict 形态测,导致真实 PASS 运行导出当场崩溃。"""
    root = _fake_project_root(tmp_path)
    run = _fake_run(tmp_path)
    (run / "report.json").write_text(json.dumps({
        "task_id": "adopt-demo-guided-v1", "final_verdict": "PASS_ADAPTED",
        "capability": "passed_checks=5, failed_checks=0, total_checks=5; all frozen nodes ran",
        "regression": "passed_checks=3, failed_checks=0, total_checks=3",
        "policy": "oracle/upstream intact; action causality holds",
        "agent": {"exit_status": "Submitted", "model_calls": 7},
        "gate_reasons": ["capability PASS"],
    }), encoding="utf-8")
    out = export_bundle(root, run)
    text = (Path(out["bundle_dir"]) / "report.md").read_text(encoding="utf-8")
    assert "5/5" in text and "3/3" in text
    assert "Submitted(调用 7 次)" in text
    assert "oracle/upstream intact" in text


def test_fail_run_exports_too(tmp_path: Path) -> None:
    """§十三-9:FAIL/BLOCKED 也必须返回当前产物和报告。"""
    root = _fake_project_root(tmp_path)
    run = _fake_run(tmp_path, verdict="FAIL", with_adapter=False)
    out = export_bundle(root, run)
    b = Path(out["bundle_dir"])
    assert (b / "report.md").exists()
    assert "FAIL" in (b / "report.md").read_text(encoding="utf-8")
    assert "诚实失败" in (b / "integration_guide.md").read_text(encoding="utf-8")


def test_bundle_refuses_nonempty_dest(tmp_path: Path) -> None:
    root = _fake_project_root(tmp_path)
    run = _fake_run(tmp_path)
    dest = tmp_path / "occupied"
    dest.mkdir()
    (dest / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(BundleError, match="拒绝覆盖"):
        export_bundle(root, run, dest)
    assert (dest / "keep.txt").exists()


def test_bundle_requires_finished_run(tmp_path: Path) -> None:
    root = _fake_project_root(tmp_path)
    run = tmp_path / "runs" / "incomplete-run"
    run.mkdir(parents=True)
    with pytest.raises(BundleError, match="不完整"):
        export_bundle(root, run)


def test_bundle_never_touches_user_project(tmp_path: Path) -> None:
    """EXPORT_ONLY:导出前后,仓库外「用户项目」目录零变化。"""
    root = _fake_project_root(tmp_path)
    run = _fake_run(tmp_path)
    user_proj = tmp_path / "user_project_outside"
    user_proj.mkdir()
    (user_proj / "mine.py").write_text("x=1", encoding="utf-8")
    snap = {str(p): p.stat().st_mtime_ns for p in user_proj.rglob("*")}
    export_bundle(root, run)
    assert snap == {str(p): p.stat().st_mtime_ns for p in user_proj.rglob("*")}


# ---------- CLI ----------

def test_cli_export_bundle_json(tmp_path: Path) -> None:
    import os
    import sys
    root = _fake_project_root(tmp_path)
    run = _fake_run(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "repoproof.cli", "export-bundle",
         "--run-dir", str(run), "--dest", str(tmp_path / "out_bundle"), "--json"],
        capture_output=True, text=True, timeout=60, check=False,
        cwd=str(root), env={**os.environ, "PYTHONPATH": str(REPO / "src")},
    )
    # CLI 的 PROJECT_ROOT 是安装位置,contracts 查不到 → 仍应成功导出核心件
    out = json.loads(proc.stdout)
    assert proc.returncode == 0 and out["ok"] is True
    assert (tmp_path / "out_bundle" / "report.md").exists()
