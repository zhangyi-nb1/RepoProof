"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'valid.json': '{\n  "error_count": 0,\n  "errors": [],\n  "valid": true\n}\n', 'missing.json': '{\n  "error_count": 1,\n  "errors": [\n    {\n      "message": "\'name\' is a required property",\n      "path": ""\n    }\n  ],\n  "valid": false\n}\n', 'nested.json': '{\n  "error_count": 2,\n  "errors": [\n    {\n      "message": "\'x\' is not of type \'integer\'",\n      "path": "/items/1"\n    },\n    {\n      "message": "\'y\' is not of type \'integer\'",\n      "path": "/items/3"\n    }\n  ],\n  "valid": false\n}\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
