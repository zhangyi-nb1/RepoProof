"""NC_badexit:坏输入不包装,裸奔→exit 2 — 接口契约必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'config.yaml': '{\n  "replicas": 3,\n  "service": {\n    "name": "api",\n    "ports": [\n      8080,\n      8443\n    ],\n    "tls": true\n  },\n  "tags": [\n    "prod",\n    "critical"\n  ]\n}\n', 'simple.yaml': '"greeting": "你好"', 'list.yaml': '"beta"'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    # 坏输入不包装:裸奔异常 → 骨架兜成 exit 2 → 接口契约测试必须抓
    return _M[input_path.name]
