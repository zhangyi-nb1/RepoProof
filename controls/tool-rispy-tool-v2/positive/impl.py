"""正控:全样例硬编码 — 只证明样例测试自洽可满足(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'chinese_exact_duplicate.ris': 'TY  - JOUR\nTI  - 中文文献题名：测试\nAU  - 张, 三\nAB  - 含有中文摘要和 café 字符。\nPY  - 2024\nER  - \nTY  - JOUR\nTI  - 不同的后续文献\nAU  - 李, 四\nPY  - 2023\nER  - \n', 'chinese_exact_duplicate_and_distinct': 'TY  - JOUR\nTI  - 中文文献题名\nAU  - 王, 小明\nAB  - 这是一段中文摘要。\nPY  - 2024\nER  - \nTY  - JOUR\nTI  - 中文文献题名（修订版）\nAU  - 王, 小明\nAB  - 这是一段中文摘要。\nPY  - 2024\nER  - \n', 'chinese_exact_duplicate_records.ris': 'TY  - JOUR\nTI  - 中文文献题名：UTF-8 保存测试\nAU  - 王小明\nAU  - 李华\nPY  - 2024\nJO  - 测试期刊\nAB  - 这是一段中文摘要，含有标点：，。！\nER  - \nTY  - JOUR\nTI  - 独立的后续记录\nAU  - Zhang, Wei\nPY  - 2023\nER  - \n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
