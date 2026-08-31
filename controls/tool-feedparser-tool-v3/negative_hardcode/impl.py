"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_rss_nonascii.xml': '{"entries":[{"authors":[{"email":"a@example.test","href":"","name":"作者甲"},{"email":"b@example.test","href":"","name":"作者乙"}],"id":"post-一","link":"https://example.test/posts/1","published":{"raw":"Tue, 02 Jan 2024 03:04:05 +0800","utc":"2024-01-01T19:04:05Z"},"tags":[{"label":"","scheme":"","term":"Python"},{"label":"","scheme":"","term":"数据 处理"}],"title":"第一条 内容","updated":{"raw":"Tue, 02 Jan 2024 03:04:05 +0800","utc":"2024-01-01T19:04:05Z"}},{"authors":[],"id":"https://example.test/posts/2","link":"https://example.test/posts/2","published":{"raw":"Wed, 03 Jan 2024 00:00:00 GMT","utc":"2024-01-03T00:00:00Z"},"tags":[],"title":"第二条","updated":{"raw":"Wed, 03 Jan 2024 00:00:00 GMT","utc":"2024-01-03T00:00:00Z"}}],"feed":{"authors":[{"email":"editor@example.test","href":"","name":"编辑甲"}],"id":"","link":"https://example.test/feed","published":{"raw":"Tue, 02 Jan 2024 03:04:05 +0800","utc":"2024-01-01T19:04:05Z"},"tags":[{"label":"","scheme":"","term":"新闻"},{"label":"","scheme":"","term":"技术"}],"title":"示例 RSS 频道","updated":{"raw":"Tue, 02 Jan 2024 03:04:05 +0800","utc":"2024-01-01T19:04:05Z"}},"format":"rss20","warnings":[]}', 'malformed_atom_invalid_dates.xml': '{"entries":[{"authors":[{"email":"","href":"","name":"韩梅梅"}],"id":"urn:example:entry:1","link":"https://example.test/atom/1","published":{"raw":"2024-13-40T25:61:00Z","utc":"2025-01-01T00:00:00Z"},"tags":[{"label":"","scheme":"","term":"错误日期"}],"title":"未闭合条目","updated":{"raw":"2024-01-02T03:04:05+08:00","utc":"2024-01-01T19:04:05Z"}},{"authors":[],"id":"urn:example:entry:2","link":"urn:example:entry:2","published":{"raw":"","utc":""},"tags":[],"title":"后续条目","updated":{"raw":"2024-01-03T00:00:00Z","utc":"2024-01-03T00:00:00Z"}}],"feed":{"authors":[{"email":"","href":"","name":"李雷"}],"id":"urn:example:atom","link":"urn:example:atom","published":{"raw":"","utc":""},"tags":[{"label":"","scheme":"","term":"甲"},{"label":"","scheme":"","term":"乙"}],"title":"Atom 恢复测试","updated":{"raw":"not-a-date","utc":""}},"format":"atom10","warnings":[{"message":"<unknown>:22:7: not well-formed (invalid token)","type":"SAXParseException"}]}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
