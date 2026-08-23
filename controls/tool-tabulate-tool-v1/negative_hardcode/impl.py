"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'sales.csv': '| region   | units   | rep   |\n|----------|---------|-------|\n| North    | 120     | Ann   |\n| South    | 95      | Bob   |\n', 'codes.csv': '| 007'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
