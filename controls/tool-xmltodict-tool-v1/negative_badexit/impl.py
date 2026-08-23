"""NC_badexit:坏输入不包装,裸奔→exit 2 — 接口契约必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'note.xml': '{\n  "note": {\n    "to": "Li",\n    "body": "你好"\n  }\n}\n', 'attrs.xml': '{\n  "cfg": {\n    "@env": "prod",\n    "item": {\n      "@id": "1",\n      "#text": "a"\n    }\n  }\n}\n', 'list.xml': '{\n  "r": {\n    "x": [\n      "1",\n      "2",\n      "3"\n    ]\n  }\n}\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    # 坏输入不包装:裸奔异常 → 骨架兜成 exit 2 → 接口契约测试必须抓
    return _M[input_path.name]
