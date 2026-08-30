from pathlib import Path
import re
import rispy

_COMMITMENTS = [
    "exact-parsed-record-deduplication",
    "first-occurrence-order",
    "metadata-preservation",
    "chinese-unicode-preservation",
]
_FIELD = re.compile(r"^[A-Z0-9]{2}  -(?: .*)?$")


def _read_utf8(path):
    data = path.read_bytes()
    try:
        return data.decode("utf-8"), True
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace"), False


def _valid_ris_profile(text):
    in_record = False
    record_count = 0
    for line in text.splitlines():
        if not line:
            continue
        if line.startswith("      "):
            if not in_record:
                return False
            continue
        if not _FIELD.fullmatch(line):
            return False
        tag = line[:2]
        if tag == "TY":
            if in_record:
                return False
            in_record = True
            continue
        if tag == "ER":
            if not in_record:
                return False
            in_record = False
            record_count += 1
            continue
        if not in_record:
            return False
    return record_count > 0 and not in_record


def _first_records(records):
    kept = []
    for record in records:
        if not any(record == previous for previous in kept):
            kept.append(record)
    return kept


def _unicode_values_preserved(expected, actual):
    if isinstance(expected, str):
        return not any(ord(ch) > 127 for ch in expected) or actual == expected
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(
            key in actual and _unicode_values_preserved(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, (list, tuple)):
        return (
            isinstance(actual, type(expected))
            and len(expected) == len(actual)
            and all(_unicode_values_preserved(value, actual[index])
                    for index, value in enumerate(expected))
        )
    return True


def verify(input_path: Path, artifact_path: Path) -> dict:
    reasons = []
    checked = []
    try:
        input_text, input_utf8 = _read_utf8(input_path)
    except Exception:
        input_text, input_utf8 = "", False
    try:
        artifact_text, artifact_utf8 = _read_utf8(artifact_path)
    except Exception:
        artifact_text, artifact_utf8 = "", False

    input_records = None
    artifact_records = None
    input_parse_ok = False
    artifact_parse_ok = False
    try:
        input_records = rispy.loads(input_text)
        input_parse_ok = isinstance(input_records, list)
    except Exception:
        input_parse_ok = False
    try:
        artifact_records = rispy.loads(artifact_text)
        artifact_parse_ok = isinstance(artifact_records, list)
    except Exception:
        artifact_parse_ok = False

    if getattr(rispy, "__version__", None) != "0.10.0":
        reasons.append("UPSTREAM_VERSION_MISMATCH")
    if not artifact_utf8:
        reasons.append("OUTPUT_NOT_UTF8")
    if not _valid_ris_profile(artifact_text):
        reasons.append("OUTPUT_PROFILE_INVALID")

    if not input_utf8 or not input_parse_ok or not artifact_parse_ok:
        reasons.append("UPSTREAM_SEMANTICS_UNAVAILABLE")
        return {
            "ok": False,
            "reason_codes": sorted(set(reasons)),
            "checked_commitment_ids": checked,
        }

    if getattr(rispy, "__version__", None) != "0.10.0":
        return {
            "ok": False,
            "reason_codes": sorted(set(reasons)),
            "checked_commitment_ids": checked,
        }

    try:
        expected = _first_records(input_records)
        exact_deduplication = artifact_records == expected
        first_occurrence_order = (
            len(artifact_records) == len(expected)
            and all(artifact_records[index] == expected[index]
                    for index in range(len(expected)))
        )
        metadata_preserved = (
            len(artifact_records) == len(expected)
            and all(artifact_records[index] == expected[index]
                    for index in range(len(expected)))
        )
        unicode_preserved = (
            len(artifact_records) == len(expected)
            and all(_unicode_values_preserved(expected[index], artifact_records[index])
                    for index in range(len(expected)))
        )
        checked.extend(_COMMITMENTS)
    except Exception:
        reasons.append("SEMANTIC_COMPARISON_UNAVAILABLE")
        return {
            "ok": False,
            "reason_codes": sorted(set(reasons)),
            "checked_commitment_ids": checked,
        }

    if not exact_deduplication:
        reasons.append("EXACT_PARSED_RECORD_DEDUPLICATION_FAILED")
    if not first_occurrence_order:
        reasons.append("FIRST_OCCURRENCE_ORDER_FAILED")
    if not metadata_preserved:
        reasons.append("METADATA_PRESERVATION_FAILED")
    if not unicode_preserved:
        reasons.append("CHINESE_UNICODE_PRESERVATION_FAILED")

    return {
        "ok": not reasons,
        "reason_codes": sorted(set(reasons)),
        "checked_commitment_ids": checked,
    }
