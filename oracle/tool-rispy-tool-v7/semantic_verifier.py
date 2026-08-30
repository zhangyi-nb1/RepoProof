from pathlib import Path
import re
import rispy


_COMMITMENTS = [
    "stable-exact-record-deduplication",
    "unicode-field-preservation",
]
_FIELD_LINE = re.compile(r"^[A-Z0-9]{2}  -.*$")
_CONTINUATION_LINE = re.compile(r"^ {6}.*$")


def _result(ok, reason_codes, checked):
    return {
        "ok": bool(ok),
        "reason_codes": list(reason_codes),
        "checked_commitment_ids": list(checked),
    }


def _valid_ris_interchange(text):
    in_record = False
    complete_records = 0

    for line in text.splitlines():
        if not line:
            continue
        if _CONTINUATION_LINE.fullmatch(line):
            if not in_record:
                return False
            continue
        if not _FIELD_LINE.fullmatch(line):
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
                complete_records += 1

    return not in_record and complete_records >= 1


def _stable_deduplicated(records):
    retained = []
    for record in records:
        duplicate = False
        for prior in retained:
            if record == prior:
                duplicate = True
                break
        if not duplicate:
            retained.append(record)
    return retained


def _text_values_equal(expected, observed):
    if isinstance(expected, str) or isinstance(observed, str):
        return isinstance(expected, str) and isinstance(observed, str) and expected == observed
    if isinstance(expected, dict) and isinstance(observed, dict):
        if set(expected) != set(observed):
            return False
        return all(_text_values_equal(expected[key], observed[key]) for key in expected)
    if isinstance(expected, (list, tuple)) and isinstance(observed, (list, tuple)):
        if len(expected) != len(observed):
            return False
        return all(_text_values_equal(left, right) for left, right in zip(expected, observed))
    return expected == observed


def _unicode_preserved(expected_records, observed_records):
    if len(expected_records) != len(observed_records):
        return False
    return all(
        _text_values_equal(expected, observed)
        for expected, observed in zip(expected_records, observed_records)
    )


def verify(input_path: Path, artifact_path: Path) -> dict:
    try:
        input_text = Path(input_path).read_text(encoding="utf-8")
        artifact_text = Path(artifact_path).read_text(encoding="utf-8")
    except Exception:
        return _result(False, ["SEMANTIC_EVALUATION_UNAVAILABLE"], [])

    input_records = None
    artifact_records = None
    input_failed = False
    artifact_failed = False

    try:
        input_records = rispy.loads(input_text)
    except Exception:
        input_failed = True

    try:
        artifact_records = rispy.loads(artifact_text)
    except Exception:
        artifact_failed = True

    if input_failed or artifact_failed:
        return _result(False, ["UPSTREAM_SEMANTICS_UNAVAILABLE"], [])

    if not isinstance(input_records, list) or not isinstance(artifact_records, list):
        return _result(False, ["UPSTREAM_SEMANTICS_UNAVAILABLE"], [])

    checked = []
    try:
        expected_records = _stable_deduplicated(input_records)
        deduplication_ok = artifact_records == expected_records
        checked.append("stable-exact-record-deduplication")

        unicode_ok = _unicode_preserved(expected_records, artifact_records)
        checked.append("unicode-field-preservation")
    except Exception:
        return _result(False, ["SEMANTIC_EVALUATION_UNAVAILABLE"], checked)

    reasons = []
    if not _valid_ris_interchange(artifact_text):
        reasons.append("RIS_INTERCHANGE_PROFILE_INVALID")
    if not deduplication_ok:
        reasons.append("STABLE_EXACT_RECORD_DEDUPLICATION_FAILED")
    if not unicode_ok:
        reasons.append("UNICODE_FIELD_PRESERVATION_FAILED")

    return _result(not reasons, reasons, checked)
