"""reference:真调 pinned webcolors —— 十六进制颜色编号 → CSS3 颜色名。

出题人提供,绝不交付。行为**严格忠实上游**(不擅自加宽松处理):

  "#daa520" → "goldenrod"      六位十六进制
  "#f00"    → "red"            三位简写(上游自己会展开)
  "#DAA520" → "goldenrod"      大小写不敏感
  "#123456" → UserInputError   合法十六进制,但 css3 里没有对应名字
  "daa520"  → UserInputError   缺 "#" —— 上游判为非法值
  ""        → UserInputError   空输入

最后两条是**有意保留**的上游行为:如果你希望"不带 # 也能识别",那是一个
产品决定(要改的是下面那行 + 题面),不是我替你默认的。
"""
from pathlib import Path

import webcolors


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    raw = input_path.read_text(encoding="utf-8").strip()
    if not raw:
        raise UserInputError("输入为空:请给一个十六进制颜色编号,例如 #daa520")
    try:
        return webcolors.hex_to_name(raw)
    except ValueError as exc:            # 非法十六进制 / 无对应颜色名
        raise UserInputError(str(exc)) from exc
