"""NC_badexit:坏输入不包装,裸奔→exit 2 — 接口契约必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'rss_unicode_whitespace_invalid_date.xml': '{"entries":[{"authors":[{"email":"alice@example.test","href":"","name":"Alice Example"}],"id":"item-001","link":"/article/1","published":{"raw":"not a real date","utc":""},"tags":[{"label":"","scheme":"topic","term":"技术"}],"title":"第一 篇 条目","updated":{"raw":"Tue, 02 Jan 2024 03:04:05 GMT","utc":"2024-01-02T03:04:05Z"}}],"feed":{"authors":[],"id":"","link":"https://example.test/feed","published":{"raw":"","utc":""},"tags":[],"title":"Café 新闻","updated":{"raw":"","utc":""}},"format":"rss20","warnings":[]}', 'atom_recoverable_unclosed.xml': '{"entries":[{"authors":[{"email":"li@example.test","href":"","name":"李雷"}],"id":"urn:example:entry:1","link":"relative/item","published":{"raw":"2024-01-02T03:04:05+08:00","utc":"2024-01-01T19:04:05Z"},"tags":[{"label":"新闻","scheme":"urn:tag","term":"新闻"}],"title":"条目 & 内容","updated":{"raw":"2024-01-02T03:04:05+08:00","utc":"2024-01-01T19:04:05Z"}}],"feed":{"authors":[],"id":"urn:example:broken","link":"urn:example:broken","published":{"raw":"","utc":""},"tags":[],"title":"未闭合 Atom","updated":{"raw":"2024-01-02T03:04:05Z","utc":"2024-01-02T03:04:05Z"}},"format":"atom10","warnings":[{"message":"<unknown>:14:0: no element found","type":"SAXParseException"}]}', 'atom_complete_unicode.xml': '{"entries":[{"authors":[{"email":"taro@example.test","href":"https://example.test/people/taro","name":"山田 太郎"},{"email":"taro@example.test","href":"","name":"Renée"}],"id":"urn:example:entry:one","link":"https://example.test/base/posts/one","published":{"raw":"2024-06-01T01:02:03-05:00","utc":"2024-06-01T06:02:03Z"},"tags":[{"label":"技術ニュース","scheme":"","term":"技术"}],"title":"Résumé 第１篇","updated":{"raw":"invalid-date","utc":""}}],"feed":{"authors":[{"email":"owner@example.test","href":"https://example.test/owner","name":"Feed Owner"}],"id":"urn:example:feed:complete","link":"urn:example:feed:complete","published":{"raw":"","utc":""},"tags":[{"label":"发布","scheme":"urn:kind","term":"release"}],"title":"Café 更新","updated":{"raw":"2024-06-01T12:30:45+09:00","utc":"2024-06-01T03:30:45Z"}},"format":"atom10","warnings":[]}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    # 坏输入不包装:裸奔异常 → 骨架兜成 exit 2 → 接口契约测试必须抓
    return _M[input_path.name]
