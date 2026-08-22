"""宿主任务 T1–T4 UI 入口的钉死测试(用户正式 run 都在 UI 进行)。"""

from __future__ import annotations

from pathlib import Path

import pytest

from repoproof.persistence.bench_records import (
    EXPLORATORY_BATCH,
    append_adjudication,
    append_run,
)
from repoproof.ui.services.live_run import (
    HOST_PILOT,
    HOST_TASKS,
    host_pilot_state,
    host_run_argv,
    host_task_state,
    next_run_index,
    start_host_run,
    variance_summary,
)

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "src" / "repoproof" / "ui" / "pages" / "host_pilot.py"


def _seed(root: Path, models: list[str]) -> None:
    for i, m in enumerate(models):
        append_run(root, {"host_id": "zhangyi-nb1/offerclaw", "run_id": f"{HOST_PILOT['task_id']}-2026080{i}-000000",
                          "task_id": HOST_PILOT["task_id"], "model": m,
                          "verdict": "FAIL"})


def test_pilot_state_counts_per_model_and_ignores_fake(tmp_path: Path) -> None:
    """v2:自由选择+重复;fake 不计数;per-model run_index 与全局序号正确。"""
    s0 = host_pilot_state(tmp_path)
    assert s0["next_global_order"] == 1
    assert s0["by_model"] == {"deepseek-v4-pro": 0, "gpt-5.5": 0, "gpt-5.6": 0}
    _seed(tmp_path, ["fake-scripted", "fake-scripted"])
    assert host_pilot_state(tmp_path)["next_global_order"] == 1  # fake 不计
    # 同模型重复两发 + 另一模型一发
    for i, m in enumerate(["deepseek-v4-pro", "deepseek-v4-pro", "gpt-5.6"]):
        append_run(tmp_path, {
            "host_id": "zhangyi-nb1/offerclaw",
            "run_id": f"{HOST_PILOT['task_id']}-2026081{i}-111111",
                              "task_id": HOST_PILOT["task_id"],
                              "model": m, "verdict": "FAIL"})
    s = host_pilot_state(tmp_path)
    assert s["next_global_order"] == 4
    assert s["by_model"]["deepseek-v4-pro"] == 2
    assert s["by_model"]["gpt-5.6"] == 1
    assert s["by_model"]["gpt-5.5"] == 0
    assert len(s["done"]) == 3


def test_host_run_argv_never_carries_secrets(tmp_path: Path) -> None:
    argv = host_run_argv(tmp_path, run_order=1, run_index=1)
    joined = " ".join(argv)
    assert "host-run" in joined and "--run-order 1" in joined
    assert HOST_PILOT["contract"] in joined
    for secret_marker in ("KEY", "sk-", "BASE"):
        assert secret_marker not in joined, "密钥/连接信息绝不进 argv(只经进程环境)"


def test_page_renders_without_provider_env(tmp_path: Path, monkeypatch) -> None:
    """无连接配置:页面不崩,给出配置指引,不出现启动按钮。"""
    from streamlit.testing.v1 import AppTest

    for v in ("REPOPROOF_OPENAI_BASE", "REPOPROOF_OPENAI_KEY", "REPOPROOF_OPENAI_MODELS",
              "REPOPROOF_DEEPSEEK_BASE", "REPOPROOF_DEEPSEEK_KEY", "REPOPROOF_DEEPSEEK_MODELS",
              "REPOPROOF_API_BASE", "REPOPROOF_API_KEY", "REPOPROOF_MODEL"):
        monkeypatch.delenv(v, raising=False)
    import repoproof.ui.services.facts as facts

    monkeypatch.setattr(facts, "repo_root", lambda: tmp_path)
    at = AppTest.from_file(str(PAGE), default_timeout=30)
    at.run()
    assert not [e.value for e in at.exception]
    assert any("REPOPROOF" in str(e.value) for e in at.error)
    assert not at.button


