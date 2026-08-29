"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'two-pages-with-empty.pdf': '{"author":"Ada Example","bookmarks":[{"children":[{"children":[],"page_number":2,"title":"Empty Appendix"}],"page_number":1,"title":"Chapter One"}],"page_count":2,"pages":[{"page_number":1,"text":"First page text"},{"page_number":2,"text":""}],"title":"Alpha Index"}\n', 'single-page.pdf': '{"author":"Grace Example","bookmarks":[],"page_count":1,"pages":[{"page_number":1,"text":"Only one searchable page"}],"title":null}\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
