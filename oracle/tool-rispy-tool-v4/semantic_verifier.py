from pathlib import Path
import re
import rispy

_COMMITMENTS = [
    "parse-and-export-ris",
    "first-occurrence-order",
    "exact-parsed-record-deduplication",
    "retain-distinct-records",
    "surviving-record-semantics",
    "unicode-text-preservation",
]
_FIELD = re.compile(r"^[A-Z0-9]{2}  -.*$")
_CONTINUATION = re.compile(r"^ {6}.*$")


def _result(ok, reasons, checked):
    return {
        "ok": bool(ok),
        "reason_codes": sorted(set(reasons)),
        "checked_commitment_ids": checked,
    }


def _ris_structure_valid(text):
    in_record = False
    complete = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        if _CONTINUATION.match(line):
            if not in_record:
                return False
            continue
        if not _FIELD.match(line):
            return False
        tag = line[:2]
        if not in_record:
            if tag != "TY":
                return False
            in_record = True
        else:
            if tag == "TY":
                return False
            if tag == "ER":
                in_record = False
                complete += 1
    return not in_record and complete > 0


def _contains_unicode(value):
    if isinstance(value, str):
        return any(ord(character) > 127 for character in value)
    if isinstance(value, dict):
        return any(_contains_unicode(key) or _contains_unicode(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_unicode(item) for item in value)
    return False


def _unicode_projection(value):
    if isinstance(value, str):
        return value if _contains_unicode(value) else None
    if isinstance(value, dict):
        return {key: _unicode_projection(item) for key, item in value.items() if _contains_unicode(key) or _contains_unicode(item)}
    if isinstance(value, (list, tuple)):
        return [_unicode_projection(item) for item in value]
    return None


def _unique_first(records):
    result = []
    for record in records:
        if not any(record == earlier for earlier in result):
            result.append(record)
    return result


def verify(input_path: Path, artifact_path: Path) -> dict:
    try:
        input_text = Path(input_path).read_text(encoding="utf-8")
        input_records = rispy.loads(input_text)
    except Exception:
        return _result(False, ["UPSTREAM_INPUT_PARSE_FAILED"], [])

    if not isinstance(input_records, list):
        return _result(False, ["UPSTREAM_INPUT_RECORD_COLLECTION_UNAVAILABLE"], [])

    try:
        artifact_text = Path(artifact_path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return _result(False, ["ARTIFACT_NOT_UTF8"], [])

    try:
        artifact_records = rispy.loads(artifact_text)
    except Exception:
        return _result(False, ["PARSE_AND_EXPORT_RIS_FAILED"], [])

    if not isinstance(artifact_records, list):
        return _result(False, ["PARSE_AND_EXPORT_RIS_FAILED"], [])

    expected = _unique_first(input_records)
    reasons = []

    structure_ok = _ris_structure_valid(artifact_text)
    if not structure_ok:
        reasons.extend(["PARSE_AND_EXPORT_RIS_FAILED", "RIS_INTERCHANGE_STRUCTURE_INVALID"])

    expected_indices = []
    unknown_actual = False
    for record in artifact_records:
        matches = [index for index, expected_record in enumerate(expected) if record == expected_record]
        if matches:
            expected_indices.append(matches[0])
        else:
            unknown_actual = True

    if expected_indices != sorted(expected_indices):
        reasons.append("FIRST_OCCURRENCE_ORDER_MISMATCH")

    has_actual_duplicate = any(
        artifact_records[left] == artifact_records[right]
        for left in range(len(artifact_records))
        for right in range(left)
    )
    if has_actual_duplicate or artifact_records != expected:
        reasons.append("EXACT_PARSED_RECORD_DEDUPLICATION_MISMATCH")

    if any(sum(record == wanted for record in artifact_records) != 1 for wanted in expected):
        reasons.append("DISTINCT_RECORD_RETENTION_MISMATCH")

    if unknown_actual:
        reasons.append("SURVIVING_RECORD_SEMANTICS_MISMATCH")

    unicode_ok = True
    for index, expected_record in enumerate(expected):
        if _contains_unicode(expected_record):
            if index >= len(artifact_records) or _unicode_projection(artifact_records[index]) != _unicode_projection(expected_record):
                unicode_ok = False
                break
    if not unicode_ok:
        reasons.append("UNICODE_TEXT_PRESERVATION_MISMATCH")

    return _result(not reasons, reasons, list(_COMMITMENTS))
