"""NC_reimpl:全样例但零 import 上游 — provenance 必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'article.html': '# Quarterly Report\n\nRevenue grew by **12%** this quarter.\n\n- North region\n- South region\n', 'links.html': '[the documentation](https://example.com/docs)', 'nested.html': '2. Configure `app.toml`'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
