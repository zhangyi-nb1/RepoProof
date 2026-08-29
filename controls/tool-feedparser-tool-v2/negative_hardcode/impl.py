"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'rss_unicode_whitespace.xml': '{"entries":[{"authors":[{"email":"zhangsan@example.test","href":"","name":"张三"}],"id":"post-001","link":"https://example.test/posts/1","published":{"raw":"Tue, 05 Mar 2024 08:30:00 +0800","utc":"2024-03-05T00:30:00Z"},"tags":[{"label":"","scheme":"","term":"技术"},{"label":"","scheme":"","term":"Python"}],"title":"第一条 新闻","updated":{"raw":"Tue, 05 Mar 2024 08:30:00 +0800","utc":"2024-03-05T00:30:00Z"}},{"authors":[],"id":"https://example.test/posts/2","link":"https://example.test/posts/2","published":{"raw":"2024-03-04T12:00:00Z","utc":"2024-03-04T12:00:00Z"},"tags":[],"title":"Second item","updated":{"raw":"2024-03-04T12:00:00Z","utc":"2024-03-04T12:00:00Z"}}],"feed":{"authors":[],"id":"","link":"https://example.test/feed","published":{"raw":"","utc":""},"tags":[],"title":"新闻 聚合","updated":{"raw":"","utc":""}},"format":"rss20","warnings":[]}', 'atom_ordered_authors_tags.xml': '{"entries":[{"authors":[{"email":"","href":"","name":"Bob"},{"email":"","href":"","name":"李四"}],"id":"urn:example:entry:1","link":"https://example.test/e/1","published":{"raw":"2024-03-01T09:00:00Z","utc":"2024-03-01T09:00:00Z"},"tags":[{"label":"","scheme":"","term":"alpha"},{"label":"","scheme":"","term":"beta"}],"title":"Entry 一","updated":{"raw":"2024-03-02T09:30:00Z","utc":"2024-03-02T09:30:00Z"}}],"feed":{"authors":[{"email":"alice@example.test","href":"","name":"Alice"}],"id":"urn:example:feed","link":"urn:example:feed","published":{"raw":"","utc":""},"tags":[{"label":"发布","scheme":"","term":"release"}],"title":"Atom 示例","updated":{"raw":"2024-03-05T10:15:30+02:00","utc":"2024-03-05T08:15:30Z"}},"format":"atom10","warnings":[]}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
