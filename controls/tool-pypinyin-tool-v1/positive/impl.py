"""正控:全样例硬编码 — 只证明样例测试自洽可满足(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'cn1.txt': 'ni hao shi jie\nzhong wen chu li\n', 'cn2.txt': 'bai ri yi shan jin\nhuang he ru hai liu\n', 'mixed.txt': 'wo ai  Python  bian cheng\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
