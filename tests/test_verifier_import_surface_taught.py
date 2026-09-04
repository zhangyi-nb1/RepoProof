"""判官能导入什么必须先教后杀(incident-verifier-import-surface-untaught-*)。

现象:两个独立仓库的判官第一版都伸手去要一个不在判官环境里的第三方读取库(一处读交付的
zip 容器文档,一处解析交付的 HTML),整轮自检变成一条 ModuleNotFoundError 类的失败。系统
的应对是"修判官"——用把判官改弱的方式教它环境边界,白扔一轮预算;而两处修复后的判官都用
标准库读通了同一份交付物,说明环境本就够用,缺的是一句话。判官起草与判官修复两份提示词
里从未提过可导入面。

不变量:
  I1 判官起草提示写明可导入面:只有标准库与已钉住的上游发行版,别的第三方导入会在验证时
     报 ModuleNotFoundError;
  I2 判官修复提示同样写明(修复轮同样会重新伸手要读取库);
  I3 给出的是**通用**标准库读法指引(zip 容器、HTML、结构化文本),不含任何病例标识。
"""

from __future__ import annotations

import re

from repoproof.adoption.intake import tool_drafter

_PROMPTS = {
    "draft": tool_drafter._VERIFIER_SYSTEM,
    "repair": tool_drafter._VERIFIER_REPAIR_SYSTEM,
}


def test_both_verifier_prompts_state_the_import_surface() -> None:
    for name, prompt in _PROMPTS.items():
        lowered = prompt.lower()
        assert "standard library" in lowered, name
        assert "modulenotfounderror" in lowered, name
        assert "pinned upstream" in lowered, name


def test_the_prompts_point_at_standard_library_readers() -> None:
    for name, prompt in _PROMPTS.items():
        lowered = prompt.lower()
        assert "zipfile" in lowered and "html.parser" in lowered, name


def test_the_guidance_names_no_case() -> None:
    banned = re.compile(
        r"mkdocs|pygal|xlsxwriter|nbformat|pillow|icalendar|python-pptx|openpyxl|beautifulsoup|bs4",
        re.IGNORECASE,
    )
    for name, prompt in _PROMPTS.items():
        assert banned.search(prompt) is None, name


def test_codex_shares_the_same_taught_prompts() -> None:
    assert tool_drafter._CODEX_VERIFIER_SYSTEM == tool_drafter._VERIFIER_SYSTEM
    assert tool_drafter._CODEX_VERIFIER_REPAIR_SYSTEM == tool_drafter._VERIFIER_REPAIR_SYSTEM
