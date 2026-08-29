"""NC_empty:空实现 —— 样例断言必须拒绝它。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    return ""
