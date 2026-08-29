"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'valid_unicode_object': '{"error_count":0,"errors":[],"valid":true}', 'nested_anyof_escaped_pointer': '{"error_count":3,"errors":[{"depth":0,"instance_path":["a/b~c"],"instance_pointer":"/a~1b~0c","message":"\'é\' is not valid under any of the given schemas","schema_path":["properties","a/b~c","anyOf"],"schema_pointer":"/properties/a~1b~0c/anyOf","validator":"anyOf"},{"depth":1,"instance_path":["a/b~c"],"instance_pointer":"/a~1b~0c","message":"\'é\' is not of type \'integer\'","schema_path":["properties","a/b~c","anyOf",0,"type"],"schema_pointer":"/properties/a~1b~0c/anyOf/0/type","validator":"type"},{"depth":1,"instance_path":["a/b~c"],"instance_pointer":"/a~1b~0c","message":"\'é\' does not match \'^[A-Z]+$\'","schema_path":["properties","a/b~c","anyOf",1,"pattern"],"schema_pointer":"/properties/a~1b~0c/anyOf/1/pattern","validator":"pattern"}],"valid":false}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
