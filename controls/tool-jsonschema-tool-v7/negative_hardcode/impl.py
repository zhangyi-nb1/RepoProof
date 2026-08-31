"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_valid_non_ascii': '{"error_count":0,"errors":[],"valid":true}', 'invalid_instance_value': '{"error_count":2,"errors":[{"depth":0,"instance_path":["name"],"instance_pointer":"/name","message":"42 is not of type \'string\'","schema_path":["properties","name","type"],"schema_pointer":"/properties/name/type","validator":"type"},{"depth":0,"instance_path":["price"],"instance_pointer":"/price","message":"\'免费\' is not of type \'number\'","schema_path":["properties","price","type"],"schema_pointer":"/properties/price/type","validator":"type"}],"valid":false}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
