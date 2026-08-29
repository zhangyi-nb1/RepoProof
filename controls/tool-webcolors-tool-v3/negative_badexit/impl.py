"""NC_badexit:坏输入不包装,裸奔→exit 2 — 接口契约必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_css3_name.txt': '{"gray_level":5,"input":"goldenrod","luma":166,"msp432_pattern":"101","rgb":{"blue":32,"green":165,"red":218}}', 'upstream-evidence-1.txt': '{"gray_level":5,"input":"#daa520","luma":166,"msp432_pattern":"101","rgb":{"blue":32,"green":165,"red":218}}', 'upstream-evidence-3.txt': '{"gray_level":1,"input":"#123456","luma":46,"msp432_pattern":"001","rgb":{"blue":86,"green":52,"red":18}}', 'upstream-evidence-5.txt': '{"gray_level":7,"input":"white","luma":255,"msp432_pattern":"111","rgb":{"blue":255,"green":255,"red":255}}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    # 坏输入不包装:裸奔异常 → 骨架兜成 exit 2 → 接口契约测试必须抓
    return _M[input_path.name]
