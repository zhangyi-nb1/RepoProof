"""正控:全样例硬编码 — 只证明样例测试自洽可满足(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_features.md': '{"headings":[{"level":1,"text":"项目 Alpha"},{"level":2,"text":"安装"}],"links":[{"href":"https://example.com/docs","text":"官方文档"},{"href":"/guide","text":"本地页"}],"code_blocks":[{"language":"python","code":"print(\\"你好\\")\\n"}]}', 'malformed_markdown.md': '{"headings":[{"level":1,"text":"标题"}],"links":[{"href":"","text":"空目标"}],"code_blocks":[{"language":"python","code":"x = 1\\n"}]}', 'no-language-nested.md': '{"headings":[{"level":4,"text":"Mixed title"}],"links":[{"href":"../x?q=1","text":"relative bold"}],"code_blocks":[{"language":"","code":"alpha < beta\\n"}]}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
