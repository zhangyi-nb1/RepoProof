"""正控:全样例硬编码 — 只证明样例测试自洽可满足(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'news.rss': 'title\tlink\nFirst Post\thttps://example.com/1\nSecond Post\thttps://example.com/2\n', 'blog.atom': 'Atom Entry', 'cn.rss': '每周简报 第一期'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
