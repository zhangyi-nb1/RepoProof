"""NC_badexit:坏输入不包装,裸奔→exit 2 — 接口契约必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'all-statuses-duplicate-suites.zip': '{"filter":["passed","failed","error","skipped"],"suites":[{"errors":1,"failures":0,"name":"same-suite","passed":0,"skipped":1,"source":"alpha.xml","tests":2,"time":0.7},{"errors":0,"failures":1,"name":"same-suite","passed":1,"skipped":0,"source":"zeta.xml","tests":2,"time":0.30000000000000004}],"totals":{"errors":1,"failures":1,"passed":1,"skipped":1,"tests":4,"time":1.0}}\n', 'failed-and-skipped-filter.zip': '{"filter":["failed","skipped"],"suites":[{"errors":0,"failures":0,"name":"alpha","passed":0,"skipped":1,"source":"report-a.xml","tests":1,"time":3.0},{"errors":0,"failures":1,"name":"beta","passed":0,"skipped":0,"source":"report-b.xml","tests":1,"time":2.0}],"totals":{"errors":0,"failures":1,"passed":0,"skipped":1,"tests":2,"time":5.0}}\n', 'passed-only-unicode.zip': '{"filter":["passed"],"suites":[{"errors":0,"failures":0,"name":"支付流程","passed":1,"skipped":0,"source":"报告.xml","tests":1,"time":0.25}],"totals":{"errors":0,"failures":0,"passed":1,"skipped":0,"tests":1,"time":0.25}}\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    # 坏输入不包装:裸奔异常 → 骨架兜成 exit 2 → 接口契约测试必须抓
    return _M[input_path.name]
