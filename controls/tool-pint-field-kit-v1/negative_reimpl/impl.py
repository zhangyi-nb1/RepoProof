"""NC_reimpl:全样例但零 import 上游 — provenance 必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'mixed_valid_and_row_failures': '<?xml version="1.0" encoding="UTF-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml"><head><meta charset="utf-8" /><title>现场准备单</title></head><body><h1>现场准备单</h1><p id="summary">总行数：5；成功数：2；失败数：3</p><table id="preparation-list"><thead><tr><th>item</th><th>per_group_amount</th><th>groups</th><th>total_amount</th><th>status</th></tr></thead><tbody><tr data-input-row="1"><td>面粉</td><td>500 gram</td><td>3</td><td>1.5 kg</td><td>OK</td></tr><tr data-input-row="2"><td>水</td><td>2 liter</td><td>4</td><td>8000 ml</td><td>OK</td></tr><tr data-input-row="3"><td>mystery</td><td>1 blorp</td><td>2</td><td></td><td>UNKNOWN_UNIT</td></tr><tr data-input-row="4"><td>length</td><td>1 meter</td><td>1</td><td></td><td>DIMENSION_MISMATCH</td></tr><tr data-input-row="5"><td>bad-groups</td><td>5 gram</td><td>０</td><td></td><td>INVALID_GROUPS</td></tr></tbody></table></body></html>\n', 'typical_convertible_rows': '<?xml version="1.0" encoding="UTF-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml"><head><meta charset="utf-8" /><title>现场准备单</title></head><body><h1>现场准备单</h1><p id="summary">总行数：2；成功数：2；失败数：0</p><table id="preparation-list"><thead><tr><th>item</th><th>per_group_amount</th><th>groups</th><th>total_amount</th><th>status</th></tr></thead><tbody><tr data-input-row="1"><td>flour</td><td>250 gram</td><td>4</td><td>1 kg</td><td>OK</td></tr><tr data-input-row="2"><td>water</td><td>1.5 liter</td><td>3</td><td>4500 ml</td><td>OK</td></tr></tbody></table></body></html>\n', 'unicode_and_invalid_row_values': '<?xml version="1.0" encoding="UTF-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml"><head><meta charset="utf-8" /><title>现场准备单</title></head><body><h1>现场准备单</h1><p id="summary">总行数：4；成功数：1；失败数：3</p><table id="preparation-list"><thead><tr><th>item</th><th>per_group_amount</th><th>groups</th><th>total_amount</th><th>status</th></tr></thead><tbody><tr data-input-row="1"><td>抹茶</td><td>2 gram</td><td>5</td><td>10000 mg</td><td>OK</td></tr><tr data-input-row="2"><td>全角组数</td><td>1 meter</td><td>２</td><td></td><td>INVALID_GROUPS</td></tr><tr data-input-row="3"><td>空白数量</td><td>   </td><td>2</td><td></td><td>INVALID_QUANTITY</td></tr><tr data-input-row="4"><td>未知单位</td><td>3 blorp</td><td>1</td><td></td><td>UNKNOWN_UNIT</td></tr></tbody></table></body></html>\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
