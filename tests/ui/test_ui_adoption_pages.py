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
