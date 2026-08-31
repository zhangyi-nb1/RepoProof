"""NC_reimpl:全样例但零 import 上游 — provenance 必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'atom_unicode_typical.xml': '{"entries":[{"authors":[{"email":"","href":"","name":"李四"}],"id":"urn:example:entry:1","link":"posts/1","published":{"raw":"2024-02-01T12:30:00Z","utc":"2024-02-01T12:30:00Z"},"tags":[{"label":"编程","scheme":"","term":"Python"}],"title":"第一 篇 Café","updated":{"raw":"2024-02-02T00:00:00Z","utc":"2024-02-02T00:00:00Z"}}],"feed":{"authors":[{"email":"zhang@example.com","href":"/作者","name":"张 三"}],"id":"urn:example:feed","link":"/首页","published":{"raw":"","utc":""},"tags":[{"label":"技术资讯","scheme":"/分类","term":"技术"}],"title":"Café 新闻","updated":{"raw":"2024-02-03T04:05:06+08:00","utc":"2024-02-02T20:05:06Z"}},"format":"atom10","warnings":[]}', 'recoverable_malformed_rss.xml': '{"entries":[{"authors":[],"id":"bad-1","link":"item/1","published":{"raw":"not-a-date","utc":""},"tags":[],"title":"损坏条目","updated":{"raw":"not-a-date","utc":""}}],"feed":{"authors":[],"id":"","link":"/feed","published":{"raw":"","utc":""},"tags":[],"title":"可恢复 RSS","updated":{"raw":"","utc":""}},"format":"rss20","warnings":[{"message":"<unknown>:12:6: mismatched tag","type":"SAXParseException"}]}', 'rss_typical_unicode_invalid_dates.xml': '{"entries":[{"authors":[{"email":"author@example.com","href":"","name":"赵六"}],"id":"urn:test:2","link":"articles/2","published":{"raw":"Tue, 05 Mar 2024 01:02:03 GMT","utc":"2024-03-05T01:02:03Z"},"tags":[{"label":"","scheme":"分类","term":"人工智能"}],"title":"第二 篇 é","updated":{"raw":"not-a-valid-date","utc":""}}],"feed":{"authors":[{"email":"","href":"","name":"王 五"}],"id":"","link":"/新闻","published":{"raw":"","utc":""},"tags":[{"label":"","scheme":"/主题","term":"科技 动态"}],"title":"Résumé 日报","updated":{"raw":"2024-03-04T05:06:07+09:00","utc":"2024-03-03T20:06:07Z"}},"format":"rss20","warnings":[]}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
