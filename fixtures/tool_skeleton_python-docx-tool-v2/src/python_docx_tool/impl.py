"""能力位(agent 交付区):必须调用 pinned python-docx 实现。

约定(合同的一部分):
  - extract(input_path) -> str:返回 JSON 文本;
  - 输入内容坏(能打开但不是合法 DOCX)→ raise UserInputError(...)
    (骨架把它转成 exit 1;裸奔其他异常会被兜成 exit 2 = 接口契约违约);
  - 重复调用同一输入必须返回相同结果;完全离线 CPU-only。
"""
from pathlib import Path


class UserInputError(ValueError):
    """输入内容级错误(格式坏/不可解析)。"""


def extract(input_path: Path) -> str:
    raise NotImplementedError("能力未实现(骨架初始态)")
