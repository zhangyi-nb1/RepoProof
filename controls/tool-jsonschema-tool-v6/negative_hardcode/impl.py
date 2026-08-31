"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_non_ascii_valid.json': '{"error_count":0,"errors":[],"valid":true}', 'nested_combinator_pointer.json': '{"error_count":4,"errors":[{"depth":0,"instance_path":["a/b"],"instance_pointer":"/a~1b","message":"False is not valid under any of the given schemas","schema_path":["properties","a/b","anyOf"],"schema_pointer":"/properties/a~1b/anyOf","validator":"anyOf"},{"depth":1,"instance_path":["a/b"],"instance_pointer":"/a~1b","message":"False is not of type \'string\'","schema_path":["properties","a/b","anyOf",0,"type"],"schema_pointer":"/properties/a~1b/anyOf/0/type","validator":"type"},{"depth":1,"instance_path":["a/b"],"instance_pointer":"/a~1b","message":"False is not of type \'integer\'","schema_path":["properties","a/b","anyOf",1,"type"],"schema_pointer":"/properties/a~1b/anyOf/1/type","validator":"type"},{"depth":0,"instance_path":["~code",1],"instance_pointer":"/~0code/1","message":"\'否\' is not of type \'boolean\'","schema_path":["properties","~code","items","type"],"schema_pointer":"/properties/~0code/items/type","validator":"type"}],"valid":false}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
