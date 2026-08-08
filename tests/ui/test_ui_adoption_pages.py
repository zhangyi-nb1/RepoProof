"""新增三页(项目分析/采用计划/修复过程)AppTest 验收,零 LLM。"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PAGES = REPO / "src" / "repoproof" / "ui" / "pages"

try:
    from streamlit.testing.v1 import AppTest

    HAVE_ST = True
except ImportError:  # pragma: no cover
    HAVE_ST = False

needs_streamlit = pytest.mark.skipif(not HAVE_ST, reason="streamlit not installed")


def _all_text(at) -> str:
    parts = []
    for kind in ("title", "header", "subheader", "markdown", "caption", "info", "success",
                 "warning", "error", "metric", "button", "text_input"):
        for el in getattr(at, kind, []):
            parts.append(str(getattr(el, "value", "")) + str(getattr(el, "label", "")))
    return "\n".join(parts)


@needs_streamlit
def test_analysis_page_runs_real_analyzer() -> None:
    at = AppTest.from_file(str(PAGES / "analysis.py"), default_timeout=60)
    at.run()
    next(b for b in at.button if b.label == "开始分析").click().run()
    assert not at.exception
    text = _all_text(at)
    for section in ("你的项目", "Python 版本", "测试", "推荐接入点", "发现风险"):
        assert section in text, section
    assert "事实" in text or "未知" in text  # 三级出处中文标注
    assert "ingest.py" in text  # 示例 fixture 的真实接入点


@needs_streamlit
def test_plan_page_shows_plan_and_gate_blocks_unanswered() -> None:
    if not (REPO / "upstream-cache" / "upstream-dc7c0af5466b").exists():
        pytest.skip("pinned cache absent")
    at = AppTest.from_file(str(PAGES / "plan_view.py"), default_timeout=120)
    at.session_state["plan_host"] = str(REPO)  # 确定性:宿主=RepoProof 自身
    at.session_state["plan_repo"] = str(REPO / "upstream-cache" / "upstream-dc7c0af5466b")
    at.run()
    assert not at.exception
    text = _all_text(at)
    for section in ("你的目标", "AI 理解", "推荐方案", "预计修改", "成功标准", "需要确认"):
        assert section in text, section
    labels = [b.label for b in at.button]
    assert "修改计划" in labels and "确认开始" in labels
    # 未回答问题 → Human Gate 拒绝(真实 gate,不是 UI 判定)
    next(b for b in at.button if b.label == "确认开始").click().run()
    errs = "".join(str(e.value) for e in at.error)
    assert "还不能开始" in errs


@needs_streamlit
def test_repair_page_teaches_multi_round() -> None:
    at = AppTest.from_file(str(PAGES / "repair_view.py"), default_timeout=60)
    at.run()
    assert not at.exception
    text = _all_text(at)
    assert "AI 不是一次生成答案" in text
    for section in ("第1轮", "第2轮", "第3轮", "修改", "测试", "失败", "改善"):
        assert section in text, section
    assert "5/9" in text and "8/9" in text and "9/9" in text
    assert "永远不宣布成功" in text  # 全绿≠最终成功的诚实边界


@needs_streamlit
def test_wizard_step3_need_information_unlocks_via_confirmations(tmp_path) -> None:
    """死角修复(用户实测 2026-08-08):深度检查 NEED_INFORMATION 时,
    「?」条目只渲染成文字、无处补齐,「下一步」永久灰死。现在每条
    问题=人工确认勾选框,问题+风险全勾即解锁;阻断项仍不可绕过。"""
    import subprocess

    from repoproof.adoption.admission.admission_report import decide
    from repoproof.adoption.analysis.host_analyzer import analyze_host_project
    from repoproof.adoption.analysis.repository_analyzer import analyze_repository_dir

    host_dir = tmp_path / "empty_project"
    host_dir.mkdir()
    repo_dir = tmp_path / "norepo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("# demo\n", encoding="utf-8")
    (repo_dir / "demo.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo_dir)], check=True)
    for args in (["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", "-C", str(repo_dir), "-c", "user.email=t@t",
                        "-c", "user.name=t", *args], check=True)

    host = analyze_host_project(str(host_dir))
    repo = analyze_repository_dir(repo_dir, url="https://github.com/example/norepo")
    adm = decide(host, repo)
    assert adm.status == "NEED_INFORMATION" and adm.questions  # 测试前提

    at = AppTest.from_file(str(PAGES / "new_task.py"), default_timeout=60)
    at.session_state["wizard_step"] = 3
    at.session_state["wz_goal"] = "为我的项目引入演示能力,输入输出都是字符串"
    at.session_state["wz_project"] = str(host_dir)
    at.session_state["wz_repo"] = "https://github.com/example/norepo"
    at.session_state["wz_rev"] = "main"
    at.session_state["wz_risk_ok"] = True
    at.session_state["wz_host_report"] = host.to_dict()
    at.session_state["wz_repo_report"] = repo.to_dict()
    at.run()
    assert not at.exception
    assert next(b for b in at.button if b.label == "下一步").disabled  # 未确认前锁死
    q_boxes = [c for c in at.checkbox if str(c.label).startswith("我已人工核实并确认")]
    assert q_boxes, "「?」条目必须有对应的确认控件"
    for c in at.checkbox:  # 问题确认 + 风险接受全勾
        c.check()
    at.run()
    assert not at.exception
    assert not next(b for b in at.button if b.label == "下一步").disabled  # 解锁
    assert "会解锁" not in _all_text(at) or "确认完毕" in _all_text(at)


@needs_streamlit
def test_wizard_step2_warns_on_swapped_fields() -> None:
    """用户实测:项目路径/仓库地址/版本号整体错位一格,界面曾零提示。
    现在三个字段任一填成"不像它该有的形态"都就地黄条提醒。"""
    at = AppTest.from_file(str(PAGES / "new_task.py"), default_timeout=60)
    at.session_state["wizard_step"] = 2
    at.session_state["wz_project"] = ""  # 真正的项目路径框空着
    at.session_state["wz_repo"] = "/Users/someone/Desktop/pluralize_demo"
    at.session_state["wz_rev"] = "https://github.com/jpvanhal/inflection"
    at.run()
    assert not at.exception
    warns = "".join(str(w.value) for w in at.warning)
    assert "像本机路径" in warns  # 仓库框里是路径
    assert "像一个网址" in warns  # 版本框里是网址
    assert "填错框" in warns


def test_frozen_tasks_detailed_newest_first_with_labels(tmp_path) -> None:
    """用户实测:任务下拉全是相似英文 ID 字母序,分不清哪个是刚冻结的。
    现在按冻结时间最新在前,label 带时间,最新标 🆕,默认选中第一项。"""
    import os
    import time

    from repoproof.ui.services.live_run import frozen_tasks_detailed

    c = tmp_path / "contracts"
    c.mkdir()
    old = c / "adopt-aaa-guided-v1.package.json"
    new = c / "adopt-zzz-guided-v1.package.json"
    old.write_text("{}", encoding="utf-8")
    new.write_text("{}", encoding="utf-8")
    now = time.time()
    os.utime(old, (now - 86400 * 3, now - 86400 * 3))  # 3 天前冻结
    os.utime(new, (now, now))  # 刚冻结

    items = frozen_tasks_detailed(tmp_path)
    assert [it["task_id"] for it in items] == [
        "adopt-zzz-guided-v1", "adopt-aaa-guided-v1"]  # 时间序压过字母序
    assert items[0]["label"].startswith("🆕 ") and "今天" in items[0]["label"]
    assert "🆕" not in items[1]["label"] and "冻结" in items[1]["label"]


@needs_streamlit
def test_wizard_step2_version_ambiguity_guards(tmp_path) -> None:
    """歧义修复(用户实测):版本号留空时用户把「本次分析快照 commit」
    当成系统推荐版本抄回。现在:留空即提示默认分支语义;检测到的
    发布 Tag 可一键填入版本框。"""
    import subprocess

    from repoproof.adoption.analysis.repository_analyzer import analyze_repository_dir

    repo_dir = tmp_path / "demo"
    repo_dir.mkdir()
    (repo_dir / "demo.py").write_text("X = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo_dir)], check=True)
    for args in (["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", "-C", str(repo_dir), "-c", "user.email=t@t",
                        "-c", "user.name=t", *args], check=True)
    rep = analyze_repository_dir(repo_dir, url="https://github.com/example/demo")

    at = AppTest.from_file(str(PAGES / "new_task.py"), default_timeout=60)
    at.session_state["wizard_step"] = 2
    at.session_state["wz_repo"] = "https://github.com/example/demo"
    at.session_state["wz_rev"] = ""
    at.session_state["wz_repo_report"] = rep.to_dict()
    at.session_state["wz_repo_tags"] = ["0.5.1", "0.5.0"]
    at.run()
    assert not at.exception
    infos = "".join(str(i.value) for i in at.info)
    assert "最新开发提交" in infos  # 留空语义就地说明
    text = _all_text(at)
    assert "不是**版本推荐" in text or "不是版本推荐" in text.replace("**", "")
    assert "正式发布 Tag" in text
    fill = next(b for b in at.button if "一键填入最新正式 Tag" in str(b.label))
    fill.click().run()
    assert at.session_state["wz_rev"] == "0.5.1"  # 点击后版本框被填入 Tag


def test_local_runs_sorted_by_time_not_name() -> None:
    """用户实测:字母序把 thefuzz(t)顶在最前,刚跑完的 inflection(i)
    被埋没。回顾/历史列表必须按尾缀时间戳最新在前。"""
    from repoproof.ui.services.facts import local_runs, run_ts_human

    names = local_runs()
    assert names, "本仓库应有本地运行"
    stamps = [n[-15:] for n in names]
    assert stamps == sorted(stamps, reverse=True)  # 时间序,不是名字序
    assert run_ts_human("adopt-x-guided-v2-20260808-172420") == "08-08 17:24"


def test_lock_race_window_closed_by_started_at(tmp_path, monkeypatch) -> None:
    """用户实测:预检窗口内 run 目录未创建,"最新目录=上次已完成运行"
    使产物优先判完成误放行第二次启动(两个 deepseek 运行重叠 18 秒)。
    修复:锁记录 started_at,产物只在目录时间戳不早于启动时刻才算数。"""
    import json as _j
    import os

    from repoproof.ui.services.live_run import LOCK, active_run, start_run

    monkeypatch.setenv("REPOPROOF_API_KEY", "test-key")
    monkeypatch.setenv("REPOPROOF_API_BASE", "http://127.0.0.1:1")

    runs = tmp_path / "runs"
    old = runs / "adopt-x-guided-v1-20260101-000000"
    old.mkdir(parents=True)
    (old / "report.json").write_text('{"final_verdict": "PASS_ADAPTED"}', encoding="utf-8")

    # 新式锁:启动晚于旧运行,进程存活(用当前测试进程 pid)→ 必须仍视为运行中
    (tmp_path / LOCK).parent.mkdir(exist_ok=True)
    (tmp_path / LOCK).write_text(_j.dumps({
        "pid": os.getpid(), "task_id": "adopt-x-guided-v1",
        "started_at": "20260102-000000"}), encoding="utf-8")
    info = active_run(tmp_path)
    assert not info["report_ready"]  # 旧产物不算本次的完成
    assert info["alive"]
    out = start_run(tmp_path, "adopt-x-guided-v1")
    assert not out["ok"] and "已有任务在运行" in out["error"]  # 并发被拒

    # 旧式锁(无 started_at):保持兼容语义——旧产物即判完成
    (tmp_path / LOCK).write_text(_j.dumps({
        "pid": os.getpid(), "task_id": "adopt-x-guided-v1"}), encoding="utf-8")
    assert active_run(tmp_path)["report_ready"]


def test_run_mode_zh_distinguishes_baseline_from_agent_runs() -> None:
    """用户实测:装配基线(无 AI、预期失败)混在「你的运行」里,被误读成
    "gpt-5.5 失败"。运行类型必须人话可辨。"""
    from repoproof.ui.services.facts import run_mode_zh

    assert "无AI" in run_mode_zh("direct-adoption-baseline (scripted, no agent, no LLM)")
    assert "预期失败" in run_mode_zh("direct-adoption-baseline (scripted, no agent, no LLM)")
    assert run_mode_zh("real-agent-baseline") == "单次运行"
    assert run_mode_zh("guided-repair") == "多轮修复"
    assert run_mode_zh(None) == "—"
