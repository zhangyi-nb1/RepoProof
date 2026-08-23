"""正控:全样例硬编码 — 只证明样例测试自洽可满足(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'doc.md': '<h1>Title</h1>\n<p>Some <strong>bold</strong> and <em>em</em> text with <code>code</code>.</p>\n<ul>\n<li>one</li>\n<li>two</li>\n</ul>\n<p><a href="https://example.com">link</a></p>\n', 'quote.md': '<blockquote>', 'heading.md': '<h2>Second Level</h2>'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
