"""HB-PCDELTA-1 出题工程的 harness 接线钉死(G 系,2026-08-16)。

预注册:benchmarks/v2/preregistrations/HB-batch1-postcutoff-delta-prereg-20260816.md
四处接线,每处先红后绿:

  G1  source_repo 可选 —— delta 形态宿主即上游,复用 upstream-cache 会把含
      答案 commit 的 git 历史复制进会话(一条 `git log -p` 即满分)。
  G2  prompt_profile 双档 —— 缺省 offerclaw-v1 **逐字节不变**(K13 同律,
      金标哈希钉死);新档 hb-delta-v1 不得说 OfferClaw 的假话。
  G3  fake 冒烟 patch 形态 —— 正控 = 施上游 answer patch,现有"复制 .py +
      挂载 + 追加 rag_api.py"的形状对 delta 任务是三处硬伤。
  G4  bench 白名单 —— 三个 hb1-* 宿主目录显式登记,目录内只许 host/wheelhouse。

G2 的金标是**负控**(改坏第一宿主提示必红),不属红绿对;其余各条在接线
落地前必须先红。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from repoproof.runner.host_guided import (
    HostContract,
    build_host_prompt,
    source_commit_of,
    _fake_script,
)

REPO = Path(__file__).resolve().parents[1]
SIDECAR_CONTRACT = REPO / "benchmarks/v2/tasks/t3_sidecar_v1/contract.yaml"

# 2026-08-16 改动前实测(wheel_note="PIN-NOTE")。这是 K13 纪律的字节形态:
# 泛化提示的意义是让新形态能声明自己的话,不是趁机改第一宿主的话。
_OFFERCLAW_PROMPT_SHA = "48e2f4e37821cdd98a358993f38aad9b9ad99524f80da3513e9fb28ab4431c8e"


def _delta_contract_dict(**over) -> dict:
    d = {
        "task_id": "hb1-click-3581",
        "task_version": "v1",
        "kind": "host_integrated",
        "prompt_profile": "hb-delta-v1",
        "host": {
            "repo": "pallets/click",
            "commit": "16fc00e2f4a2717a521084f193709a6058afc693",
            "copy_path": "~/RepoProofBench/hb1-click-3581/host",
            "regression_command": [".venv/bin/python", "-m", "pytest", "tests",
                                   "-q", "-p", "no:cacheprovider"],
            "setup_commands": [["python3", "-m", "venv", ".venv"],
                               [".venv/bin/pip", "install", "-q", "--no-index",
                                "-e", ".", "pytest"]],
            "health_checks": [{"command": [".venv/bin/python", "-c", "import click"]}],
            "host_root_env": "HB_DELTA_HOST_ROOT",
            "wheelhouse_path": "~/RepoProofBench/hb1-click-3581/wheelhouse",
            "require_wheelhouse_manifest": False,
        },
        "capability": {
            "statement": "PR #3581: add @custom_version_option (upstream statement verbatim)",
            "requirements": [{"id": "R1", "text": "按题面实现,上游隐藏验收判卷"}],
        },
        "constraints": {"forbidden": ["- tests/ 只读:回归套件是量具,改它按伪造处理"]},
        "budgets": {"semantics": "per_round", "max_rounds": 3, "max_model_calls": 30,
                    "max_commands": 100, "max_patch_files": 15, "max_patch_lines": 1500,
                    "max_wall_time_minutes": 60, "max_input_tokens_total": 600000,
                    "max_output_tokens_total": 80000},
        "acceptance": {"public_test_command": [".venv/bin/python", "-m", "pytest",
                                               "tests", "-q", "-p", "no:cacheprovider"],
                       "hidden_oracle_command": ["unused"]},
        "task_shape": {},
        "failure_taxonomy_expected": ["DESIGN_MISMATCH", "IMPL_INCOMPLETE",
                                      "REGRESSION_BROKEN", "NO_SUBMISSION",
                                      "HARNESS_FAILURE", "PROVIDER_FAILURE"],
    }
    d.update(over)
    return d


# ---------------------------------------------------------------- G1 source_repo 可选


def test_g1a_contract_without_source_repo_loads():
    c = HostContract.model_validate(_delta_contract_dict())
    assert c.source_repo is None


def test_g1b_source_commit_falls_back_to_host_commit():
    c = HostContract.model_validate(_delta_contract_dict())
    assert source_commit_of(c) == c.host.commit


def test_g1c_source_commit_prefers_source_repo_when_present():
    c, _ = HostContract.load(SIDECAR_CONTRACT)
    assert c.source_repo is not None
    assert source_commit_of(c) == c.source_repo.resolved_commit


# ---------------------------------------------------------------- G2 prompt 双档


def test_g2a_offerclaw_prompt_byte_identical():
    """金标负控:缺省档提示逐字节不变。改坏第一宿主的话,这条先红。"""
    c, _ = HostContract.load(SIDECAR_CONTRACT)
    p = build_host_prompt(c, wheel_note="PIN-NOTE")
    assert hashlib.sha256(p.encode()).hexdigest() == _OFFERCLAW_PROMPT_SHA


def test_g2b_delta_prompt_tells_no_offerclaw_lies():
    c = HostContract.model_validate(_delta_contract_dict())
    p = build_host_prompt(c, wheel_note="w")
    assert "OfferClaw" not in p
    assert "../upstream" not in p          # 无上游区,提示不得声称有
    assert "requirements.txt" not in p     # 重放走契约 setup,不走 requirements.txt
    assert "rag_api" not in p


def test_g2c_delta_prompt_teaches_the_acceptance_semantics():
    """先教后杀(附录一第 4 条):验收语义类别公开,验收实例隐藏。"""
    c = HostContract.model_validate(_delta_contract_dict())
    p = build_host_prompt(c, wheel_note="w")
    flat = " ".join(p.split())             # 断言语义短语,不与换行位置耦合
    assert "upstream project's own hidden acceptance tests" in flat
    assert "from FAIL to PASS" in flat
    assert " ".join(c.acceptance.public_test_command) in p   # 公开反馈怎么跑,原样给
    assert "STAY INSIDE THE WORKSPACE" in p                  # H9-c 边界照教
    assert c.host.repo in flat


def test_g2d_unknown_prompt_profile_refused():
    with pytest.raises(Exception, match="prompt_profile"):
        HostContract.model_validate(_delta_contract_dict(prompt_profile="typo-v9"))


def test_g2e_offerclaw_profile_without_source_repo_refused():
    """缺省档的提示要说 ../upstream 的话 —— 没有 source_repo 就说不成。"""
    c = HostContract.model_validate(
        _delta_contract_dict(prompt_profile="offerclaw-v1"))
    with pytest.raises(Exception, match="source_repo"):
        build_host_prompt(c, wheel_note="w")


# ---------------------------------------------------------------- G3 fake patch 形态


def _patch_control(tmp_path: Path, *, with_setup: bool = True) -> SimpleNamespace:
    ctrl = tmp_path / "controls" / "positive"
    ctrl.mkdir(parents=True)
    (ctrl / "apply.patch").write_text(
        "diff --git a/src/x.py b/src/x.py\n--- a/src/x.py\n+++ b/src/x.py\n"
        "@@ -1 +1 @@\n-old\n+new\n", encoding="utf-8")
    if with_setup:
        (ctrl / "smoke_setup.txt").write_text("# nothing to install\necho ok\n",
                                              encoding="utf-8")
    return SimpleNamespace(task_dir=tmp_path)


def test_g3a_patch_mode_applies_patch_and_skips_mount(tmp_path):
    steps = _fake_script("positive", _patch_control(tmp_path))
    joined = "\n".join(a["command"] for s in steps for a in s["actions"])
    assert "git apply" in joined
    assert "+new" in joined                # patch 正文经 heredoc 送达
    assert "rag_api.py" not in joined      # OfferClaw 挂载形状不得出现
    assert "mount_" not in joined
    assert joined.rstrip().endswith("COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT")


def test_g3b_patch_mode_missing_setup_still_refuses(tmp_path):
    ns = _patch_control(tmp_path, with_setup=False)
    with pytest.raises(ValueError, match="环境清单"):
        _fake_script("positive", ns)


def test_g3c_py_mount_mode_unchanged():
    """现有形状原样:sidecar 正控仍走复制 .py + 挂载 + rag_api 追加。"""
    ns = SimpleNamespace(task_dir=SIDECAR_CONTRACT.parent)
    steps = _fake_script("positive", ns)
    joined = "\n".join(a["command"] for s in steps for a in s["actions"])
    assert "rag_api.py" in joined and "mount_" in joined


def test_g3d_patch_mode_negative_control_reuses_positive_setup(tmp_path):
    _patch_control(tmp_path)               # positive 带清单
    nc = tmp_path / "controls" / "nc_null_submission"
    nc.mkdir(parents=True)
    (nc / "apply.patch").write_text(
        "diff --git a/RP_NULL.txt b/RP_NULL.txt\nnew file mode 100644\n"
        "--- /dev/null\n+++ b/RP_NULL.txt\n@@ -0,0 +1 @@\n+inert\n",
        encoding="utf-8")
    steps = _fake_script("control:nc_null_submission", SimpleNamespace(task_dir=tmp_path))
    joined = "\n".join(a["command"] for s in steps for a in s["actions"])
    assert "echo ok" in joined             # 负控与正控同环境(回落纪律不变)
    assert "+inert" in joined


# ---------------------------------------------------------------- G5 PII 扫描范畴


def test_g5a_pii_profile_default_is_user_host():
    c = HostContract.model_validate(_delta_contract_dict())
    del c
    from repoproof.runner.host_guided import HostInfo
    assert HostInfo.model_fields["pii_scan_profile"].default == "user-host"


def test_g5b_pii_profile_typo_refused():
    d = _delta_contract_dict()
    d["host"]["pii_scan_profile"] = "skip"     # 想跳过必须写全名,不许缩写滑过
    with pytest.raises(Exception, match="pii_scan_profile"):
        HostContract.model_validate(d)


def test_g5c_public_oss_tree_accepted():
    d = _delta_contract_dict()
    d["host"]["pii_scan_profile"] = "public-oss-tree"
    c = HostContract.model_validate(d)
    assert c.host.pii_scan_profile == "public-oss-tree"


def test_g5d_scan_required_is_the_default_and_only_full_name_skips():
    from repoproof.runner.host_guided import _pii_scan_required
    assert _pii_scan_required(HostContract.model_validate(_delta_contract_dict())) is True
    d = _delta_contract_dict()
    d["host"]["pii_scan_profile"] = "public-oss-tree"
    assert _pii_scan_required(HostContract.model_validate(d)) is False


# ---------------------------------------------------------------- G7 测量 PATH 语义


def test_g7a_measure_env_default_is_empty():
    """缺省不动 PATH —— 既有宿主的测量环境逐字节不变。"""
    from repoproof.runner.host_guided import HostGuidedRunner
    c = HostContract.model_validate(_delta_contract_dict())
    r = object.__new__(HostGuidedRunner)      # 只考 _measure_env,不走 __init__
    r.contract = c
    s = SimpleNamespace(root=Path("/tmp/x"))
    assert r._measure_env(s) == {}


def test_g7b_declared_flag_prepends_session_venv_bin():
    """B10 同款:声明后 venv/bin 前置(sqlglot test_lazy_load 裸 python 实测)。"""
    from repoproof.runner.host_guided import HostGuidedRunner
    d = _delta_contract_dict()
    d["host"]["path_prepend_venv_bin"] = True
    r = object.__new__(HostGuidedRunner)
    r.contract = HostContract.model_validate(d)
    env = r._measure_env(SimpleNamespace(root=Path("/tmp/x")))
    assert env["PATH"].startswith("/tmp/x/host/.venv/bin:")
    assert len(env["PATH"]) > len("/tmp/x/host/.venv/bin:")   # 原 PATH 保留在后


# ------------------------------------------------- G8 oracle env 净化(审查 [1a])


def test_g8a_default_keeps_legacy_pythonpath_injection():
    """缺省 false:既有宿主(OfferClaw)的 oracle 靠 PYTHONPATH import 宿主模块,
    一个字节不许变 —— 新洞要堵,旧宿主不许被顺手改坏。"""
    from repoproof.runner.host_guided import HostInfo
    assert HostInfo.model_fields["oracle_env_sanitized"].default is False


def test_g8b_declared_contract_drops_pythonpath():
    d = _delta_contract_dict()
    d["host"]["oracle_env_sanitized"] = True
    c = HostContract.model_validate(d)
    assert c.host.oracle_env_sanitized is True


def test_g8c_run_oracle_env_branches_on_the_flag():
    """判卷进程的 env 是伪绿通道的闸:声明后不许再出现 PYTHONPATH,
    且必须禁 user-site(usercustomize 是同型通道)。"""
    src = (Path(__file__).resolve().parents[1]
           / "src/repoproof/runner/host_guided.py").read_text(encoding="utf-8")
    seg = src.split("def _run_oracle")[1].split("def ")[0]
    assert "oracle_env_sanitized" in seg
    assert '"PYTHONNOUSERSITE": "1"' in seg
    # PYTHONPATH 只许出现在未净化的那一支里
    assert seg.count('"PYTHONPATH"') == 1


# ---------------------------------------------------------------- G4 bench 白名单


def test_g4a_hb1_host_dirs_are_registered(tmp_path, monkeypatch):
    from repoproof.harness.host_guard import bench_root_strays
    for name in ("hb1-click-3581", "hb1-click-3407", "hb1-sqlglot-8042"):
        (tmp_path / name / "host").mkdir(parents=True)
        (tmp_path / name / "wheelhouse").mkdir()
    assert bench_root_strays(tmp_path) == []


def test_g4b_hb1_inner_stray_is_flagged(tmp_path):
    from repoproof.harness.host_guard import bench_root_strays
    d = tmp_path / "hb1-click-3581"
    (d / "host").mkdir(parents=True)
    (d / "wheelhouse").mkdir()
    (d / "answer").mkdir()                 # 答案区混进 bench = 必须被拦
    strays = bench_root_strays(tmp_path)
    assert any("answer" in s for s in strays)
