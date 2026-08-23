"""NC_reimpl:全样例但零 import 上游 — provenance 必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'utf8_cn.txt': '{"encoding":"utf-8","confidence":0.99,"language":"","chardet_version":"5.2.0"}\n', 'gbk_cn.txt': '"encoding":"GB2312"', 'ascii.txt': '"encoding":"ascii"'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
