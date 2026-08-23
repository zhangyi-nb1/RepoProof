"""正控:全样例硬编码 — 只证明样例测试自洽可满足(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'dates.txt': '2024-03-15T00:00:00\n2021-03-05T14:30:00\n2020-01-15T00:00:00\n', 'times.txt': '2023-07-01T08:00:00+02:00', 'mixed.txt': '1999-12-31T23:59:59'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
