"""NC_badexit:坏输入不包装,裸奔→exit 2 — 接口契约必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_internal_ref_unicode.json': '{"error_count":0,"errors":[],"valid":true}', 'nested_combinator_unicode.json': '{"error_count":5,"errors":[{"depth":0,"instance_path":["choice"],"instance_pointer":"/choice","message":"False is not valid under any of the given schemas","schema_path":["properties","choice","oneOf"],"schema_pointer":"/properties/choice/oneOf","validator":"oneOf"},{"depth":1,"instance_path":["choice"],"instance_pointer":"/choice","message":"False is not of type \'string\'","schema_path":["properties","choice","oneOf",0,"type"],"schema_pointer":"/properties/choice/oneOf/0/type","validator":"type"},{"depth":1,"instance_path":["choice"],"instance_pointer":"/choice","message":"False is not of type \'number\'","schema_path":["properties","choice","oneOf",1,"type"],"schema_pointer":"/properties/choice/oneOf/1/type","validator":"type"},{"depth":0,"instance_path":["用户","年龄"],"instance_pointer":"/用户/年龄","message":"16 is less than the minimum of 18","schema_path":["properties","用户","properties","年龄","minimum"],"schema_pointer":"/properties/用户/properties/年龄/minimum","validator":"minimum"},{"depth":0,"instance_path":["用户","昵称"],"instance_pointer":"/用户/昵称","message":"\'é\' is too short","schema_path":["properties","用户","properties","昵称","minLength"],"schema_pointer":"/properties/用户/properties/昵称/minLength","validator":"minLength"}],"valid":false}', 'nested_combinators_escaped_pointers.json': '{"error_count":5,"errors":[{"depth":0,"instance_path":["a/b~c",0],"instance_pointer":"/a~1b~0c/0","message":"0 is less than the minimum of 1","schema_path":["properties","a/b~c","items","minimum"],"schema_pointer":"/properties/a~1b~0c/items/minimum","validator":"minimum"},{"depth":0,"instance_path":["a/b~c",1],"instance_pointer":"/a~1b~0c/1","message":"\'二\' is not of type \'integer\'","schema_path":["properties","a/b~c","items","type"],"schema_pointer":"/properties/a~1b~0c/items/type","validator":"type"},{"depth":0,"instance_path":["选项"],"instance_pointer":"/选项","message":"None is not valid under any of the given schemas","schema_path":["properties","选项","anyOf"],"schema_pointer":"/properties/选项/anyOf","validator":"anyOf"},{"depth":1,"instance_path":["选项"],"instance_pointer":"/选项","message":"None is not of type \'string\'","schema_path":["properties","选项","anyOf",0,"type"],"schema_pointer":"/properties/选项/anyOf/0/type","validator":"type"},{"depth":1,"instance_path":["选项"],"instance_pointer":"/选项","message":"None is not of type \'object\'","schema_path":["properties","选项","anyOf",1,"type"],"schema_pointer":"/properties/选项/anyOf/1/type","validator":"type"}],"valid":false}'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    # 坏输入不包装:裸奔异常 → 骨架兜成 exit 2 → 接口契约测试必须抓
    return _M[input_path.name]
