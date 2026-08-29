"""NC_badexit:坏输入不包装,裸奔→exit 2 — 接口契约必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_mixed.md': '{"code_blocks":[{"content":"print(\'你好\')\\n","language":"python","order":3}],"headings":[{"level":1,"order":0,"text":"项目概览"},{"level":2,"order":4,"text":"安装"}],"links":[{"label":"文档","order":1,"target":"docs/guide.md"},{"label":"官网","order":2,"target":"https://example.com/"},{"label":"文档","order":5,"target":"docs/guide.md"}]}\n', 'malformed_unicode.md': '{"code_blocks":[{"content":"const 值 = \\"✓\\";\\n\\n[空目标]() 和 ![图片](img.png)\\n","language":"js","order":1}],"headings":[{"level":3,"order":0,"text":"Café 与 中文 强调"}],"links":[]}\n', 'typical_mixed_markdown.md': '{"code_blocks":[{"content":"print(\\"你好\\")\\n","language":"python","order":3},{"content":"plain text\\n","language":"","order":5}],"headings":[{"level":1,"order":0,"text":"标题 一"},{"level":2,"order":4,"text":"第二节"}],"links":[{"label":"相对链接","order":1,"target":"guide/intro.md"},{"label":"绝对链接","order":2,"target":"https://example.org/a?x=1"}]}\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    # 坏输入不包装:裸奔异常 → 骨架兜成 exit 2 → 接口契约测试必须抓
    return _M[input_path.name]
