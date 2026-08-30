from pathlib import Path
import re
import rispy

_COMMITMENTS = [
    "exact-parsed-record-deduplication",
    "retain-nonidentical-records",
    "preserve-retained-record-semantics",
    "preserve-chinese-unicode",
    "ris-record-only-output",
]
_FIELD = re.compile(r"^[A-Z0-9]{2}  -.*$")
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f]")


def _ris_interchange_text_is_valid(text):
    active = False
    complete_count = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("      "):
            if not active:
                return False
            continue
        if not _FIELD.fullmatch(line):
            return False
        tag = line[:2]
        if not active:
            if tag != "TY":
                return False
            active = True
            continue
        if tag == "TY":
            return False
        if tag == "ER":
            active = False
            complete_count += 1
    return (not active) and complete_count >= 1


def _first_occurrences(records):
    retained = []
    for record in records:
        if not any(record == prior for prior in retained):
            retained.append(record)
    return retained


def _chinese_leaves(value, path=()):
    if isinstance(value, str):
        if _HAN.search(value):
            return [(path, value)]
        return []
    if isinstance(value, dict):
        leaves = []
        for key, child in value.items():
            leaves.extend(_chinese_leaves(child, path + (("key", key),)))
        return leaves
    if isinstance(value, (list, tuple)):
        leaves = []
        for index, child in enumerate(value):
            leaves.extend(_chinese_leaves(child, path + (("index", index),)))
        return leaves
    return []


def _chinese_values_preserved(expected, delivered):
    if len(expected) != len(delivered):
        return False
    for source_record, output_record in zip(expected, delivered):
        if _chinese_leaves(source_record) != _chinese_leaves(output_record):
            return False
    return True


def verify(input_path: Path, artifact_path: Path) -> dict:
    input_text = input_path.read_text(encoding="utf-8")
    artifact_text = artifact_path.read_text(encoding="utf-8")

    input_records = None
    artifact_records = None
    parse_failed = False
    try:
        input_records = rispy.loads(input_text)
    except Exception:
        parse_failed = True
    try:
        artifact_records = rispy.loads(artifact_text)
    except Exception:
        parse_failed = True

    if parse_failed:
        return {
            "ok": False,
            "reason_codes": ["UPSTREAM_PARSE_FAILURE"],
            "checked_commitment_ids": [],
        }

    retained = _first_occurrences(input_records)
    exact_deduplication = artifact_records == retained

    retain_nonidentical = True
    for record in retained:
        if sum(output_record == record for output_record in artifact_records) != 1:
            retain_nonidentical = False
            break

    preserve_semantics = (
        len(artifact_records) == len(retained)
        and all(output_record == source_record
                for source_record, output_record in zip(retained, artifact_records))
    )
    preserve_chinese = _chinese_values_preserved(retained, artifact_records)
    ris_only = _ris_interchange_text_is_valid(artifact_text)

    reasons = []
    if not exact_deduplication:
        reasons.append("EXACT_PARSED_RECORD_DEDUPLICATION_FAILED")
    if not retain_nonidentical:
        reasons.append("RETAIN_NONIDENTICAL_RECORDS_FAILED")
    if not preserve_semantics:
        reasons.append("PRESERVE_RETAINED_RECORD_SEMANTICS_FAILED")
    if not preserve_chinese:
        reasons.append("PRESERVE_CHINESE_UNICODE_FAILED")
    if not ris_only:
        reasons.append("RIS_RECORD_ONLY_OUTPUT_FAILED")

    return {
        "ok": not reasons,
        "reason_codes": reasons,
        "checked_commitment_ids": list(_COMMITMENTS),
    }
