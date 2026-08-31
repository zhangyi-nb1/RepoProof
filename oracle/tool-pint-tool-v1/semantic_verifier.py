import csv
from pathlib import Path

import pint


_INPUT_HEADER = ["样本名", "原数值", "目标单位"]
_OUTPUT_HEADER = ["样本名", "原数值", "目标单位", "换算结果", "状态", "说明"]


def _result(ok, codes, checked):
    return {
        "ok": bool(ok),
        "reason_codes": sorted(set(codes)),
        "checked_commitment_ids": checked,
    }


def _read_with_delimiter(path, delimiter):
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle, delimiter=delimiter, strict=True))


def _read_excel_tab(path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle, dialect="excel-tab", strict=True))


def _input_rows(input_path):
    candidates = []
    for delimiter in (",", "\t"):
        try:
            rows = _read_with_delimiter(input_path, delimiter)
        except (OSError, UnicodeError, csv.Error):
            continue
        if rows and rows[0] == _INPUT_HEADER:
            candidates.append(rows)
    if not candidates:
        return None
    rows = candidates[0]
    if any(len(row) != 3 or any(cell == "" for cell in row) for row in rows[1:]):
        return None
    return rows[1:]


def verify(input_path: Path, artifact_path: Path) -> dict:
    checked = []
    try:
        registry = pint.UnitRegistry()
    except Exception:
        return _result(False, ["UPSTREAM_FAILURE"], checked)

    source_rows = _input_rows(input_path)
    checked.append("input-table-layout")
    if source_rows is None:
        return _result(False, ["INPUT_TABLE_LAYOUT_INVALID"], checked)

    expected = []
    conversion_errors = (
        pint.UndefinedUnitError,
        pint.DimensionalityError,
        pint.OffsetUnitCalculusError,
        pint.LogarithmicUnitCalculusError,
        ValueError,
    )
    for sample, original, target in source_rows:
        try:
            quantity = registry.Quantity(original)
            converted = quantity.to(target)
        except conversion_errors as exc:
            expected.append((sample, original, target, "", "未换算", "无法换算：" + exc.__class__.__name__, False))
            continue
        except Exception:
            return _result(False, ["UPSTREAM_FAILURE"], checked)
        try:
            rendered = format(converted.magnitude, ".6g") + " " + target
        except Exception:
            return _result(False, ["UPSTREAM_FAILURE"], checked)
        expected.append((sample, original, target, rendered, "已换算", "", True))

    checked.extend([
        "pint-conversion",
        "successful-result-rendering",
        "unconvertible-row-reporting",
    ])

    try:
        artifact_rows = _read_excel_tab(artifact_path)
    except (OSError, UnicodeError, csv.Error):
        checked.append("excel-tab-output")
        return _result(False, ["ARTIFACT_TSV_INVALID"], checked)

    checked.append("excel-tab-output")
    profile_valid = bool(artifact_rows)
    if profile_valid:
        header = artifact_rows[0]
        profile_valid = (
            bool(header)
            and all(cell != "" for cell in header)
            and len(set(header)) == len(header)
            and all(len(row) == len(header) for row in artifact_rows[1:])
        )
    if not profile_valid:
        return _result(False, ["ARTIFACT_TSV_INVALID"], checked)

    codes = []
    if artifact_rows[0] != _OUTPUT_HEADER:
        codes.append("ROW_PRESERVATION_AND_ORDER_MISMATCH")

    actual_rows = artifact_rows[1:]
    if len(actual_rows) != len(expected):
        codes.append("ROW_PRESERVATION_AND_ORDER_MISMATCH")

    checked.append("row-preservation-and-order")
    comparable = min(len(actual_rows), len(expected))
    for index in range(comparable):
        actual = actual_rows[index]
        wanted = expected[index]
        if len(actual) != 6:
            codes.append("ROW_PRESERVATION_AND_ORDER_MISMATCH")
            continue
        if actual[:3] != list(wanted[:3]):
            codes.append("ROW_PRESERVATION_AND_ORDER_MISMATCH")
        if wanted[6]:
            if actual[4] != "已换算":
                codes.append("PINT_CONVERSION_MISMATCH")
            if actual[3] != wanted[3] or actual[5] != "":
                codes.append("SUCCESSFUL_RESULT_RENDERING_MISMATCH")
        else:
            if actual[3] != "" or actual[4] != "未换算" or actual[5] != wanted[5]:
                codes.append("UNCONVERTIBLE_ROW_REPORTING_MISMATCH")

    return _result(not codes, codes, checked)
