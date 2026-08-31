"""NC_reimpl:全样例但零 import 上游 — provenance 必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'structured-headings.docx': '{"blocks":[{"type":"paragraph","text":"Quarterly Brief","heading_level":null},{"type":"paragraph","text":"Overview","heading_level":1},{"type":"paragraph","text":"Café résumé — 你好","heading_level":null},{"type":"paragraph","text":"Details","heading_level":2}],"metadata":{"block_count":4,"paragraph_count":4,"heading_count":2,"table_count":0}}\n', 'merged-and-empty-cells.docx': '{"blocks":[{"type":"paragraph","text":"Merge matrix","heading_level":null},{"type":"table","rows":[[{"text":"Merged","row_span":1,"col_span":2},{"covered":true}],[{"text":"","row_span":1,"col_span":1},{"text":"Tail","row_span":1,"col_span":1}]]}],"metadata":{"block_count":2,"paragraph_count":1,"heading_count":0,"table_count":1}}\n', 'mixed-document-order.docx': '{"blocks":[{"type":"paragraph","text":"Before","heading_level":null},{"type":"table","rows":[[{"text":"A","row_span":1,"col_span":1}]]},{"type":"paragraph","text":"Between","heading_level":3},{"type":"table","rows":[[{"text":"B","row_span":1,"col_span":1},{"text":"C","row_span":1,"col_span":1}]]},{"type":"paragraph","text":"After","heading_level":null}],"metadata":{"block_count":5,"paragraph_count":3,"heading_count":1,"table_count":2}}\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
