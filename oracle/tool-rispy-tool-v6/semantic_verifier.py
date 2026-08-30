from pathlib import Path
from io import StringIO
from collections.abc import Mapping
import re
import rispy


_COMMITMENTS = [
    "parse-ris-input",
    "exact-semantic-deduplication",
    "encounter-order-preserved",
    "no-enrichment-or-field-alteration",
    "unicode-field-preservation",
    "ris-record-only-output",
]
_TAG_LINE = re.compile(r"^[A-Z0-9]{2}  -.*$")


def _result(ok, reasons, checked):
    return {
        "ok": bool(ok),
        "reason_codes": sorted(set(reasons)),
        "checked_commitment_ids": checked,
    }


def _parse_with_rispy(text):
    # rispy.load is the public RIS parsing interface.  Materializing its
    # returned records makes all later decisions depend on upstream parsing.
    return list(rispy.load(StringIO(text)))


def _profile_is_ris_records_only(text):
    """Implement the public ris_interchange_v1 representation rules."""
    state = "outside"
    complete_records = 0

    for line in text.splitlines():
        if line == "":
            continue

        if line.startswith("      "):
            if state != "inside":
                return False
            continue

        if not _TAG_LINE.fullmatch(line):
            return False

        tag = line[:2]
        if state == "outside":
            if tag != "TY":
                return False
            state = "inside"
        else:
            if tag == "TY":
                return False
            if tag == "ER":
                state = "outside"
                complete_records += 1

    return state == "outside" and complete_records > 0


def _unique_first(records):
    """Use equality of the complete upstream-parsed record objects."""
    kept = []
    for record in records:
        if not any(record == prior for prior in kept):
            kept.append(record)
    return kept


def _unicode_leaves(value, path=()):
    """Return paths and values for all non-ASCII parsed string values."""
    leaves = []
    if isinstance(value, str):
        if any(ord(character) > 127 for character in value):
            leaves.append((path, value))
    elif isinstance(value, Mapping):
        for key, child in value.items():
            leaves.extend(_unicode_leaves(child, path + (("key", key),)))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            leaves.extend(_unicode_leaves(child, path + (("index", index),)))
    return leaves


def _value_at_path(value, path):
    current = value
    for kind, component in path:
        if kind == "key":
            if not isinstance(current, Mapping) or component not in current:
                return False, None
            current = current[component]
        else:
            if not isinstance(current, (list, tuple)) or component >= len(current):
                return False, None
            current = current[component]
    return True, current


def _unicode_preserved(expected, delivered):
    if len(expected) != len(delivered):
        return False
    for source_record, output_record in zip(expected, delivered):
        for path, source_value in _unicode_leaves(source_record):
            found, output_value = _value_at_path(output_record, path)
            if not found or output_value != source_value:
                return False
    return True


def verify(input_path: Path, artifact_path: Path) -> dict:
    try:
        input_text = Path(input_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return _result(False, ["INPUT_TEXT_UNAVAILABLE"], [])

    # This is deliberately an upstream call, rather than a local RIS parser.
    try:
        input_records = _parse_with_rispy(input_text)
    except Exception:
        return _result(False, ["UPSTREAM_INPUT_RIS_PARSE_FAILED"], ["parse-ris-input"])

    try:
        artifact_text = Path(artifact_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return _result(False, ["ARTIFACT_TEXT_UNAVAILABLE"], ["parse-ris-input"])

    # Parse the delivered file with the pinned public upstream before any
    # rejection based on its textual representation or record semantics.
    try:
        artifact_records = _parse_with_rispy(artifact_text)
    except Exception:
        profile_ok = _profile_is_ris_records_only(artifact_text)
        reasons = ["UPSTREAM_ARTIFACT_RIS_PARSE_FAILED"]
        if not profile_ok:
            reasons.append("RIS_RECORD_ONLY_OUTPUT_FAILED")
        return _result(False, reasons, ["parse-ris-input", "ris-record-only-output"])

    expected_records = _unique_first(input_records)
    profile_ok = _profile_is_ris_records_only(artifact_text)

    # Exact deduplication is checked against the complete parsed records,
    # including every mapped field and the order of values in lists.
    dedup_ok = (
        len(artifact_records) == len(expected_records)
        and all(output == expected for output, expected in zip(artifact_records, expected_records))
    )

    # This separately states the encounter-order property over the retained
    # first occurrences produced from upstream-parsed input records.
    order_ok = artifact_records == expected_records

    # Compare each corresponding retained record as a whole; this covers every
    # parsed bibliographic field rather than a selected metadata subset.
    fields_ok = (
        len(artifact_records) == len(expected_records)
        and all(output == expected for output, expected in zip(artifact_records, expected_records))
    )

    unicode_ok = _unicode_preserved(expected_records, artifact_records)

    reasons = []
    if not profile_ok:
        reasons.append("RIS_RECORD_ONLY_OUTPUT_FAILED")
    if not dedup_ok:
        reasons.append("EXACT_SEMANTIC_DEDUPLICATION_FAILED")
    if not order_ok:
        reasons.append("ENCOUNTER_ORDER_PRESERVED_FAILED")
    if not fields_ok:
        reasons.append("NO_ENRICHMENT_OR_FIELD_ALTERATION_FAILED")
    if not unicode_ok:
        reasons.append("UNICODE_FIELD_PRESERVATION_FAILED")

    return _result(not reasons, reasons, list(_COMMITMENTS))
