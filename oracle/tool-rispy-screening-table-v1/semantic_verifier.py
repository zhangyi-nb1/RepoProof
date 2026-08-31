from pathlib import Path
import csv
import io
from collections.abc import Mapping
import rispy

_COMMITMENTS = [
    "fixed-csv-header",
    "record-order-and-index",
    "bibliographic-column-mapping",
    "authors-serialization",
    "missing-fields-encoding",
]
_HEADER = ["record_index", "title", "authors", "year", "doi", "type", "missing_fields"]


def _result(ok, reasons, checked):
    return {
        "ok": bool(ok),
        "reason_codes": reasons,
        "checked_commitment_ids": checked,
    }


def _text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _record_values(record):
    if not isinstance(record, Mapping):
        raise TypeError("rispy record is not a mapping")
    title = _text(record.get("title"))
    authors_value = record.get("authors")
    if authors_value is None:
        authors = ""
    elif isinstance(authors_value, list):
        authors = "; ".join(_text(value) for value in authors_value)
    else:
        authors = _text(authors_value)
    year = _text(record.get("year"))
    doi = _text(record.get("doi"))
    reference_type = _text(record.get("type_of_reference"))
    missing = ";".join(
        name for name, value in (
            ("title", title),
            ("authors", authors),
            ("year", year),
            ("doi", doi),
        ) if value == ""
    )
    return [title, authors, year, doi, reference_type, missing]


def verify(input_path: Path, artifact_path: Path) -> dict:
    # Confirm the public pinned release before using its public parser.
    try:
        if getattr(rispy, "__version__", None) != "0.10.0":
            return _result(False, ["UPSTREAM_VERSION_MISMATCH"], [])
        with Path(input_path).open("rb") as raw_input:
            source = io.TextIOWrapper(raw_input, encoding="utf-8", errors="strict", newline="")
            parsed = rispy.load(source)
        records = list(parsed)
    except Exception:
        return _result(False, ["UPSTREAM_PARSE_FAILED"], [])

    try:
        expected_values = [_record_values(record) for record in records]
    except Exception:
        return _result(False, ["UPSTREAM_RESULT_UNUSABLE"], [])

    # Artifact inspection deliberately follows the upstream call, including on
    # all artifact rejection paths.
    try:
        with Path(artifact_path).open("r", encoding="utf-8", errors="strict", newline="") as artifact_file:
            rows = list(csv.reader(artifact_file, strict=True))
    except (OSError, UnicodeError, csv.Error):
        return _result(False, ["ARTIFACT_CSV_INVALID"], [])

    if not rows:
        return _result(False, ["ARTIFACT_CSV_INVALID"], [])

    header = rows[0]
    data_rows = rows[1:]
    profile_valid = (
        bool(header)
        and all(cell.strip() != "" for cell in header)
        and len(set(header)) == len(header)
        and all(len(row) == len(header) for row in data_rows)
    )

    header_ok = header == _HEADER
    shape_ok = all(len(row) == 7 for row in data_rows)
    count_ok = len(data_rows) == len(expected_values)

    index_ok = shape_ok and count_ok and all(
        row[0] == str(position)
        for position, row in enumerate(data_rows, start=1)
    )
    bibliographic_ok = shape_ok and count_ok and all(
        row[1] == expected[0]
        and row[3] == expected[2]
        and row[4] == expected[3]
        and row[5] == expected[4]
        for row, expected in zip(data_rows, expected_values)
    )
    authors_ok = shape_ok and count_ok and all(
        row[2] == expected[1]
        for row, expected in zip(data_rows, expected_values)
    )
    missing_ok = shape_ok and count_ok and all(
        row[6] == expected[5]
        for row, expected in zip(data_rows, expected_values)
    )

    reasons = []
    if not profile_valid:
        reasons.append("ARTIFACT_CSV_PROFILE_INVALID")
    if not header_ok:
        reasons.append("FIXED_CSV_HEADER_MISMATCH")
    if not index_ok:
        reasons.append("RECORD_ORDER_OR_INDEX_MISMATCH")
    if not bibliographic_ok:
        reasons.append("BIBLIOGRAPHIC_COLUMN_MAPPING_MISMATCH")
    if not authors_ok:
        reasons.append("AUTHORS_SERIALIZATION_MISMATCH")
    if not missing_ok:
        reasons.append("MISSING_FIELDS_ENCODING_MISMATCH")

    return _result(not reasons, reasons, list(_COMMITMENTS))
