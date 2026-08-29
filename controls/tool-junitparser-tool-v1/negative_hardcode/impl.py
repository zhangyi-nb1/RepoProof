"""NC_hardcode:只硬编码公开样例 — held-out 必须杀它(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'all-statuses-duplicate-suites.zip': '{"filter":["passed","failed","error","skipped"],"suites":[{"errors":1,"failures":0,"name":"same-suite","passed":0,"skipped":1,"source":"alpha.xml","tests":2,"time":0.7},{"errors":0,"failures":1,"name":"same-suite","passed":1,"skipped":0,"source":"zeta.xml","tests":2,"time":0.30000000000000004}],"totals":{"errors":1,"failures":1,"passed":1,"skipped":1,"tests":4,"time":1.0}}\n', 'failed-and-skipped-filter.zip': '{"filter":["failed","skipped"],"suites":[{"errors":0,"failures":0,"name":"alpha","passed":0,"skipped":1,"source":"report-a.xml","tests":1,"time":3.0},{"errors":0,"failures":1,"name":"beta","passed":0,"skipped":0,"source":"report-b.xml","tests":1,"time":2.0}],"totals":{"errors":0,"failures":1,"passed":0,"skipped":1,"tests":2,"time":5.0}}\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
