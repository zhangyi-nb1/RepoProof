"""NC_reimpl:全样例但零 import 上游 — provenance 必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_unicode_features.md': '{"headings":[{"level":1,"text":"总览 文档"},{"level":2,"text":"使用 markdown-it-py"},{"level":3,"text":"多行"}],"links":[{"href":"https://example.com/docs","text":"文档"},{"href":"https://example.org?q=%E6%B5%8B%E8%AF%95","text":"搜索引擎"}],"code_blocks":[{"language":"python","code":"print(\\"你好，世界\\")\\n"}]}', 'malformed_markdown.md': '{"headings":[{"level":1,"text":"未闭合的 [链接](https://example.com"}],"links":[{"href":"","text":"缺少目标"}],"code_blocks":[{"language":"javascript","code":"const 值 = \\"未闭合围栏\\";\\n"}]}', 'no-language-nested.md': '{"headings":[{"level":4,"text":"Mixed title"}],"links":[{"href":"../x?q=1","text":"relative bold"}],"code_blocks":[{"language":"","code":"alpha < beta\\n"}]}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
