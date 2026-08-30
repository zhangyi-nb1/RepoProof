"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'mixed_valid_rows.tsv': '样本名\t原数值\t目标单位\t换算结果\t状态\t说明\n样品α\t1.23456789 meter\tcentimeter\t123.457 centimeter\t已换算\t\n质量检查\t2 kilogram\tgram\t2000 gram\t已换算\t\n不兼容\t5 second\tmeter\t\t未换算\t无法换算：DimensionalityError\n解析失败\tabc\tmeter\t\t未换算\t无法换算：UndefinedUnitError\n', 'typical_unicode.csv': '样本名\t原数值\t目标单位\t换算结果\t状态\t说明\n样品α\t1.23456789 kilometer\tmeter\t1234.57 meter\t已换算\t\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
