"""NC_badexit:坏输入不包装,裸奔→exit 2 — 接口契约必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'basic.toml': '{\n  "owner": {\n    "age": 30,\n    "name": "Li"\n  },\n  "title": "示例"\n}\n', 'nested.toml': '{\n  "meta": {\n    "tags": [\n      "x",\n      "y"\n    ]\n  },\n  "servers": [\n    {\n      "host": "a",\n      "ports": [\n        80,\n        443\n      ]\n    },\n    {\n      "host": "b",\n      "ports": [\n        8080\n      ]\n    }\n  ]\n}\n', 'types.toml': '{\n  "count": 7,\n  "date": "2026-08-23",\n  "flag": true,\n  "name": "值",\n  "pi": 3.14\n}\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    # 坏输入不包装:裸奔异常 → 骨架兜成 exit 2 → 接口契约测试必须抓
    return _M[input_path.name]
