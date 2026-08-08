"""必答问题的确定性推荐答案(用户实测:新手面对空输入框不知怎么答)。

铁律边界:推荐由系统已有的确定性数据生成——用户目标文本、宿主分析
结论、用户自己填写的验收样例——零 LLM、零网络。每条推荐必须附
「依据」,用户是唯一决定者(一键填入后仍可修改)。LLM 辅助生成
属任务准备层引入模型,按变更控制需先立 RFC,不在本函数职责内。
"""

from __future__ import annotations

from repoproof.adoption.intent.intent_parser import parse_intent


def suggest_answers(
    questions: list[str],
    *,
    goal: str,
    host_report: dict | None = None,
    examples_text: str = "",
) -> dict[str, tuple[str, str]]:
    """→ {问题: (推荐答案, 依据)};没有可靠推荐的问题不返回(绝不编造)。"""
    host_report = host_report or {}
    host_mode = str((host_report.get("host_mode") or {}).get("value") or "")
    blank = host_mode == "BLANK_PROJECT"
    test_cmd = str((host_report.get("test_command") or {}).get("value") or "")
    intent = parse_intent(goal or "")
    ex_lines = [ln.strip() for ln in (examples_text or "").splitlines() if "=>" in ln]

    out: dict[str, tuple[str, str]] = {}
    for q in questions:
        if "哪类能力" in q:
            cap = intent.target_capability or (goal or "").strip()[:40]
            if cap:
                out[q] = (cap, "从你第 1 步填写的目标文本中识别")
        elif "新增第三方依赖" in q:
            if blank:
                out[q] = ("允许", "空白项目引入外部能力必然新增依赖(宿主分析:空目录模式)")
            else:
                out[q] = ("允许", "采用类任务通常需要;若你的项目有依赖白名单请改为「不允许」并说明")
        elif "预期输出" in q:
            if ex_lines:
                head = ";".join(ex_lines[:2])
                out[q] = (f"与下方验收样例一致,例:{head}", "取自你在本页填写的验收样例")
            else:
                out[q] = ("见下方验收样例(每行一组:输入 => 期望)", "样例即成功标准——先在下方填样例更省事")
        elif "保持不变" in q:
            if blank:
                out[q] = ("无", "宿主分析:空白项目,没有既有行为需要保护")
            elif test_cmd:
                out[q] = (f"现有测试须全部通过({test_cmd})", "宿主分析探测到的测试命令")
    return out
