"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_unicode_object': '{"error_count":0,"errors":[],"valid":true}', 'nested_combinators_and_pointer_escaping': '{"error_count":5,"errors":[{"depth":0,"instance_path":[],"instance_pointer":"","message":"Additional properties are not allowed (\'extra\' was unexpected)","schema_path":["additionalProperties"],"schema_pointer":"/additionalProperties","validator":"additionalProperties"},{"depth":0,"instance_path":["a/b"],"instance_pointer":"/a~1b","message":"True is not valid under any of the given schemas","schema_path":["properties","a/b","oneOf"],"schema_pointer":"/properties/a~1b/oneOf","validator":"oneOf"},{"depth":1,"instance_path":["a/b"],"instance_pointer":"/a~1b","message":"True is not of type \'string\'","schema_path":["properties","a/b","oneOf",0,"type"],"schema_pointer":"/properties/a~1b/oneOf/0/type","validator":"type"},{"depth":1,"instance_path":["a/b"],"instance_pointer":"/a~1b","message":"True is not of type \'integer\'","schema_path":["properties","a/b","oneOf",1,"type"],"schema_pointer":"/properties/a~1b/oneOf/1/type","validator":"type"},{"depth":0,"instance_path":["~key",1],"instance_pointer":"/~0key/1","message":"\'x\' is not of type \'number\'","schema_path":["properties","~key","items","type"],"schema_pointer":"/properties/~0key/items/type","validator":"type"}],"valid":false}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
