"""NC_reimpl:全样例但零 import 上游 — provenance 必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'e1.txt': 'Great job :grinning_face: party :party_popper:\n', 'e2.txt': '午餐吃 :steaming_bowl: 还是 :sushi:?\n', 'e3.txt': 'Ship it :rocket: to the :globe_showing_Europe-Africa:\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
