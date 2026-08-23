"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'basic.toml': '{\n  "owner": {\n    "age": 30,\n    "name": "Li"\n  },\n  "title": "示例"\n}\n', 'nested.toml': '{\n  "meta": {\n    "tags": [\n      "x",\n      "y"\n    ]\n  },\n  "servers": [\n    {\n      "host": "a",\n      "ports": [\n        80,\n        443\n      ]\n    },\n    {\n      "host": "b",\n      "ports": [\n        8080\n      ]\n    }\n  ]\n}\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
