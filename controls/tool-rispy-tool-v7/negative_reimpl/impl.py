"""NC_reimpl:全样例但零 import 上游 — provenance 必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'stable_exact_duplicate.ris': 'TY  - JOUR\nAU  - Smith, Jane\nTI  - Stable deduplication example\nPY  - 2024\nER  - \nTY  - JOUR\nAU  - Smith, Jane\nTI  - Stable deduplication example\nPY  - 2025\nER  - \n', 'unicode_fields.ris': 'TY  - JOUR\nAU  - 王, 小明\nAU  - García, María\nTI  - 中文标题：文献管理与 Unicode café\nJO  - 测试期刊\nPY  - 2023\nAB  - 包含汉字、é、Ω 和 emoji 😀。\nER  - \nTY  - BOOK\nAU  - Müller, Jörg\nTI  - Einführung in die Bibliographie\nCY  - 北京\nPY  - 2022\nER  - \n', 'unicode_stable_duplicate.ris': 'TY  - JOUR\nTI  - 中文标题：稳定去重与Café\nAU  - 王, 小明\nPY  - 2024\nJO  - 测试期刊\nER  - \nTY  - JOUR\nTI  - Different record Ω\nAU  - García, Ana\nPY  - 2023\nER  - \n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
