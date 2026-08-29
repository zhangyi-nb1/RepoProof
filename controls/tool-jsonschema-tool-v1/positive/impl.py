"""正控:全样例硬编码 — 只证明样例测试自洽可满足(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'组合校验与非ASCII路径': '{"error_count":5,"errors":[{"depth":0,"instance_path":[],"instance_pointer":"","message":"Additional properties are not allowed (\'额外\' was unexpected)","schema_path":["additionalProperties"],"schema_pointer":"/additionalProperties","validator":"additionalProperties"},{"depth":0,"instance_path":["price"],"instance_pointer":"/price","message":"\'免费\' is not valid under any of the given schemas","schema_path":["properties","price","oneOf"],"schema_pointer":"/properties/price/oneOf","validator":"oneOf"},{"depth":1,"instance_path":["price"],"instance_pointer":"/price","message":"\'免费\' is not of type \'number\'","schema_path":["properties","price","oneOf",0,"type"],"schema_pointer":"/properties/price/oneOf/0/type","validator":"type"},{"depth":1,"instance_path":["price"],"instance_pointer":"/price","message":"\'免费\' does not match \'^[0-9]+$\'","schema_path":["properties","price","oneOf",1,"pattern"],"schema_pointer":"/properties/price/oneOf/1/pattern","validator":"pattern"},{"depth":0,"instance_path":["名~称/值"],"instance_pointer":"/名~0称~1值","message":"2 is not of type \'string\'","schema_path":["properties","名~称/值","type"],"schema_pointer":"/properties/名~0称~1值/type","validator":"type"}],"valid":false}', '组合校验与中文路径': '{"error_count":5,"errors":[{"depth":0,"instance_path":[],"instance_pointer":"","message":"Additional properties are not allowed (\'备注\' was unexpected)","schema_path":["additionalProperties"],"schema_pointer":"/additionalProperties","validator":"additionalProperties"},{"depth":0,"instance_path":["age"],"instance_pointer":"/age","message":"True is not valid under any of the given schemas","schema_path":["properties","age","anyOf"],"schema_pointer":"/properties/age/anyOf","validator":"anyOf"},{"depth":1,"instance_path":["age"],"instance_pointer":"/age","message":"True is not of type \'integer\'","schema_path":["properties","age","anyOf",0,"type"],"schema_pointer":"/properties/age/anyOf/0/type","validator":"type"},{"depth":1,"instance_path":["age"],"instance_pointer":"/age","message":"True is not of type \'string\'","schema_path":["properties","age","anyOf",1,"type"],"schema_pointer":"/properties/age/anyOf/1/type","validator":"type"},{"depth":0,"instance_path":["姓名"],"instance_pointer":"/姓名","message":"\'甲\' is too short","schema_path":["properties","姓名","minLength"],"schema_pointer":"/properties/姓名/minLength","validator":"minLength"}],"valid":false}', '含非ASCII和格式校验的常规对象': '{"error_count":0,"errors":[],"valid":true}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
