"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_internal_ref_unicode.json': '{"error_count":0,"errors":[],"valid":true}', 'nested_combinator_unicode.json': '{"error_count":5,"errors":[{"depth":0,"instance_path":["choice"],"instance_pointer":"/choice","message":"False is not valid under any of the given schemas","schema_path":["properties","choice","oneOf"],"schema_pointer":"/properties/choice/oneOf","validator":"oneOf"},{"depth":1,"instance_path":["choice"],"instance_pointer":"/choice","message":"False is not of type \'string\'","schema_path":["properties","choice","oneOf",0,"type"],"schema_pointer":"/properties/choice/oneOf/0/type","validator":"type"},{"depth":1,"instance_path":["choice"],"instance_pointer":"/choice","message":"False is not of type \'number\'","schema_path":["properties","choice","oneOf",1,"type"],"schema_pointer":"/properties/choice/oneOf/1/type","validator":"type"},{"depth":0,"instance_path":["用户","年龄"],"instance_pointer":"/用户/年龄","message":"16 is less than the minimum of 18","schema_path":["properties","用户","properties","年龄","minimum"],"schema_pointer":"/properties/用户/properties/年龄/minimum","validator":"minimum"},{"depth":0,"instance_path":["用户","昵称"],"instance_pointer":"/用户/昵称","message":"\'é\' is too short","schema_path":["properties","用户","properties","昵称","minLength"],"schema_pointer":"/properties/用户/properties/昵称/minLength","validator":"minLength"}],"valid":false}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
