"""正控:全样例硬编码 — 只证明样例测试自洽可满足(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_non_ascii_valid.json': '{"error_count":0,"errors":[],"valid":true}', 'nested_combinator_pointer.json': '{"error_count":4,"errors":[{"depth":0,"instance_path":["a/b"],"instance_pointer":"/a~1b","message":"False is not valid under any of the given schemas","schema_path":["properties","a/b","anyOf"],"schema_pointer":"/properties/a~1b/anyOf","validator":"anyOf"},{"depth":1,"instance_path":["a/b"],"instance_pointer":"/a~1b","message":"False is not of type \'string\'","schema_path":["properties","a/b","anyOf",0,"type"],"schema_pointer":"/properties/a~1b/anyOf/0/type","validator":"type"},{"depth":1,"instance_path":["a/b"],"instance_pointer":"/a~1b","message":"False is not of type \'integer\'","schema_path":["properties","a/b","anyOf",1,"type"],"schema_pointer":"/properties/a~1b/anyOf/1/type","validator":"type"},{"depth":0,"instance_path":["~code",1],"instance_pointer":"/~0code/1","message":"\'否\' is not of type \'boolean\'","schema_path":["properties","~code","items","type"],"schema_pointer":"/properties/~0code/items/type","validator":"type"}],"valid":false}', 'local_ref_unicode_invalid_values.json': '{"error_count":6,"errors":[{"depth":0,"instance_path":[],"instance_pointer":"","message":"Additional properties are not allowed (\'额外\' was unexpected)","schema_path":["additionalProperties"],"schema_pointer":"/additionalProperties","validator":"additionalProperties"},{"depth":0,"instance_path":["名称"],"instance_pointer":"/名称","message":"42 is not of type \'string\'","schema_path":["properties","名称","type"],"schema_pointer":"/properties/名称/type","validator":"type"},{"depth":0,"instance_path":["数量"],"instance_pointer":"/数量","message":"\'两\' is not valid under any of the given schemas","schema_path":["properties","数量","oneOf"],"schema_pointer":"/properties/数量/oneOf","validator":"oneOf"},{"depth":1,"instance_path":["数量"],"instance_pointer":"/数量","message":"\'两\' is not of type \'integer\'","schema_path":["properties","数量","oneOf",0,"type"],"schema_pointer":"/properties/数量/oneOf/0/type","validator":"type"},{"depth":1,"instance_path":["数量"],"instance_pointer":"/数量","message":"\'两\' does not match \'^[A-Z]+$\'","schema_path":["properties","数量","oneOf",1,"pattern"],"schema_pointer":"/properties/数量/oneOf/1/pattern","validator":"pattern"},{"depth":0,"instance_path":["邮箱"],"instance_pointer":"/邮箱","message":"\'无效邮箱\' is not a \'email\'","schema_path":["properties","邮箱","format"],"schema_pointer":"/properties/邮箱/format","validator":"format"}],"valid":false}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
