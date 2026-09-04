"""失败要说出发生在哪(incident-failure-not-located-in-journey-report-*)。

现象:一趟连吃八次的旅程,顶层报告全部内容只有

    final_status : DRAFT_SELF_CHECK_FAILED
    stop_codes   : ['WORKSPACE_REFERENCE_EXECUTION_FAILED']
    detail       : 人工复核公开合同后重新自检或创建新任务版本

而公开合同一点问题都没有——那条建议把人往错误方向推;真正的定位(上游自己那句话、
出错的行、最内层帧)明明躺在 stages/draft.json 的逐轮记录里,从没上浮。

不变量:
  I1 顶层报告带上失败自己的话与出错位置(含最内层帧);
  I2 原本的建议不丢——定位在前、建议在后,两者并存;
  I3 没有诊断可给时不编:返回空,不塞占位文本。
"""

from __future__ import annotations

from repoproof.ui.services.autopilot import located_failure

_UPSTREAM = (
    "RuntimeError: the pinned upstream is not usable "
    "@ reference_impl.py:34 _load_catalog; reference_impl.py:60 build_workspace "
    "(innermost core.py:61 _raise_no_data_error)"
)


def _selfcheck(diagnostics):
    return {
        "ok": False,
        "final_reason_codes": ["WORKSPACE_REFERENCE_EXECUTION_FAILED"],
        "recommended_action": "保留失败证据,人工复核公开合同。",
        "report": {"rounds": [{"round": 1, "diagnostics": []}, {"round": 2, "diagnostics": diagnostics}]},
    }


def test_the_report_carries_the_failures_own_words_and_place() -> None:
    located = located_failure(_selfcheck(["RuntimeError", _UPSTREAM]))
    assert "RuntimeError" in located
    assert "reference_impl.py:34 _load_catalog" in located, "要说出出错位置"
    assert "core.py:61" in located, "要说出最内层帧"


def test_the_first_diagnostic_row_is_always_present() -> None:
    located = located_failure(_selfcheck(["CODE_A,CODE_B", "some detail without a location"]))
    assert located.startswith("CODE_A,CODE_B")
    assert "some detail" in located


def test_nothing_to_report_stays_empty() -> None:
    assert located_failure({}) == ""
    assert located_failure({"report": {"rounds": []}}) == ""
    assert located_failure({"report": {"rounds": [{"round": 1, "diagnostics": []}]}}) == ""


def test_a_single_row_does_not_get_padded() -> None:
    assert located_failure(_selfcheck(["ONLY_ONE"])) == "ONLY_ONE"
