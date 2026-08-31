"""NC_badexit:坏输入不包装,裸奔→exit 2 — 接口契约必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_hex.json': '{"blue":86,"digital_level":0,"grayscale":46,"green":52,"red":18,"sensor_state":"DARK","source_hex":"#123456"}', 'shorthand_mixed_case.json': '{"blue":204,"digital_level":1,"grayscale":184,"green":187,"red":170,"sensor_state":"LIGHT","source_hex":"#aabbcc"}', 'valid_goldenrod.json': '{"blue":32,"digital_level":1,"grayscale":166,"green":165,"red":218,"sensor_state":"LIGHT","source_hex":"#daa520"}', 'short_hex_green.json': '{"blue":0,"digital_level":1,"grayscale":150,"green":255,"red":0,"sensor_state":"LIGHT","source_hex":"#00ff00"}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    # 坏输入不包装:裸奔异常 → 骨架兜成 exit 2 → 接口契约测试必须抓
    return _M[input_path.name]
