"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'rss_unicode_whitespace_invalid_date.xml': '{"entries":[{"authors":[{"email":"alice@example.test","href":"","name":"Alice Example"}],"id":"item-001","link":"/article/1","published":{"raw":"not a real date","utc":""},"tags":[{"label":"","scheme":"topic","term":"技术"}],"title":"第一 篇 条目","updated":{"raw":"Tue, 02 Jan 2024 03:04:05 GMT","utc":"2024-01-02T03:04:05Z"}}],"feed":{"authors":[],"id":"","link":"https://example.test/feed","published":{"raw":"","utc":""},"tags":[],"title":"Café 新闻","updated":{"raw":"","utc":""}},"format":"rss20","warnings":[]}', 'atom_recoverable_unclosed.xml': '{"entries":[{"authors":[{"email":"li@example.test","href":"","name":"李雷"}],"id":"urn:example:entry:1","link":"relative/item","published":{"raw":"2024-01-02T03:04:05+08:00","utc":"2024-01-01T19:04:05Z"},"tags":[{"label":"新闻","scheme":"urn:tag","term":"新闻"}],"title":"条目 & 内容","updated":{"raw":"2024-01-02T03:04:05+08:00","utc":"2024-01-01T19:04:05Z"}}],"feed":{"authors":[],"id":"urn:example:broken","link":"urn:example:broken","published":{"raw":"","utc":""},"tags":[],"title":"未闭合 Atom","updated":{"raw":"2024-01-02T03:04:05Z","utc":"2024-01-02T03:04:05Z"}},"format":"atom10","warnings":[{"message":"<unknown>:14:0: no element found","type":"SAXParseException"}]}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
