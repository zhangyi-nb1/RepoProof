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


def test_pilot_state_counts_per_model_and_ignores_fake(tmp_path: Path) -> None:
    """v2:自由选择+重复;fake 不计数;per-model run_index 与全局序号正确。"""
    s0 = host_pilot_state(tmp_path)
    assert s0["next_global_order"] == 1
    assert s0["by_model"] == {"deepseek-v4-pro": 0, "gpt-5.5": 0, "gpt-5.6": 0}
    _seed(tmp_path, ["fake-scripted", "fake-scripted"])
    assert host_pilot_state(tmp_path)["next_global_order"] == 1  # fake 不计
    # 同模型重复两发 + 另一模型一发
    for i, m in enumerate(["deepseek-v4-pro", "deepseek-v4-pro", "gpt-5.6"]):
        append_run(tmp_path, {"run_id": f"{HOST_PILOT['task_id']}-2026081{i}-111111",
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
