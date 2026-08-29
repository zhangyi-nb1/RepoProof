"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_features.md': '{"headings":[{"level":1,"text":"项目 Alpha"},{"level":2,"text":"安装"}],"links":[{"href":"https://example.com/docs","text":"官方文档"},{"href":"/guide","text":"本地页"}],"code_blocks":[{"language":"python","code":"print(\\"你好\\")\\n"}]}', 'malformed_markdown.md': '{"headings":[{"level":1,"text":"标题"}],"links":[{"href":"","text":"空目标"}],"code_blocks":[{"language":"python","code":"x = 1\\n"}]}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
