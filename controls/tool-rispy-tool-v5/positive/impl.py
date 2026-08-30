"""正控:全样例硬编码 — 只证明样例测试自洽可满足(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'duplicate_and_near_duplicate.ris': 'TY  - JOUR\nTI  - 中文文献标题\nAU  - 王小明\nAU  - Smith, John\nPY  - 2024\nJO  - 测试期刊\nAB  - 包含中文摘要与 Unicode：é。\nER  - \nTY  - JOUR\nTI  - 中文文献标题\nAU  - 王小明\nAU  - Smith, John\nPY  - 2025\nJO  - 测试期刊\nAB  - 包含中文摘要与 Unicode：é。\nER  - \n', 'same_title_different_metadata.ris': 'TY  - JOUR\nTI  - 同题不同作者\nAU  - 张, 三\nPY  - 2023\nVL  - 1\nER  - \nTY  - JOUR\nTI  - 同题不同作者\nAU  - 李, 四\nPY  - 2023\nVL  - 1\nER  - \n', 'chinese_exact_duplicate_and_near_duplicate.ris': 'TY  - JOUR\nTI  - 中文文献去重测试\nAU  - 张伟\nAU  - 李娜\nAB  - 这是一条包含中文摘要的记录。\nPY  - 2024\nER  - \nTY  - JOUR\nTI  - 中文文献去重测试\nAU  - 张伟\nAU  - 李娜\nAB  - 这是一条包含中文摘要，但末尾不同的记录。\nPY  - 2024\nER  - \n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
