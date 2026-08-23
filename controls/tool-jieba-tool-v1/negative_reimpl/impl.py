"""NC_reimpl:全样例但零 import 上游 — provenance 必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'sent1.txt': '我 来到 北京 清华大学\n', 'sent2.txt': '小明 硕士 毕业 于 中国科学院 计算所\n', 'tech.txt': '自然语言 处理 是 人工智能 的 重要 方向\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
