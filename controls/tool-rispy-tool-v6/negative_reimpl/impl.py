"""NC_reimpl:全样例但零 import 上游 — provenance 必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_with_exact_duplicate.ris': 'TY  - JOUR\nAU  - Smith, Jane\nTI  - A reproducible study\nJO  - Journal of Examples\nPY  - 2023\nDO  - 10.1000/example.1\nER  - \nTY  - JOUR\nAU  - Smith, Jane\nAU  - Doe, John\nTI  - A related study\nJO  - Journal of Examples\nPY  - 2024\nER  - \n', 'unicode_and_similar_records.ris': 'TY  - JOUR\nAU  - 王小明\nAU  - Müller, Jörg\nTI  - 中文题名：Unicode、é和β的保存\nJO  - 国际文献学报\nPY  - 2022\nAB  - 包含中文、emoji 📚 与阿拉伯语 العربية。\nKW  - 文献管理\nKW  - Unicode\nER  - \nTY  - JOUR\nAU  - 王小明\nAU  - Müller, Jörg\nTI  - 中文题名：Unicode、é和β的保存\nJO  - 国际文献学报\nPY  - 2022\nAB  - 包含中文、emoji 📚 与阿拉伯语 العربية。\nKW  - Unicode\nKW  - 文献管理\nER  - \n', 'unicode_exact_duplicate_and_near_duplicate.ris': 'TY  - JOUR\nAU  - 王, 小明\nAU  - Smith, Jane\nTI  - 中文题名：RIS 去重与 Unicode 保留\nPY  - 2024\nJO  - 测试期刊\nER  - \nTY  - JOUR\nAU  - Smith, Jane\nAU  - 王, 小明\nTI  - 中文题名：RIS 去重与 Unicode 保留\nPY  - 2024\nJO  - 测试期刊\nER  - \n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
