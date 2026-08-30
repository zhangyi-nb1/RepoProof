"""正控:全样例硬编码 — 只证明样例测试自洽可满足(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'chinese_exact_duplicate.ris': 'TY  - JOUR\nTI  - 中文文献标题：数据整理\nAU  - 王, 小明\nPY  - 2024\nJO  - 测试期刊\nER  - \n', 'unicode_whitespace_fields.ris': 'TY  - JOUR\nTI  - Étude sur 中文\u3000空格\nAU  - García, Ana\nAU  - 陈, 美\nPY  - 2022\nDO  - 10.1000/exemple.中文\nN1  - 含有制表符\t与全角空格\u3000的备注\nER  - \n', 'chinese_exact_duplicate-2.ris': 'TY  - JOUR\nTI  - 中文文献：机器学习在医学中的应用\nAU  - 张伟\nAU  - 李娜\nPY  - 2023\nJO  - 科学与技术\nDO  - 10.1000/example.中文\nER  - \n\nTY  - JOUR\nTI  - A distinct English record\nAU  - Smith, Jane\nPY  - 2022\nJO  - Example Journal\nER  - \n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
