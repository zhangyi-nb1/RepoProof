"""NC_badexit:坏输入不包装,裸奔→exit 2 — 接口契约必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'典型多来源颜色': '{"colors":["#daa520","#aabbcc","#ffffff","#123456","#0000ff"]}', '含非ASCII文本的HTML': '{"colors":["#000080"]}', '多元素颜色来源与重复顺序.html': '{"colors":["#556b2f","#ff00aa","#ffd700","#1a2b3c","#008080","#aabbcc","#ffffff","#daa520","#000080","#aabbcc"]}', 'typical_unicode_mixed_colors.html': '{"colors":["#daa520","#aabbcc","#ffffff","#123456","#000080","#008080","#ff00aa"]}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    # 坏输入不包装:裸奔异常 → 骨架兜成 exit 2 → 接口契约测试必须抓
    return _M[input_path.name]
