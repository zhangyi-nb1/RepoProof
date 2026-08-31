"""NC_reimpl:全样例但零 import 上游 — provenance 必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'复杂依赖、重复边、环与非ASCII任务': 'task\tdirect_dependencies\tdirect_dependents\tdownstream_count\tready_now\tin_cycle\n发布\t1\t1\t1\tfalse\tfalse\n含,逗号\t1\t0\t0\tfalse\tfalse\n审核\t1\t0\t0\tfalse\tfalse\n循环乙\t1\t1\t1\tfalse\ttrue\n循环甲\t1\t1\t1\tfalse\ttrue\n构建\t1\t2\t4\tfalse\tfalse\n测试\t1\t1\t2\tfalse\tfalse\n独立\t0\t1\t1\ttrue\tfalse\n自环\t1\t1\t0\tfalse\ttrue\n获取\t0\t1\t5\ttrue\tfalse\n部署\t1\t0\t0\tfalse\tfalse\n', '典型依赖、重复边与环': 'task\tdirect_dependencies\tdirect_dependents\tdownstream_count\tready_now\tin_cycle\nA\t0\t1\t3\ttrue\tfalse\nB\t2\t1\t2\tfalse\ttrue\nC\t1\t1\t2\tfalse\ttrue\nD\t1\t1\t2\tfalse\ttrue\n', '非ASCII和保留空白任务名': 'task\tdirect_dependencies\tdirect_dependents\tdownstream_count\tready_now\tin_cycle\n  审核  \t1\t0\t0\tfalse\tfalse\néclair\t1\t0\t0\tfalse\tfalse\n前置\t0\t2\t2\ttrue\tfalse\n', '非ASCII任务、重复边与多种环': 'task\tdirect_dependencies\tdirect_dependents\tdownstream_count\tready_now\tin_cycle\nZ\t0\t0\t0\ttrue\tfalse\n乙\t1\t1\t1\tfalse\ttrue\n复核\t1\t0\t0\tfalse\tfalse\n实施\t1\t1\t1\tfalse\tfalse\n甲\t1\t1\t1\tfalse\ttrue\n计划\t0\t1\t2\ttrue\tfalse\n阻塞\t1\t1\t0\tfalse\ttrue\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
