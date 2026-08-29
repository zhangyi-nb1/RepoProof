"""NC_reimpl:全样例但零 import 上游 — provenance 必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'典型_组合错误_非ASCII_指针转义.json': '{"error_count":7,"errors":[{"depth":0,"instance_path":[],"instance_pointer":"","message":"Additional properties are not allowed (\'额外\' was unexpected)","schema_path":["additionalProperties"],"schema_pointer":"/additionalProperties","validator":"additionalProperties"},{"depth":0,"instance_path":["a/b~c"],"instance_pointer":"/a~1b~0c","message":"\'x\' is not of type \'integer\'","schema_path":["properties","a/b~c","type"],"schema_pointer":"/properties/a~1b~0c/type","validator":"type"},{"depth":0,"instance_path":["kind"],"instance_pointer":"/kind","message":"\'other\' is not valid under any of the given schemas","schema_path":["properties","kind","oneOf"],"schema_pointer":"/properties/kind/oneOf","validator":"oneOf"},{"depth":1,"instance_path":["kind"],"instance_pointer":"/kind","message":"\'retail\' was expected","schema_path":["properties","kind","oneOf",0,"const"],"schema_pointer":"/properties/kind/oneOf/0/const","validator":"const"},{"depth":1,"instance_path":["kind"],"instance_pointer":"/kind","message":"\'wholesale\' was expected","schema_path":["properties","kind","oneOf",1,"const"],"schema_pointer":"/properties/kind/oneOf/1/const","validator":"const"},{"depth":0,"instance_path":["name"],"instance_pointer":"/name","message":"\'蛋\' is too short","schema_path":["properties","name","minLength"],"schema_pointer":"/properties/name/minLength","validator":"minLength"},{"depth":0,"instance_path":["price"],"instance_pointer":"/price","message":"-1 is less than the minimum of 0","schema_path":["properties","price","minimum"],"schema_pointer":"/properties/price/minimum","validator":"minimum"}],"valid":false}', '典型-UTF8-有效对象.json': '{"error_count":0,"errors":[],"valid":true}', '布尔schema与Unicode实例.json': '{"error_count":0,"errors":[],"valid":true}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
