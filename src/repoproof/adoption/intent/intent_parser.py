"""Intent Parser(RFC-004)— 自然语言 → IntentDraft,确定性规则版。

三分纪律:Confirmed=用户原文命中;Assumption=规则推断(标注依据);
Question=必须由用户回答。无法确认的一律进 unknowns/questions——
禁止直接生成最终合同,禁止编造。零 LLM(LLM 辅助解析留作后续增强)。
"""

from __future__ import annotations

import re

from pydantic import BaseModel

_CAPABILITY_HINTS = [
    (r"pdf", "PDF 解析"), (r"markdown|frontmatter|元数据", "文档元数据解析"),
    (r"分块|chunk", "文本分块"), (r"检索|排序|bm25|search|rank", "检索排序"),
    (r"解析|parse|parsing", "内容解析"), (r"嵌入|embedding", "向量嵌入"),
]
_RE_REPO_MENTION = re.compile(r"(https://github\.com/[\w.-]+/[\w.-]+|[\w-]+/[\w-]+)\s*(?:仓库|库|repo)?")

STANDARD_QUESTIONS = [
    "是否允许为你的项目新增第三方依赖?",
    "预期输出的字段/格式是什么(能给一个例子最好)?",
    "有没有必须保持不变的现有行为?",
]


class IntentDraft(BaseModel):
    goal: str
    target_capability: str = ""
    expected_input: str = ""
    expected_output: str = ""
    constraints: list[str] = []
    unknowns: list[str] = []
    confirmed: list[str] = []
    assumptions: list[str] = []
    questions: list[str] = []

    def to_dict(self) -> dict:
        return self.model_dump()


def parse_intent(text: str) -> IntentDraft:
    text = (text or "").strip()
    draft = IntentDraft(goal=text)
    if not text:
        draft.unknowns.append("目标为空")
        draft.questions.append("请用一两句话描述你想实现的功能")
        return draft

    draft.confirmed.append(f"用户目标原文:{text}")

    low = text.lower()
    for pat, cap in _CAPABILITY_HINTS:
        if re.search(pat, low):
            draft.target_capability = cap
            draft.assumptions.append(f"推断目标能力为「{cap}」(依据:目标中出现 /{pat}/)")
            break
    if not draft.target_capability:
        draft.unknowns.append("目标能力类别无法从描述中确定")
        draft.questions.append("你想采用的是哪类能力(解析/检索/转换/其他)?")

    m = _RE_REPO_MENTION.search(text)
    if m and "/" in m.group(1):
        draft.confirmed.append(f"用户提及目标仓库:{m.group(1)}")

    # 输入/输出:仅当用户明说才算 Confirmed;否则 UNKNOWN + 提问
    m_in = re.search(r"输入(?:是|为|:|:)\s*([^,。;\n]+)", text)
    m_out = re.search(r"输出(?:是|为|:|:)\s*([^,。;\n]+)", text)
    if m_in:
        draft.expected_input = m_in.group(1).strip()
        draft.confirmed.append(f"预期输入:{draft.expected_input}")
    else:
        draft.unknowns.append("预期输入未明确")
    if m_out:
        draft.expected_output = m_out.group(1).strip()
        draft.confirmed.append(f"预期输出:{draft.expected_output}")
    else:
        draft.unknowns.append("预期输出格式未明确")

    if re.search(r"不(?:要|得|能|允许)|禁止", text):
        draft.constraints.append(f"用户提出限制(原文):{text}")
        draft.confirmed.append("用户明确提出了限制条件")

    draft.questions.extend(q for q in STANDARD_QUESTIONS if q not in draft.questions)
    return draft
