"""NC_reimpl:全样例但零 import 上游 — provenance 必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_two_records_with_duplicate': 'record_index,title,authors,year,doi,type,missing_fields\n1,First study,"Smith, Alice; Jones, Bob",2023,10.1000/example.1,JOUR,\n2,First study,"Smith, Alice; Jones, Bob",2023,10.1000/example.1,JOUR,\n', '非ASCII与空字段': 'record_index,title,authors,year,doi,type,missing_fields\n1,数据科学：café,"王, 小明; García, Ana",,,JOUR,year;doi\n2,,,2023,10.5555/ñ-测试,BOOK,title;authors\n', 'non_ascii_complete_single_record.ris': 'record_index,title,authors,year,doi,type,missing_fields\n1,非英语标题：Müller 的研究,"García, Ana; 李, 明",2024,10.1234/例子.测试,JOUR,\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
