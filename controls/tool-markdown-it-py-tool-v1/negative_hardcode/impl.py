"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_mixed.md': '{"code_blocks":[{"content":"print(\'你好\')\\n","language":"python","order":3}],"headings":[{"level":1,"order":0,"text":"项目概览"},{"level":2,"order":4,"text":"安装"}],"links":[{"label":"文档","order":1,"target":"docs/guide.md"},{"label":"官网","order":2,"target":"https://example.com/"},{"label":"文档","order":5,"target":"docs/guide.md"}]}\n', 'malformed_unicode.md': '{"code_blocks":[{"content":"const 值 = \\"✓\\";\\n\\n[空目标]() 和 ![图片](img.png)\\n","language":"js","order":1}],"headings":[{"level":3,"order":0,"text":"Café 与 中文 强调"}],"links":[]}\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
