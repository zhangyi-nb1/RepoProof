"""正控:全样例硬编码 — 只证明样例测试自洽可满足(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'valid_unicode_object': '{"error_count":0,"errors":[],"valid":true}', 'nested_anyof_escaped_pointer': '{"error_count":3,"errors":[{"depth":0,"instance_path":["a/b~c"],"instance_pointer":"/a~1b~0c","message":"\'é\' is not valid under any of the given schemas","schema_path":["properties","a/b~c","anyOf"],"schema_pointer":"/properties/a~1b~0c/anyOf","validator":"anyOf"},{"depth":1,"instance_path":["a/b~c"],"instance_pointer":"/a~1b~0c","message":"\'é\' is not of type \'integer\'","schema_path":["properties","a/b~c","anyOf",0,"type"],"schema_pointer":"/properties/a~1b~0c/anyOf/0/type","validator":"type"},{"depth":1,"instance_path":["a/b~c"],"instance_pointer":"/a~1b~0c","message":"\'é\' does not match \'^[A-Z]+$\'","schema_path":["properties","a/b~c","anyOf",1,"pattern"],"schema_pointer":"/properties/a~1b~0c/anyOf/1/pattern","validator":"pattern"}],"valid":false}', 'in_document_ref_combinator_unicode': '{"error_count":4,"errors":[{"depth":0,"instance_path":["用户"],"instance_pointer":"/用户","message":"0 is less than the minimum of 1","schema_path":["properties","用户","minimum"],"schema_pointer":"/properties/用户/minimum","validator":"minimum"},{"depth":0,"instance_path":["联系"],"instance_pointer":"/联系","message":"\'无效☎\' is not valid under any of the given schemas","schema_path":["properties","联系","oneOf"],"schema_pointer":"/properties/联系/oneOf","validator":"oneOf"},{"depth":1,"instance_path":["联系"],"instance_pointer":"/联系","message":"\'无效☎\' is not a \'email\'","schema_path":["properties","联系","oneOf",0,"format"],"schema_pointer":"/properties/联系/oneOf/0/format","validator":"format"},{"depth":1,"instance_path":["联系"],"instance_pointer":"/联系","message":"\'无效☎\' does not match \'^\\\\\\\\+?[0-9 -]+$\'","schema_path":["properties","联系","oneOf",1,"pattern"],"schema_pointer":"/properties/联系/oneOf/1/pattern","validator":"pattern"}],"valid":false}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
