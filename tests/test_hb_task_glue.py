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
    _fake_script,
    build_host_prompt,
    source_commit_of,
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


def test_g8c_oracle_import_env_branches_on_the_flag():
    """判卷进程的 import 面 env 是伪绿通道的闸(读真返回值,不读源码文本:
    源码断言会被"注释里还留着这个词"糊弄过去 —— M72f 逃逸实测)。"""
    from repoproof.runner.host_guided import HostGuidedRunner
    s = SimpleNamespace(root=Path("/tmp/x"))

    r = object.__new__(HostGuidedRunner)          # 缺省:既有宿主行为不变
    r.contract = HostContract.model_validate(_delta_contract_dict())
    assert r._oracle_import_env(s) == {"PYTHONPATH": "/tmp/x/host"}

    d = _delta_contract_dict()
    d["host"]["oracle_env_sanitized"] = True
    r2 = object.__new__(HostGuidedRunner)
    r2.contract = HostContract.model_validate(d)
    env = r2._oracle_import_env(s)
    assert "PYTHONPATH" not in env                # 宿主根不进 import 面
    assert env["PYTHONNOUSERSITE"] == "1"         # usercustomize 同型通道也堵


def test_g8d_run_oracle_uses_the_branching_env_not_a_literal():
    """接线钉死:_run_oracle 必须**用**那个函数,不许自己再写一份字面量
    (两处各写一份必然漂移,且旁路掉上面的行为钉死)。"""
    src = (Path(__file__).resolve().parents[1]
           / "src/repoproof/runner/host_guided.py").read_text(encoding="utf-8")
    seg = src.split("def _run_oracle")[1].split("\n    def ")[0]
    assert "self._oracle_import_env(s)" in seg
    assert "PYTHONPATH" not in seg                # 字面量只许活在那个函数里


# ------------------------------------------- G9 skipped ≠ failed(HB pilot 首发抓)


def _junit_bytes(cases: list[tuple[str, str]]) -> bytes:
    """合成 junitxml:(用例名, 结局) → 字节。结局 passed/failed/skipped。"""
    body = []
    for name, outcome in cases:
        inner = {"passed": "", "failed": '<failure message="boom"/>',
                 "skipped": '<skipped message="win only"/>'}[outcome]
        body.append(f'<testcase classname="tests.test_x" name="{name}">{inner}</testcase>')
    return (f'<testsuite tests="{len(cases)}">' + "".join(body) + "</testsuite>").encode()


def test_g9a_skipped_is_neither_passed_nor_failed():
    """量具的三分法必须守住:skipped 混进 failed 会凭空造 FailurePacket,
    混进 passed 会让'跳过'冒充'通过'。两边都不许沾。"""
    from repoproof.verification.junit import parse_junit_xml
    j = parse_junit_xml(_junit_bytes([("a", "passed"), ("b", "skipped"), ("c", "failed")]))
    by = {n["node_id"].split("::")[1]: n["outcome"] for n in j["nodes"]}
    assert by == {"a": "passed", "b": "skipped", "c": "failed"}

    # 修复后的口径:走真函数,不在测试里另抄一份判别式
    from repoproof.verification.junit import split_public_outcomes
    s = split_public_outcomes(j["nodes"])
    assert len(s.failed_nodes) == 1 and s.failed_nodes[0].endswith("::c")
    assert (s.passed, s.skipped) == (1, 1)


def test_g9b_no_failure_packet_is_fabricated_for_skips():
    """首发实测的真形态:26 个 Windows-only 用例在 macOS 恒 skip → 修复前
    每轮凭空喂 26 个'去修 getchar windows'的失败包,吃掉模型真预算。"""
    from repoproof.runner.guided_repair import build_failure_packets
    from repoproof.verification.junit import parse_junit_xml, split_public_outcomes
    cases = [("real_bug", "failed")] + [(f"getchar_windows_{i}", "skipped") for i in range(26)]
    nodes = parse_junit_xml(_junit_bytes(cases))["nodes"]
    s = split_public_outcomes(nodes)
    packets = build_failure_packets(s.failed_nodes, s.details)
    assert len(packets) == 1, f"skip 造出了假失败包:{len(packets)} 个"
    assert "getchar" not in str(packets)
    assert s.skipped == 26                      # 排除了,但没丢


def test_g9c_round_record_carries_the_skip_count():
    """skipped 不许静默丢弃 —— 排除它的同时必须留痕,否则'跳过数暴涨'
    这件事从证据里彻底消失。"""
    from repoproof.runner.guided_repair import RepairRoundRecord
    assert "public_skipped" in RepairRoundRecord.model_fields
    assert RepairRoundRecord(round_index=1).public_skipped is None   # 旧发次不追溯
    assert RepairRoundRecord(round_index=1, public_skipped=26).to_dict()["public_skipped"] == 26


