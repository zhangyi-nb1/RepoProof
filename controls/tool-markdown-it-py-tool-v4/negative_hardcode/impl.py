"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_features.md': '{"headings":[{"level":1,"text":"主标题 文档"},{"level":2,"text":"次级 代码 标题"}],"links":[{"href":"docs/guide.md","text":"文档"},{"href":"/home","text":"首页"},{"href":"/home","text":"首页"}],"code_blocks":[{"language":"python","code":"print(\\"你好\\")\\n"},{"language":"","code":"plain fence\\n"}]}', 'unicode_and_malformed_markdown.md': '{"headings":[{"level":1,"text":"Café 与中文 片段"}],"links":[{"href":"../%E8%B7%AF%E5%BE%84","text":"多行\\n链接"}],"code_blocks":[{"language":"javascript","code":"const emoji = \\"😀\\";\\n"}]}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
