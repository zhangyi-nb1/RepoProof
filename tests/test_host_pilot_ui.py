"""宿主任务 T1 UI 入口的钉死测试(用户正式 run 都在 UI 进行)。"""

from __future__ import annotations

from pathlib import Path

from repoproof.persistence.bench_records import append_run
from repoproof.ui.services.live_run import (
    HOST_PILOT,
    host_pilot_state,
    host_run_argv,
)

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "src" / "repoproof" / "ui" / "pages" / "host_pilot.py"


def _seed(root: Path, models: list[str]) -> None:
    for i, m in enumerate(models):
        append_run(root, {"run_id": f"{HOST_PILOT['task_id']}-2026080{i}-000000",
                          "task_id": HOST_PILOT["task_id"], "model": m,
                          "verdict": "FAIL"})


def test_pilot_order_ignores_fake_and_advances(tmp_path: Path) -> None:
    # 空账 → 第 1 发 deepseek
    s0 = host_pilot_state(tmp_path)
    assert (s0["next_order"], s0["next_model"]) == (1, "deepseek-v4-pro")
    # fake 冒烟不计入顺序
    _seed(tmp_path, ["fake-scripted", "fake-scripted"])
    s1 = host_pilot_state(tmp_path)
    assert (s1["next_order"], s1["next_model"]) == (1, "deepseek-v4-pro")
    # 第 1 发真实 run 完成 → 第 2 发 gpt-5.5
    append_run(tmp_path, {"run_id": f"{HOST_PILOT['task_id']}-20260809-111111",
                          "task_id": HOST_PILOT["task_id"],
                          "model": "deepseek-v4-pro", "verdict": "PASS_ADAPTED"})
    s2 = host_pilot_state(tmp_path)
    assert (s2["next_order"], s2["next_model"]) == (2, "gpt-5.5")
    assert len(s2["done"]) == 1
    # 两发齐 → 批完成,不再给出下一发
    append_run(tmp_path, {"run_id": f"{HOST_PILOT['task_id']}-20260809-222222",
                          "task_id": HOST_PILOT["task_id"],
                          "model": "gpt-5.5", "verdict": "PASS_ADAPTED"})
    assert host_pilot_state(tmp_path)["next_model"] is None


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
    assert any("连接配置" in str(e.value) for e in at.error)
    assert not at.button


def test_page_offers_only_preregistered_next_model(tmp_path: Path, monkeypatch) -> None:
    """有连接配置:唯一按钮=预注册顺序的下一发,无模型选择器。"""
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("REPOPROOF_DEEPSEEK_BASE", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("REPOPROOF_DEEPSEEK_KEY", "test-not-a-real-key")
    monkeypatch.setenv("REPOPROOF_DEEPSEEK_MODELS", "deepseek-v4-pro")
    import repoproof.ui.services.facts as facts

    monkeypatch.setattr(facts, "repo_root", lambda: tmp_path)
    at = AppTest.from_file(str(PAGE), default_timeout=30)
    at.run()
    assert not [e.value for e in at.exception]
    assert len(at.button) == 1
    assert "deepseek-v4-pro" in at.button[0].label
    assert not at.selectbox, "不得提供模型选择器(顺序冻结)"
