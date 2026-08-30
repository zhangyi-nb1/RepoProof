"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_nonascii.tsv': 'sample_name\tvalue\tsource_unit\ttarget_unit\tconverted_value\tstatus\treason\n样品甲\t1234.567\tmeter\tkilometer\t1.23457\tconverted\t\ncafé-β\t0.5\tkilogram\tgram\t500\tconverted\t\n', 'mixed_valid_unicode_and_pint_errors.tsv': "sample_name\tvalue\tsource_unit\ttarget_unit\tconverted_value\tstatus\treason\n样品α\t1234.567\tmeter\tcentimeter\t123457\tconverted\t\n温度样本\t25\tdegC\tkelvin\t298.15\tconverted\t\n未知单位\t7\tmystery_unit\tmeter\t\tunconverted\tUndefinedUnitError: 'mystery_unit' is not defined in the unit registry\n量纲不符\t3\tsecond\tmeter\t\tunconverted\tDimensionalityError: Cannot convert from 'second' ([time]) to 'meter' ([length])\n微量\t0.0000001234567\tmeter\tmicrometer\t0.123457\tconverted\t\n"}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
