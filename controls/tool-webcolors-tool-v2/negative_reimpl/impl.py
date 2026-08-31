"""NC_reimpl:全样例但零 import 上游 — provenance 必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical-colors.html': '{"colors":[{"grayscale":32,"hex":"#112233","rgb":[17,34,51]},{"grayscale":47,"hex":"#123456","rgb":[18,52,86]},{"grayscale":167,"hex":"#daa520","rgb":[218,165,32]},{"grayscale":255,"hex":"#ffffff","rgb":[255,255,255]}],"count":4}', 'unicode-inline.html': '{"colors":[{"grayscale":0,"hex":"#000000","rgb":[0,0,0]},{"grayscale":110,"hex":"#0080ff","rgb":[0,128,255]},{"grayscale":182,"hex":"#00ff00","rgb":[0,255,0]},{"grayscale":200,"hex":"#abcdef","rgb":[171,205,239]},{"grayscale":255,"hex":"#ffffff","rgb":[255,255,255]}],"count":5}', 'typical-mixed-colors.html': '{"colors":[{"grayscale":9,"hex":"#000080","rgb":[0,0,128]},{"grayscale":182,"hex":"#00ff00","rgb":[0,255,0]},{"grayscale":20,"hex":"#0102ff","rgb":[1,2,255]},{"grayscale":30,"hex":"#102030","rgb":[16,32,48]},{"grayscale":185,"hex":"#aabbcc","rgb":[170,187,204]},{"grayscale":130,"hex":"#ff6347","rgb":[255,99,71]}],"count":6}', 'upstream-evidence-3.txt': '{"colors":[],"count":0}', 'upstream-evidence-1.txt': '{"colors":[],"count":0}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
