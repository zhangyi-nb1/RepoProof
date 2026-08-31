"""正控:全样例硬编码 — 只证明样例测试自洽可满足(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'two-pages-with-empty.pdf': '{"metadata":{"author":"Ada Example","title":"Alpha Index"},"outlines":[{"level":0,"page_number":1,"title":"Chapter One"},{"level":1,"page_number":2,"title":"Empty Appendix"}],"pages":[{"page_number":1,"text":"First page text"},{"page_number":2,"text":""}]}\n', 'single-page.pdf': '{"metadata":{"author":"Grace Example","title":null},"outlines":[],"pages":[{"page_number":1,"text":"Only one searchable page"}]}\n', 'three-pages-middle-empty.pdf': '{"metadata":{"author":null,"title":"Three Page Report"},"outlines":[{"level":0,"page_number":1,"title":"Start"},{"level":0,"page_number":3,"title":"Finish"}],"pages":[{"page_number":1,"text":"Opening page"},{"page_number":2,"text":""},{"page_number":3,"text":"Closing page"}]}\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
