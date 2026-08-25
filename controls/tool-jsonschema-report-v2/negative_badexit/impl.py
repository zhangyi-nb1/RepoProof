"""NC_badexit:坏输入不包装,裸奔→exit 2 — 接口契约必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'valid.json': '{\n  "error_count": 0,\n  "errors": [],\n  "valid": true\n}\n', 'missing.json': '{\n  "error_count": 1,\n  "errors": [\n    {\n      "message": "\'name\' is a required property",\n      "path": ""\n    }\n  ],\n  "valid": false\n}\n', 'nested.json': '{\n  "error_count": 2,\n  "errors": [\n    {\n      "message": "\'x\' is not of type \'integer\'",\n      "path": "/items/1"\n    },\n    {\n      "message": "\'y\' is not of type \'integer\'",\n      "path": "/items/3"\n    }\n  ],\n  "valid": false\n}\n', 'enum.json': '{\n  "error_count": 1,\n  "errors": [\n    {\n      "message": "\'blue\' is not one of [\'red\', \'green\']",\n      "path": "/color"\n    }\n  ],\n  "valid": false\n}\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    # 坏输入不包装:裸奔异常 → 骨架兜成 exit 2 → 接口契约测试必须抓
    return _M[input_path.name]
