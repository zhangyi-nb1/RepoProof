"""必答问题的确定性推荐答案(用户实测:新手面对空输入框不知怎么答)。

铁律边界:推荐由系统已有的确定性数据生成——用户目标文本、宿主分析
结论、用户自己填写的验收样例——零 LLM、零网络。每条推荐必须附
「依据」,用户是唯一决定者(一键填入后仍可修改)。LLM 辅助生成
属任务准备层引入模型,按变更控制需先立 RFC,不在本函数职责内。
"""

from __future__ import annotations

from repoproof.adoption.intent.intent_parser import parse_intent

_GENERIC_GUIDANCE = ("系统没有可靠数据可推荐——用一句话直说你的决定/事实即可,"
                     "内容会原样记录进采用意向。")


def answer_guidance(question: str) -> str:
    """任意必答问题的作答格式指导(泛化兜底:推荐可以缺席,指导永远在)。"""
    if "哪类能力" in question:
        return "填能力类别或一句能力描述,如:文本转换 / 检索排序 / 文档解析"
    if "依赖" in question:
        return "答「允许」或「不允许」;不允许时请说明约束(如:只允许标准库)"
    if "预期输出" in question:
        return "给 1-2 个具体例子最好,格式:输入 => 期望输出"
    if "保持不变" in question:
        return "没有就答「无」;有则写明哪条行为或哪组测试必须保持"
    return _GENERIC_GUIDANCE


def _first_clause(text: str, limit: int = 60) -> str:
    """目标原文的第一小句(截到首个分隔符)——硬截断会产出半句话
    (用户实测:推荐答案显示"输出把每(依据…",[:40] 切在句中)。"""
    t = (text or "").strip()
    cut = len(t)
    for sep in (":", ":", ";", ";", "。", ",", ","):
        i = t.find(sep)
        if 0 <= i < cut:
            cut = i
    return t[:min(cut, limit)]


def suggest_answers(
    questions: list[str],
    *,
    goal: str,
    host_report: dict | None = None,
    repo_report: dict | None = None,
    examples_text: str = "",
) -> dict[str, tuple[str, str]]:
    """→ {问题: (推荐答案, 依据)};没有可靠推荐的问题不返回(绝不编造,
    UI 对缺席项显示 answer_guidance 的格式指导)。"""
    host_report = host_report or {}
    repo_report = repo_report or {}
    host_mode = str((host_report.get("host_mode") or {}).get("value") or "")
    blank = host_mode == "BLANK_PROJECT"
    test_cmd = str((host_report.get("test_command") or {}).get("value") or "")
    repo_desc = str((repo_report.get("description") or {}).get("value") or "")
    intent = parse_intent(goal or "")
    ex_lines = [ln.strip() for ln in (examples_text or "").splitlines() if "=>" in ln]

    out: dict[str, tuple[str, str]] = {}
    for q in questions:
        if "哪类能力" in q:
            cap, basis = intent.target_capability, "从你第 1 步填写的目标文本中识别"
            if not cap and repo_desc:
                cap2 = parse_intent(repo_desc).target_capability
                if cap2:
                    cap, basis = cap2, "从目标仓库的自述中识别"
            if not cap and (goal or "").strip():
                cap, basis = _first_clause(goal), "引用你目标的第一句(未匹配到已知类别,可改写)"
            if cap:
                out[q] = (cap, basis)
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
