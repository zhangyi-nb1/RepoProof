"""NC_reimpl:全样例但零 import 上游 — provenance 必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_duplicate_unicode.ris': 'TY  - JOUR\nAU  - Wang, Wei\nTI  - 中文文献：机器学习与数据分析\nJO  - 测试期刊\nPY  - 2024\nDO  - 10.1000/example.1\nER  - \nTY  - JOUR\nAU  - Smith, Jane\nTI  - A reference with café and αβ\nJO  - Journal of Examples\nPY  - 2023\nER  - \n', 'duplicate_records.ris': 'TY  - JOUR\nTI  - Duplicate handling in reference exports\nAU  - Smith, Alice\nPY  - 2024\nJO  - Test Journal\nER  - \nTY  - BOOK\nTI  - A distinct retained record\nAU  - Jones, Bob\nPY  - 2023\nPB  - Example Press\nER  - \n', 'unicode_and_whitespace.ris': 'TY  - JOUR\nTI  - 中文题名：文献去重与 Unicode 保真\nAU  - 王, 小明\nAU  - García, María\nJO  - 测试期刊\nPY  - 2022\nAB  - 包含中文、é、β、😀 与末尾空格\nKW  - 中文关键词\nKW  - naïve café\nER  - \nTY  - JOUR\nTI  - Second record\nAU  - Müller, Jörg\nPY  - 2021\nER  - \n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
