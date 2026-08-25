"""正控:全样例硬编码 — 只证明样例测试自洽可满足(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'daily.txt': '2026-01-05T09:00:00\n2026-01-06T09:00:00\n2026-01-07T09:00:00\n', 'weekly.txt': '2026-01-05T08:00:00\n2026-01-09T08:00:00\n2026-01-12T08:00:00\n2026-01-16T08:00:00\n2026-01-19T08:00:00\n', 'monthly.txt': '2026-01-31T12:00:00\n2026-03-31T12:00:00\n2026-05-31T12:00:00\n2026-07-31T12:00:00\n', 'until.txt': '2026-03-01T10:00:00\n2026-03-04T10:00:00\n2026-03-07T10:00:00\n2026-03-10T10:00:00\n2026-03-13T10:00:00\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
