import csv
import html
import math
import re
import tokenize
from pathlib import Path

import pint
from pint.errors import DimensionalityError, PintError, UndefinedUnitError


class UserInputError(ValueError):
    pass


_REQUIRED_HEADER = ["item", "per_group_amount", "target_unit", "groups"]
_OUTPUT_HEADER = ["item", "per_group_amount", "groups", "total_amount", "status"]
_GROUPS_RE = re.compile(r"^[0-9]+$")
_ROW_INPUT_ERRORS = (
    PintError,
    ValueError,
    TypeError,
    ArithmeticError,
    AssertionError,
    tokenize.TokenError,
)


def _xml_chars_allowed(value: str) -> bool:
    return all(
        code == 0x9
        or code == 0xA
        or code == 0xD
        or 0x20 <= code <= 0xD7FF
        or 0xE000 <= code <= 0xFFFD
        or 0x10000 <= code <= 0x10FFFF
        for code in map(ord, value)
    )


def _finite_scalar(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _convert_row(
    registry: pint.UnitRegistry,
    amount_text: str,
    target_text: str,
    groups_text: str,
) -> tuple[str, str]:
    if _GROUPS_RE.fullmatch(groups_text) is None:
        return "", "INVALID_GROUPS"

    try:
        groups = int(groups_text, 10)
    except (ValueError, OverflowError):
        return "", "INVALID_GROUPS"
    if groups <= 0:
        return "", "INVALID_GROUPS"

    if not amount_text.strip():
        return "", "INVALID_QUANTITY"

    try:
        quantity = registry.Quantity(amount_text)
    except UndefinedUnitError:
        return "", "UNKNOWN_UNIT"
    except _ROW_INPUT_ERRORS:
        return "", "INVALID_QUANTITY"

    if not _finite_scalar(quantity.magnitude):
        return "", "INVALID_QUANTITY"

    if not target_text.strip():
        return "", "UNKNOWN_UNIT"

    try:
        target_unit = registry.Unit(target_text)
    except UndefinedUnitError:
        return "", "UNKNOWN_UNIT"
    except _ROW_INPUT_ERRORS:
        return "", "INVALID_QUANTITY"

    try:
        converted = (quantity * groups).to(target_unit)
    except UndefinedUnitError:
        return "", "UNKNOWN_UNIT"
    except DimensionalityError:
        return "", "DIMENSION_MISMATCH"
    except _ROW_INPUT_ERRORS:
        return "", "INVALID_QUANTITY"

    if not _finite_scalar(converted.magnitude):
        return "", "INVALID_QUANTITY"

    try:
        return format(converted, "~.6gP"), "OK"
    except _ROW_INPUT_ERRORS:
        return "", "INVALID_QUANTITY"


def _cell(value: str) -> str:
    return "<td>" + html.escape(value, quote=True) + "</td>"


def extract(input_path: Path) -> str:
    try:
        with input_path.open("r", encoding="utf-8", newline="") as source:
            rows = list(csv.reader(source, dialect="excel-tab", strict=True))
    except OSError as exc:
        raise UserInputError("无法读取输入 TSV") from exc
    except (UnicodeDecodeError, csv.Error) as exc:
        raise UserInputError("输入不是有效的 UTF-8 TSV") from exc

    if not rows:
        raise UserInputError("TSV 必须包含表头")
    if rows[0] != _REQUIRED_HEADER:
        raise UserInputError(
            "TSV 表头必须依次为 item、per_group_amount、target_unit、groups"
        )

    for row in rows[1:]:
        if len(row) != len(_REQUIRED_HEADER):
            raise UserInputError("每个 TSV 数据行必须恰有四列")
        if not all(_xml_chars_allowed(value) for value in row):
            raise UserInputError("TSV 含有不能写入 XHTML 的字符")

    registry = pint.UnitRegistry()
    rendered_rows: list[str] = []
    success_count = 0

    for ordinal, (item, amount, target_unit, groups) in enumerate(
        rows[1:], start=1
    ):
        total_amount, status = _convert_row(
            registry,
            amount,
            target_unit,
            groups,
        )
        if status == "OK":
            success_count += 1

        cells = [item, amount, groups, total_amount, status]
        rendered_rows.append(
            '<tr data-input-row="'
            + str(ordinal)
            + '">'
            + "".join(_cell(value) for value in cells)
            + "</tr>"
        )

    total_count = len(rows) - 1
    failed_count = total_count - success_count
    summary = (
        f"总行数：{total_count}；成功数：{success_count}；失败数：{failed_count}"
    )
    header = "".join("<th>" + label + "</th>" for label in _OUTPUT_HEADER)

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">'
        '<head><meta charset="utf-8" /><title>现场准备单</title></head>'
        '<body><h1>现场准备单</h1>'
        '<p id="summary">'
        + summary
        + "</p>"
        '<table id="preparation-list"><thead><tr>'
        + header
        + "</tr></thead><tbody>"
        + "".join(rendered_rows)
        + "</tbody></table></body></html>\n"
    )
