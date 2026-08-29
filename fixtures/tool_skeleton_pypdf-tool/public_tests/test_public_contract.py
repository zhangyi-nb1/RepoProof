"""公开合同测试 — agent 可运行自测(由用户样例确定性编译;验收强度=用户样例级)"""
import os
import shlex
import subprocess
from pathlib import Path

_TOOL = os.environ["REPOPROOF_TOOL_BIN"]
_FIX = Path(__file__).resolve().parent / "fixtures"


def _run(args):
    return subprocess.run([_TOOL, *args], capture_output=True, text=True, timeout=120)


_ROOT_TYPE = 'object'


import json as _json

_JSON_ROOTS = ['array', 'json', 'object']

def _normalize_text(value: str) -> str:
    unified = value.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in unified.strip().splitlines())

def _canonical_json(value: str) -> str | None:
    try:
        parsed = _json.loads(value)
    except (TypeError, ValueError):
        return None
    return _json.dumps(parsed, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))

def compare_output(actual: str, expected: str, *, root_type: str = "text") -> tuple[bool, str]:
    if actual == expected:
        return True, "exact"

    kind = (root_type or "text").strip().lower()
    if kind in _JSON_ROOTS:
        a, e = _canonical_json(actual), _canonical_json(expected)
        # 期望值解析不出 → 说明人写的期望本身不满足合同,判不符并如实说明;
        # 实际输出解析不出 → 合同违约。两种都不许回落到文本比较去救。
        return (a is not None and e is not None and a == e), "json"

    if kind == "json_lines":
        a_lines = [_canonical_json(x) for x in _normalize_text(actual).splitlines()]
        e_lines = [_canonical_json(x) for x in _normalize_text(expected).splitlines()]
        ok = (a_lines == e_lines and all(x is not None for x in a_lines)
              and bool(a_lines))
        return ok, "json_lines"

    return _normalize_text(actual) == _normalize_text(expected), "text"



# RFC-011: independent validation of actual stdout (not expected/golden text).
import json as _rp_json
import math as _rp_math

_RP_OUTPUT_CONTRACT = {'media_type': 'application/json', 'root_type': 'object', 'required': {'author': 'any', 'bookmarks': 'array', 'page_count': 'integer', 'pages': 'array', 'title': 'any'}}


def _rp_reject_json_constant(constant):
    raise ValueError(f"non-standard JSON constant: {constant}")


def _rp_strict_json_float(value):
    parsed = float(value)
    if not _rp_math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number: {value}")
    return parsed


def _rp_json_loads(text):
    return _rp_json.loads(
        text,
        parse_constant=_rp_reject_json_constant,
        parse_float=_rp_strict_json_float,
    )


def _rp_type_ok(value, expected):
    if expected == "any":
        return True
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "null":
        return value is None
    return False


def _rp_validate_value(value, location):
    root = _RP_OUTPUT_CONTRACT["root_type"]
    required = _RP_OUTPUT_CONTRACT["required"]
    if root == "object" and not isinstance(value, dict):
        return [f"{location}: wrong_root expected=object"]
    if root == "array" and not isinstance(value, list):
        return [f"{location}: wrong_root expected=array"]
    if required and not isinstance(value, dict):
        return [f"{location}: wrong_root required_fields_need=object"]
    errors = []
    for field, field_type in required.items():
        if field not in value:
            errors.append(f"{location}: missing_required field={field}")
        elif not _rp_type_ok(value[field], field_type):
            errors.append(
                f"{location}: wrong_type field={field} expected={field_type}")
    return errors


def _assert_output_contract(text):
    root = _RP_OUTPUT_CONTRACT["root_type"]
    if root == "text":
        return
    errors = []
    if root == "json_lines":
        lines = [
            (i, line) for i, line in enumerate(text.splitlines(), 1) if line.strip()
        ]
        if not lines:
            errors.append("json_lines: no_nonempty_lines")
        for line_no, line in lines:
            try:
                value = _rp_json_loads(line)
            except ValueError:
                errors.append(f"line={line_no}: invalid_json")
                continue
            errors.extend(_rp_validate_value(value, f"line={line_no}"))
    else:
        try:
            value = _rp_json_loads(text)
        except ValueError:
            errors.append("document: invalid_json")
        else:
            errors.extend(_rp_validate_value(value, "document"))
    assert not errors, '[tool-output-contract]' + " " + "; ".join(errors)


def test_example_1():
    r = _run([str(_FIX / 'inputs/two-pages-with-empty.pdf')])
    assert r.returncode == 0, f"exit={r.returncode} stderr: {r.stderr[:300]}"
    _assert_output_contract(r.stdout)
    want = (_FIX / 'expected/two-pages-with-empty.expected.json').read_text(encoding="utf-8")
    ok, mode = compare_output(r.stdout, want, root_type=_ROOT_TYPE)
    assert ok, f"输出与期望文件 expected/two-pages-with-empty.expected.json 不符(判据={mode});实际前 200 字: {r.stdout[:200]}"


def test_example_2():
    r = _run([str(_FIX / 'inputs/single-page.pdf')])
    assert r.returncode == 0, f"exit={r.returncode} stderr: {r.stderr[:300]}"
    _assert_output_contract(r.stdout)
    want = (_FIX / 'expected/single-page.expected.json').read_text(encoding="utf-8")
    ok, mode = compare_output(r.stdout, want, root_type=_ROOT_TYPE)
    assert ok, f"输出与期望文件 expected/single-page.expected.json 不符(判据={mode});实际前 200 字: {r.stdout[:200]}"

