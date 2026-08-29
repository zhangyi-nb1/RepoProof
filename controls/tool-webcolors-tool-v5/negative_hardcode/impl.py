"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'upstream-evidence-5.txt': '{"color_name":"white","rgb":{"blue":255,"green":255,"red":255}}', 'upstream-evidence-7.txt': '{"color_name":"goldenrod","rgb":{"blue":32,"green":165,"red":218}}', 'typical_css3_name.txt': '{"color_name":"navy","rgb":{"blue":128,"green":0,"red":0}}', 'typical_css3_name-2.txt': '{"color_name":"aliceblue","rgb":{"blue":255,"green":248,"red":240}}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