def test_page_offers_model_choice_within_pool(tmp_path: Path, monkeypatch) -> None:
    """v2:有连接配置 → 模型选择器只含池内已配置模型 + 启动按钮。"""
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("REPOPROOF_DEEPSEEK_BASE", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("REPOPROOF_DEEPSEEK_KEY", "test-not-a-real-key")
    monkeypatch.setenv("REPOPROOF_DEEPSEEK_MODELS", "deepseek-v4-pro")
    import repoproof.ui.services.facts as facts

    monkeypatch.setattr(facts, "repo_root", lambda: tmp_path)
    at = AppTest.from_file(str(PAGE), default_timeout=30)
    at.run()
    assert not [e.value for e in at.exception]
    assert len(at.selectbox) == 1
    opts = at.selectbox[0].options  # AppTest 返回 format_func 后的标签
    assert len(opts) == 1 and opts[0].startswith("deepseek-v4-pro"), "只列池内且已配置的模型"
    assert len(at.button) == 1 and "第 1 发" in at.button[0].label


# ---- T1–T4 泛化(2026-08-11:用户要在 UI 里对各阶段重复发以观察方差)----


def test_registry_points_at_real_frozen_surfaces() -> None:
    """注册表指向的契约/预注册必须真实存在,且 task_id 与契约逐字一致。

    UI 是用户发射正式 run 的唯一入口——指错契约 = 整批数据废掉,
    所以这里对磁盘实物核验,不接受"看起来对"。"""
    import yaml

    for key, t in HOST_TASKS.items():
        assert t["key"] == key
        assert (ROOT / t["prereg"]).exists(), f"{key} 预注册缺失:{t['prereg']}"
        if t["runnable"]:
            cpath = ROOT / t["contract"]
            assert cpath.exists(), f"{key} 契约缺失:{t['contract']}"
            got = yaml.safe_load(cpath.read_text(encoding="utf-8"))["task_id"]
            assert got == t["task_id"], f"{key} task_id 与契约不符:{got}"
            assert t["models"], f"{key} 可发射却没有模型池"
        else:
            assert (ROOT / t["ledger"]).exists()
            assert (ROOT / t["pin_suite"]).exists()
            assert t["why_not_runnable"], "不可发射必须写明理由(UI 要展示)"


def test_t4_cannot_be_launched_from_ui(tmp_path: Path) -> None:
    """T4 是零模型调用的确定性专项,无方差可观察 → 两层都必须拒绝。"""
    with pytest.raises(ValueError, match="T4"):
        host_run_argv(tmp_path, run_order=1, task_key="T4")
    out = start_host_run(tmp_path, model="gpt-5.6", run_order=1, task_key="T4")
    assert out["ok"] is False and "T4" in out["error"]


def test_argv_carries_that_stage_own_contract(tmp_path: Path) -> None:
    for key in ("T1", "T2", "T3"):
        joined = " ".join(host_run_argv(tmp_path, run_order=7, run_index=2,
                                        task_key=key))
        assert HOST_TASKS[key]["contract"] in joined
        assert "--run-order 7" in joined and "--run-index 2" in joined
        # UI 加发一律是预注册之外的探索性发次 → 必须在**写入时**打标,
        # 否则台账里与预注册批次无从分辨(append-only,事后补不回来)。
        assert f"--batch {EXPLORATORY_BATCH}" in joined
        for other in set("T1 T2 T3".split()) - {key}:
            assert HOST_TASKS[other]["contract"] not in joined, "串台 = 整批作废"
        for secret_marker in ("KEY", "sk-", "BASE"):
            assert secret_marker not in joined


def test_per_task_counts_are_independent(tmp_path: Path) -> None:
    """同一模型在 T1/T2 各自计数;全局序号跨任务单调(TESTPLAN §9)。"""
    for key in ("T1", "T2", "T2"):
        append_run(tmp_path, {"host_id": "zhangyi-nb1/offerclaw", "run_id": f"{HOST_TASKS[key]['task_id']}-x{key}"
                              f"-{next_run_index(tmp_path, key, 'gpt-5.6')}",
                              "task_id": HOST_TASKS[key]["task_id"],
                              "model": "gpt-5.6", "verdict": "FAIL"})
    assert next_run_index(tmp_path, "T1", "gpt-5.6") == 2
    assert next_run_index(tmp_path, "T2", "gpt-5.6") == 3
    assert next_run_index(tmp_path, "T3", "gpt-5.6") == 1
    assert next_run_index(tmp_path, "T1", "gpt-5.5") == 1
    assert host_task_state(tmp_path, "T2")["next_global_order"] == 4  # 全局


def test_older_task_versions_are_disclosed_not_silently_dropped(tmp_path: Path) -> None:
    """旧版发次不进面板(版本不可互比),但**条数必须明示**——静默少显示会让
    人以为发次丢了,而"少报"正是本项目最忌讳的失真方向。"""
    append_run(tmp_path, {
        "host_id": "zhangyi-nb1/offerclaw",
        "run_id": "t3-old-1", "task_id": "t3-offerclaw-browser-use-v4",
                          "model": "gpt-5.6", "verdict": "FAIL"})
    append_run(tmp_path, {
        "host_id": "zhangyi-nb1/offerclaw",
        "run_id": "t3-old-2", "task_id": "t3-offerclaw-browser-use",
                          "model": "gpt-5.5", "verdict": "FAIL"})
    append_run(tmp_path, {
        "host_id": "zhangyi-nb1/offerclaw",
        "run_id": "t3-cur", "task_id": HOST_TASKS["T3"]["task_id"],
                          "model": "gpt-5.6", "verdict": "PASS_ADAPTED"})
    s = host_task_state(tmp_path, "T3")
    assert len(s["done"]) == 1, "面板只含当前冻结版"
    assert s["older_versions"] == {"t3-offerclaw-browser-use-v4": 1,
                                   "t3-offerclaw-browser-use": 1}
    assert host_task_state(tmp_path, "T1")["older_versions"] == {}


def test_variance_counts_effective_verdict_not_system(tmp_path: Path) -> None:
    """被人工判无效的假 PASS 不得进方差面板的通过计数;n<3 明确标注。"""
    tid = HOST_TASKS["T3"]["task_id"]
    for i, v in enumerate(["PASS_ADAPTED", "FAIL", "PASS_ADAPTED"]):
        append_run(tmp_path, {"host_id": "zhangyi-nb1/offerclaw", "run_id": f"{tid}-2026081{i}-000000", "task_id": tid,
                              "model": "gpt-5.6", "verdict": v,
                              "input_tokens": 100 + i * 50, "rounds_used": 1 + i})
    append_run(tmp_path, {"host_id": "zhangyi-nb1/offerclaw", "run_id": f"{tid}-fake", "task_id": tid,
                          "model": "fake-scripted", "verdict": "PASS"})
    append_adjudication(tmp_path, {
        "run_id": f"{tid}-20260810-000000", "system_verdict": "PASS_ADAPTED",
        "effective_verdict": "INVALIDATED_FALSE_PASS", "counts_as_pass": False,
        "adjudicated_at": "2026-08-11T00:00:00Z", "adjudicated_by": "test",
        "basis": "钉死用", "evidence_refs": ["tests/test_host_pilot_ui.py"]})

    var = variance_summary(tmp_path, "T3")
    assert [v["model"] for v in var] == ["gpt-5.6"], "fake 不进方差面板"
    v = var[0]
    assert v["n"] == 3 and v["enough_for_variance"] is True
    assert v["passes"] == 1, "系统判 2 个 PASS_ADAPTED,人工作废 1 个 → 有效 1"
    assert v["verdicts"] == {"PASS_ADAPTED": 1, "FAIL": 1,
                             "INVALIDATED_FALSE_PASS": 1}
    assert v["stats"]["读入"] == {"n": 3, "min": 100, "max": 200,
                                  "mean": 150.0, "spread": 100}
    # n<3 必须自报不足以谈方差(项目纪律:n<3 不排名)
    append_run(tmp_path, {"host_id": "zhangyi-nb1/offerclaw", "run_id": f"{tid}-20260820-000000", "task_id": tid,
                          "model": "gpt-5.5", "verdict": "FAIL"})
    small = [x for x in variance_summary(tmp_path, "T3") if x["model"] == "gpt-5.5"][0]
    assert small["n"] == 1 and small["enough_for_variance"] is False


def test_page_renders_every_stage(monkeypatch) -> None:
    """四个阶段逐一切换都不能崩;T4 走只读分支(无启动按钮)。"""
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("REPOPROOF_DEEPSEEK_BASE", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("REPOPROOF_DEEPSEEK_KEY", "test-not-a-real-key")
    monkeypatch.setenv("REPOPROOF_DEEPSEEK_MODELS", "deepseek-v4-pro")
    for key in HOST_TASKS:
        at = AppTest.from_file(str(PAGE), default_timeout=60)
        at.run()
        at.radio[0].set_value(key).run()
        assert not [e.value for e in at.exception], f"{key} 页面异常"
        if HOST_TASKS[key]["runnable"]:
            assert len(at.button) == 1 and key in at.button[0].label
            assert at.button[0].disabled, "未勾选探索性加发确认 → 发射按钮必须禁用"
        else:
            assert not at.button, "T4 只读,不得出现发射按钮"
            assert at.warning, "T4 必须说明为什么不能从这里发"


def test_local_runs_include_host_runs_time_sorted() -> None:
    """用户实测 bug:adopt-* 前缀过滤让宿主级 run 三页集体隐身——钉死修复。"""
    from repoproof.ui.services.facts import local_run_meta, local_runs, run_mode_zh

    names = local_runs()
    t1 = [n for n in names if n.startswith("t1-offerclaw")]
    # 2026-08-23 收线清理后补的资源护栏:钉的是"adopt-* 过滤不许隐身宿主级
    # run",需要盘上真有 t1 历史运行;runs/ 已清理时 skip,不许空盘读成回归。
    if not t1:
        pytest.skip("盘上无 t1-offerclaw 运行历史(runs/ 已收线清理);"
                    "任一宿主级 run 落盘后本测自动回归执行")
    assert names == sorted(names, key=lambda n: n[-15:], reverse=True), "必须时间序"
    meta = local_run_meta(t1[0])
    assert meta["verdict"] is not None
    assert meta["model"], "宿主级运行必须能标注模型型号(runs.jsonl 反查)"
    assert run_mode_zh("host-guided-repair") == "宿主级多轮修复"
