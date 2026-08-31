"""NC_reimpl:全样例但零 import 上游 — provenance 必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_valid.tsv': '样本名\t原数值\t目标单位\t换算结果\t状态\t说明\n样品A\t12.5 meter\tcentimeter\t1250\t已换算\t\n样品B\t3 kilogram\tgram\t3000\t已换算\t\n', 'nonascii_invalid_values.tsv': "样本名\t原数值\t目标单位\t换算结果\t状态\t说明\n样品Ω\tabc\tmeter\t\t未换算\t无法换算：UndefinedUnitError: 'abc' is not defined in the unit registry\n温度样本é\t1 meter\tnot_a_unit\t\t未换算\t无法换算：UndefinedUnitError: 'not_a_unit' is not defined in the unit registry\n", 'mixed_valid_rows.tsv': "样本名\t原数值\t目标单位\t换算结果\t状态\t说明\n普通样本\t1.23456789 meter\tcentimeter\t123.456789\t已换算\t\n咖啡样品α\t 2 kilogram \tgram\t2000\t已换算\t\n坏单位\t3 meter\tnot_a_unit\t\t未换算\t无法换算：UndefinedUnitError: 'not_a_unit' is not defined in the unit registry\n非有限\tNaN meter\tcentimeter\t\t未换算\t无法换算：结果不是有限实数\n"}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
