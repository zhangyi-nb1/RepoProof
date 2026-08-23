"""正控:全样例硬编码 — 只证明样例测试自洽可满足(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'img.png.bin': '{"ext": "png", "mime": "image/png"}\n', 'anim.gif.bin': '{"ext": "gif", "mime": "image/gif"}\n', 'arch.zip.bin': '{"ext": "zip", "mime": "application/zip"}\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
