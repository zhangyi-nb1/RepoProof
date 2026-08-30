from pathlib import Path
import csv
import math
import numbers
import pint


_COMMITMENTS = [
    "output-columns",
    "row-order-and-retention",
    "pint-conversion",
    "successful-row-status",
    "short-decimal-format",
    "pint-failure-preservation",
    "nonfinite-result-preservation",
]
_HEADER = ["样本名", "原数值", "目标单位", "换算结果", "状态", "说明"]


def _result(ok, codes, checked):
    return {
        "ok": bool(ok),
        "reason_codes": sorted(set(codes)),
        "checked_commitment_ids": checked,
    }


def _read_input(path):
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle, dialect="excel-tab", strict=True))
    header = rows[0]
    positions = {name: header.index(name) for name in ("样本名", "原数值", "目标单位")}
    return [(row[positions["样本名"]], row[positions["原数值"]], row[positions["目标单位"]]) for row in rows[1:]]


def _read_artifact(path):
    try:
        with Path(path).open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle, dialect="excel-tab", strict=True))
    except (OSError, UnicodeError, csv.Error):
        return None
    if not rows:
        return None
    header = rows[0]
    if not header or any(cell == "" for cell in header) or len(set(header)) != len(header):
        return None
    width = len(header)
    if any(len(row) != width for row in rows[1:]):
        return None
    return rows


def _expected_rows(input_rows):
    # UnitRegistry, Quantity parsing, and conversion are deliberately performed
    # through Pint rather than reproduced by this verifier.
    registry = pint.UnitRegistry()
    expected = []
    for sample, original, target in input_rows:
        try:
            quantity = registry.Quantity(original)
            converted = quantity.to(target)
            magnitude = converted.magnitude
        except pint.PintError as exc:
            expected.append({
                "input": (sample, original, target),
                "kind": "pint_failure",
                "exception_name": type(exc).__name__,
                "exception_text": str(exc),
            })
            continue
        except Exception:
            # This is an upstream evaluation failure, not a successful conversion.
            raise

        if not isinstance(magnitude, numbers.Real) or isinstance(magnitude, bool) or not math.isfinite(magnitude):
            expected.append({
                "input": (sample, original, target),
                "kind": "nonfinite",
            })
            continue

        rendered = format(magnitude, ".6f").rstrip("0").rstrip(".")
        expected.append({
            "input": (sample, original, target),
            "kind": "success",
            "result": rendered,
        })
    return expected


def verify(input_path: Path, artifact_path: Path) -> dict:
    # The input contract is a valid UTF-8 TSV and is intentionally a precondition
    # of this semantic verifier; Core owns invalid-input handling.
    input_rows = _read_input(input_path)

    try:
        expected = _expected_rows(input_rows)
    except Exception:
        return _result(False, ["UPSTREAM_EVALUATION_FAILED"], [])

    # All Pint-dependent row semantics have now been evaluated before any possible
    # artifact rejection is returned.
    transformation_checked = [
        "pint-conversion",
        "successful-row-status",
        "short-decimal-format",
        "pint-failure-preservation",
        "nonfinite-result-preservation",
    ]

    artifact_rows = _read_artifact(artifact_path)
    if artifact_rows is None:
        return _result(False, ["ARTIFACT_TSV_INVALID"], transformation_checked)

    codes = []
    if artifact_rows[0] != _HEADER:
        codes.append("OUTPUT_COLUMNS_MISMATCH")

    checked = list(_COMMITMENTS)
    if artifact_rows[0] == _HEADER:
        delivered = artifact_rows[1:]
        if len(delivered) != len(expected):
            codes.append("ROW_COUNT_MISMATCH")

        for index, item in enumerate(expected):
            if index >= len(delivered):
                break
            row = delivered[index]
            sample, original, target = item["input"]
            if row[0] != sample or row[1] != original or row[2] != target:
                codes.append("ROW_PRESERVATION_MISMATCH")

            if item["kind"] == "success":
                if row[3] != item["result"] or row[4] != "已换算" or row[5] != "":
                    codes.append("SUCCESS_ROW_MISMATCH")
            elif item["kind"] == "nonfinite":
                if row[3] != "" or row[4] != "未换算" or row[5] != "无法换算：结果不是有限实数":
                    codes.append("NONFINITE_ROW_MISMATCH")
            else:
                explanation = row[5]
                valid_explanation = (
                    explanation.startswith("无法换算：")
                    and item["exception_name"] in explanation
                    and (not item["exception_text"] or item["exception_text"] in explanation)
                )
                if row[3] != "" or row[4] != "未换算" or not valid_explanation:
                    codes.append("PINT_FAILURE_ROW_MISMATCH")

    return _result(not codes, codes, checked)
