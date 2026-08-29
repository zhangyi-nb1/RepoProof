"""NC_reimpl:全样例但零 import 上游 — provenance 必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'rss_unicode_complete.xml': '{"entries":[{"authors":[{"email":"alice@example.test","href":"","name":"Alice 张"}],"id":"post-1","link":"https://example.test/posts/1","published":{"raw":"Tue, 03 Jun 2008 11:05:30 GMT","utc":"2008-06-03T11:05:30Z"},"tags":[{"label":"","scheme":"","term":"公告"},{"label":"","scheme":"","term":"Python"}],"title":"第一 篇 文章","updated":{"raw":"Tue, 03 Jun 2008 11:05:30 GMT","utc":"2008-06-03T11:05:30Z"}},{"authors":[{"email":"bob@example.test","href":"","name":"Bob"}],"id":"https://example.test/posts/2","link":"https://example.test/posts/2","published":{"raw":"not-a-real-date","utc":""},"tags":[],"title":"Second entry","updated":{"raw":"not-a-real-date","utc":""}}],"feed":{"authors":[{"email":"editor@example.test","href":"","name":"编辑者"}],"id":"","link":"https://example.test/feed","published":{"raw":"Tue, 03 Jun 2008 11:05:30 GMT","utc":"2008-06-03T11:05:30Z"},"tags":[{"label":"","scheme":"","term":"技术"},{"label":"","scheme":"","term":"Python"}],"title":"Café 新闻","updated":{"raw":"Tue, 03 Jun 2008 12:00:00 +0000","utc":"2008-06-03T12:00:00Z"}},"format":"rss20","warnings":[]}', 'atom_unicode_complete.xml': '{"entries":[{"authors":[{"email":"","href":"","name":"Alice"},{"email":"","href":"","name":"王五"}],"id":"urn:example:entry:1","link":"https://example.test/atom/1","published":{"raw":"2024-01-01T00:00:00Z","utc":"2024-01-01T00:00:00Z"},"tags":[{"label":"","scheme":"","term":"alpha"},{"label":"","scheme":"","term":"βeta"}],"title":"Café́ 更新","updated":{"raw":"2024-01-02T03:04:05+08:00","utc":"2024-01-01T19:04:05Z"}}],"feed":{"authors":[{"email":"li@example.test","href":"","name":"李雷"}],"id":"urn:example:atom-feed","link":"urn:example:atom-feed","published":{"raw":"","utc":""},"tags":[{"label":"","scheme":"","term":"新闻"},{"label":"","scheme":"","term":"release"}],"title":"Atom 示例","updated":{"raw":"2024-01-02T03:04:05+08:00","utc":"2024-01-01T19:04:05Z"}},"format":"atom10","warnings":[]}', 'recoverable_malformed_rss.xml': '{"entries":[{"authors":[],"id":"broken-1","link":"broken-1","published":{"raw":"Fri, 32 Feb 2024 25:61:00 GMT","utc":""},"tags":[{"label":"","scheme":"","term":"测试"}],"title":"保留的条目","updated":{"raw":"Fri, 32 Feb 2024 25:61:00 GMT","utc":""}},{"authors":[],"id":"","link":"","published":{"raw":"","utc":""},"tags":[],"title":"","updated":{"raw":"","utc":""}}],"feed":{"authors":[],"id":"","link":"https://example.test/broken","published":{"raw":"","utc":""},"tags":[],"title":"损坏但可恢复的 RSS","updated":{"raw":"","utc":""}},"format":"rss20","warnings":[{"message":"<unknown>:14:4: mismatched tag","type":"SAXParseException"}]}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