def test_g9d_the_split_is_one_shared_function_not_two_copies():
    """同病扫查:v1(guided_repair)与 host_guided 是同一处置的两条路。
    只修被首发撞到的那一条,等于把同一个坑留在隔壁等下一次撞。
    钉的是**函数真实返回值**,不是源码文本(M72f 的教训:文本断言会被
    注释里的同名词喂饱而漏掉真突变)。"""
    from repoproof.runner.guided_repair import split_public_outcomes as v1
    from repoproof.runner.host_guided import split_public_outcomes as v2
    assert v1 is v2, "两条修复路各拿一份拷贝 = 下次只修一边"

    nodes = [{"node_id": "t::ok", "outcome": "passed", "message": ""},
             {"node_id": "t::win", "outcome": "skipped", "message": ""},
             {"node_id": "t::bug", "outcome": "failed", "message": "boom"}]
    s = v1(nodes)
    assert s.failed_nodes == ["t::bug"]        # skipped 不进失败
    assert s.details == {"t::bug": "boom"}     # 也不进失败明细
    assert (s.passed, s.skipped) == (1, 1)     # 也不进通过,且留痕


def _ast_of(rel: str):
    import ast
    return ast.parse((REPO / rel).read_text(encoding="utf-8"))


def _calls_named(tree, name: str) -> int:
    import ast
    return sum(1 for n in ast.walk(tree)
               if isinstance(n, ast.Call) and getattr(n.func, "id", None) == name)


def _has_not_passed_compare(tree) -> bool:
    """AST 里是否还留着 `<expr> != "passed"` 这条判别式。用 AST 而非字符串:
    M72f 的教训是文本断言会被注释里的同名词喂饱,从而漏掉真突变。"""
    import ast
    for n in ast.walk(tree):
        if (isinstance(n, ast.Compare) and len(n.ops) == 1
                and isinstance(n.ops[0], ast.NotEq)
                and isinstance(n.comparators[0], ast.Constant)
                and n.comparators[0].value == "passed"):
            return True
    return False


def test_g9d3_neither_repair_path_keeps_a_local_copy_of_the_buggy_predicate():
    """接线钉(M72j 同型):共享函数存在 ≠ 调用点在用它。
    任一条修复路把判别式抄回本地,这条就必须红。"""
    for rel in ("src/repoproof/runner/host_guided.py",
                "src/repoproof/runner/guided_repair.py"):
        tree = _ast_of(rel)
        assert _calls_named(tree, "split_public_outcomes") >= 1, f"{rel} 不再走共享口径"
        assert not _has_not_passed_compare(tree), f'{rel} 抄回了 != "passed"'


def test_g9e2_the_battery_routes_through_the_shared_classifier():
    tree = _ast_of("src/repoproof/harness/controls_battery.py")
    assert _calls_named(tree, "classify_negative_control") >= 1
    assert not _has_not_passed_compare(tree), "负控判词抄回了 != \"passed\""


def test_g9d2_the_v1_round_record_keeps_the_skip_count():
    from repoproof.adoption.repair.repair_loop import RoundResult
    assert RoundResult(adapter_snapshot="x", passed=0).skipped is None   # 旧轮不追溯
    assert RoundResult(adapter_snapshot="x", passed=0, skipped=26).skipped == 26


def test_g9e_a_skipped_must_fail_node_is_not_a_fired_control():
    """反方向的假绿:负控的必红用例若被 skip(平台标记 / 导入失败),
    旧式 `!= passed` 会把它记成 FAILED_AS_EXPECTED —— 控制根本没考,
    却发了一张"已验证"的证书。必须 fail-closed。"""
    from repoproof.harness.controls_battery import (
        FAILED_AS_EXPECTED,
        PASS,
        classify_negative_control,
    )
    must = ["test_cheat"]
    red = [{"node_id": "t::test_cheat", "outcome": "failed"}]
    skip = [{"node_id": "t::test_cheat", "outcome": "skipped"}]
    green = [{"node_id": "t::test_cheat", "outcome": "passed"}]

    assert classify_negative_control(red, must) == FAILED_AS_EXPECTED
    assert classify_negative_control(green, must) == "NOT_REJECTED"

    verdict = classify_negative_control(skip, must)
    assert verdict not in (PASS, FAILED_AS_EXPECTED), "跳过冒充了'控制已生效'"
    assert "SKIPPED" in verdict, verdict          # 病名必须说出口,不许混进别的桶


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
