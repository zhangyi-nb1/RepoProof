from pathlib import Path
import csv
import io
import math
import pint

_INPUT_HEADER = ["sample_name", "value", "source_unit", "target_unit"]
_OUTPUT_HEADER = _INPUT_HEADER + ["converted_value", "status", "reason"]


def _read_tsv(path: Path):
    data = path.read_bytes()
    text = data.decode("utf-8", errors="strict")
    return list(csv.reader(io.StringIO(text, newline=""), dialect="excel-tab", strict=True))


def verify(input_path: Path, artifact_path: Path) -> dict:
    checked = []
    reasons = []

    def check(commitment_id):
        if commitment_id not in checked:
            checked.append(commitment_id)

    def reject(code):
        if code not in reasons:
            reasons.append(code)

    # This public Pint call is deliberately performed before any artifact
    # rejection, so the verifier observes the supplied upstream runtime.
    try:
        registry = pint.UnitRegistry()
        probe = registry.Quantity(0.0, "dimensionless").to("dimensionless")
        if float(probe.magnitude) != 0.0:
            reject("UPSTREAM_EVALUATION_FAILURE")
            return {"ok": False, "reason_codes": reasons, "checked_commitment_ids": checked}
    except Exception:
        reject("UPSTREAM_EVALUATION_FAILURE")
        return {"ok": False, "reason_codes": reasons, "checked_commitment_ids": checked}

    try:
        input_rows = _read_tsv(input_path)
    except UnicodeDecodeError:
        reject("INPUT_NOT_EVALUABLE")
        return {"ok": False, "reason_codes": reasons, "checked_commitment_ids": checked}
    except (OSError, csv.Error):
        reject("INPUT_NOT_EVALUABLE")
        return {"ok": False, "reason_codes": reasons, "checked_commitment_ids": checked}

    check("input-columns")
    input_is_table = (
        len(input_rows) >= 2
        and input_rows[0] == _INPUT_HEADER
        and all(len(row) == len(_INPUT_HEADER) for row in input_rows[1:])
    )
    if not input_is_table:
        reject("INPUT_NOT_EVALUABLE")
        return {"ok": False, "reason_codes": reasons, "checked_commitment_ids": checked}

    numeric_values = []
    check("finite-numeric-values")
    for row in input_rows[1:]:
        try:
            value = float(row[1])
        except (TypeError, ValueError):
            reject("INPUT_NOT_EVALUABLE")
            return {"ok": False, "reason_codes": reasons, "checked_commitment_ids": checked}
        if not math.isfinite(value):
            reject("INPUT_NOT_EVALUABLE")
            return {"ok": False, "reason_codes": reasons, "checked_commitment_ids": checked}
        numeric_values.append(value)

    check("pint-conversion")
    check("compact-number-format")
    check("unconvertible-row")
    expected_rows = []
    for row, value in zip(input_rows[1:], numeric_values):
        sample_name, original_value, source_unit, target_unit = row
        try:
            converted = registry.Quantity(value, source_unit).to(target_unit)
            converted_text = format(converted.magnitude, ".6g")
            expected_rows.append(
                [sample_name, original_value, source_unit, target_unit,
                 converted_text, "converted", ""]
            )
        except pint.PintError as exc:
            expected_rows.append(
                [sample_name, original_value, source_unit, target_unit,
                 "", "unconverted", f"{type(exc).__name__}: {exc}"]
            )
        except Exception:
            reject("UPSTREAM_EVALUATION_FAILURE")
            return {"ok": False, "reason_codes": reasons, "checked_commitment_ids": checked}

    try:
        artifact_rows = _read_tsv(artifact_path)
    except UnicodeDecodeError:
        reject("ARTIFACT_NOT_UTF8")
        return {"ok": False, "reason_codes": reasons, "checked_commitment_ids": checked}
    except (OSError, csv.Error):
        reject("ARTIFACT_TSV_INVALID")
        return {"ok": False, "reason_codes": reasons, "checked_commitment_ids": checked}

    if not artifact_rows:
        reject("ARTIFACT_TSV_INVALID")
        return {"ok": False, "reason_codes": reasons, "checked_commitment_ids": checked}
    artifact_header = artifact_rows[0]
    if (not artifact_header or any(cell == "" for cell in artifact_header)
            or len(set(artifact_header)) != len(artifact_header)
            or any(len(row) != len(artifact_header) for row in artifact_rows[1:])):
        reject("ARTIFACT_TSV_INVALID")
        return {"ok": False, "reason_codes": reasons, "checked_commitment_ids": checked}

    check("row-preservation")
    if artifact_header != _OUTPUT_HEADER:
        reject("OUTPUT_HEADER_MISMATCH")
    if len(artifact_header) != len(_OUTPUT_HEADER):
        reject("OUTPUT_SCHEMA_MISMATCH")
    if len(artifact_rows) - 1 != len(expected_rows):
        reject("ROW_COUNT_MISMATCH")

    for index, expected in enumerate(expected_rows):
        if index >= len(artifact_rows) - 1:
            break
        actual = artifact_rows[index + 1]
        if len(actual) < 4 or actual[:4] != expected[:4]:
            reject("ORIGINAL_COLUMNS_NOT_PRESERVED")
        if len(actual) != len(_OUTPUT_HEADER):
            reject("OUTPUT_SCHEMA_MISMATCH")
            continue
        if expected[5] == "converted":
            if actual[4:] != expected[4:]:
                reject("CONVERTED_ROW_MISMATCH")
        else:
            if actual[4:] != expected[4:]:
                reject("UNCONVERTED_ROW_MISMATCH")

    return {"ok": not reasons, "reason_codes": reasons, "checked_commitment_ids": checked}
