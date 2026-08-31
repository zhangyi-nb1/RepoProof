"""正控:全样例硬编码 — 只证明样例测试自洽可满足(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'unicode_duplicate_and_distinct.ris': 'TY  - JOUR\nTI  - 中文文献：量子计算与café\nAU  - 张三\nAU  - Müller, Jörg\nPY  - 2024\nKW  - 测试\nER  - \nTY  - JOUR\nTI  - 中文文献：量子计算与café\nAU  - 张三\nAU  - Müller, Jörg\nPY  - 2025\nKW  - 测试\nER  - \n', 'unicode_exact_duplicate_and_near_duplicate.ris': 'TY  - JOUR\nTI  - 中文文献标题：Unicode 与 RIS\nAU  - 王小明\nAU  - García, María\nPY  - 2024\nJO  - 测试期刊\nER  - \nTY  - JOUR\nTI  - 中文文献标题：Unicode 与 RIS\nAU  - 王小明\nAU  - García, María\nPY  - 2025\nJO  - 测试期刊\nER  - \n', 'unicode_distinct_and_exact_duplicate.ris': 'TY  - JOUR\nTI  - 中文题名：机器学习与研究\nAU  - 王, 小明\nPY  - 2024\nJO  - 测试期刊\nER  - \nTY  - JOUR\nTI  - 中文题名：机器学习与研究\nAU  - 王, 小明\nPY  - 2024\nJO  - 另一份期刊\nER  - \n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
