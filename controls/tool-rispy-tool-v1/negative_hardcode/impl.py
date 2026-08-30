"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'chinese_exact_duplicate.ris': 'TY  - JOUR\nTI  - 中文文献标题：数据整理\nAU  - 王, 小明\nPY  - 2024\nJO  - 测试期刊\nER  - \n', 'unicode_whitespace_fields.ris': 'TY  - JOUR\nTI  - Étude sur 中文\u3000空格\nAU  - García, Ana\nAU  - 陈, 美\nPY  - 2022\nDO  - 10.1000/exemple.中文\nN1  - 含有制表符\t与全角空格\u3000的备注\nER  - \n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
