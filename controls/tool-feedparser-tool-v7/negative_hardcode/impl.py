"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'atom_unicode_typical.xml': '{"entries":[{"authors":[{"email":"","href":"","name":"李四"}],"id":"urn:example:entry:1","link":"posts/1","published":{"raw":"2024-02-01T12:30:00Z","utc":"2024-02-01T12:30:00Z"},"tags":[{"label":"编程","scheme":"","term":"Python"}],"title":"第一 篇 Café","updated":{"raw":"2024-02-02T00:00:00Z","utc":"2024-02-02T00:00:00Z"}}],"feed":{"authors":[{"email":"zhang@example.com","href":"/作者","name":"张 三"}],"id":"urn:example:feed","link":"/首页","published":{"raw":"","utc":""},"tags":[{"label":"技术资讯","scheme":"/分类","term":"技术"}],"title":"Café 新闻","updated":{"raw":"2024-02-03T04:05:06+08:00","utc":"2024-02-02T20:05:06Z"}},"format":"atom10","warnings":[]}', 'recoverable_malformed_rss.xml': '{"entries":[{"authors":[],"id":"bad-1","link":"item/1","published":{"raw":"not-a-date","utc":""},"tags":[],"title":"损坏条目","updated":{"raw":"not-a-date","utc":""}}],"feed":{"authors":[],"id":"","link":"/feed","published":{"raw":"","utc":""},"tags":[],"title":"可恢复 RSS","updated":{"raw":"","utc":""}},"format":"rss20","warnings":[{"message":"<unknown>:12:6: mismatched tag","type":"SAXParseException"}]}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
