from pathlib import Path
import re
import rispy


_COMMITMENTS = [
    "ris-reexport",
    "exact-duplicate-definition",
    "retain-first-exact-duplicate",
    "preserve-surviving-order",
    "unicode-chinese-preservation",
]
_TAG = re.compile(r"^[A-Z0-9]{2}  -(?: ?.*)?$")


def _result(ok, reason_codes, checked):
    return {
        "ok": bool(ok),
        "reason_codes": list(reason_codes),
        "checked_commitment_ids": list(checked),
    }


def _is_chinese(char):
    point = ord(char)
    return (
        0x3400 <= point <= 0x4DBF
        or 0x4E00 <= point <= 0x9FFF
        or 0xF900 <= point <= 0xFAFF
        or 0x20000 <= point <= 0x2A6DF
        or 0x2A700 <= point <= 0x2B73F
        or 0x2B740 <= point <= 0x2B81F
        or 0x2B820 <= point <= 0x2CEAF
        or 0x30000 <= point <= 0x3134F
    )


def _chinese_runs(value):
    if isinstance(value, str):
        runs = []
        current = []
        for char in value:
            if _is_chinese(char):
                current.append(char)
            elif current:
                runs.append("".join(current))
                current = []
        if current:
            runs.append("".join(current))
        return runs
    if isinstance(value, dict):
        runs = []
        for item in value.values():
            runs.extend(_chinese_runs(item))
        return runs
    if isinstance(value, (list, tuple)):
        runs = []
        for item in value:
            runs.extend(_chinese_runs(item))
        return runs
    return []


def _is_ris_interchange_text(text):
    """Check RIS record framing while permitting standard continuation lines."""
    if not text:
        return True

    active = False
    completed = 0
    for line in text.splitlines():
        if not line:
            if active:
                return False
            continue

        if _TAG.fullmatch(line):
            tag = line[:2]
            if tag == "TY":
                if active:
                    return False
                active = True
            elif tag == "ER":
                if not active:
                    return False
                active = False
                completed += 1
            elif not active:
                return False
        elif not active:
            return False

    return not active and completed > 0


def _individual_exports(records):
    """Canonical record identities are defined by the pinned rispy writer."""
    return [rispy.dumps([record]) for record in records]


def verify(input_path: Path, artifact_path: Path) -> dict:
    try:
        input_text = input_path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return _result(False, ["INPUT_NOT_UTF8"], [])
    except OSError:
        return _result(False, ["INPUT_READ_FAILED"], [])

    try:
        input_records = list(rispy.loads(input_text))
        input_exports = _individual_exports(input_records)
    except Exception:
        return _result(False, ["INPUT_RIS_PARSE_FAILED"], ["ris-reexport"])

    # Deduplicate solely by the separately serialized upstream RIS record.
    seen = set()
    survivors = []
    expected_exports = []
    for record, exported in zip(input_records, input_exports):
        if exported not in seen:
            seen.add(exported)
            survivors.append(record)
            expected_exports.append(exported)

    source_chinese_runs = []
    for record in survivors:
        source_chinese_runs.extend(_chinese_runs(record))

    try:
        artifact_text = artifact_path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return _result(False, ["ARTIFACT_NOT_UTF8"], _COMMITMENTS)
    except OSError:
        return _result(False, ["ARTIFACT_READ_FAILED"], _COMMITMENTS)

    reasons = []
    if not _is_ris_interchange_text(artifact_text):
        reasons.append("ARTIFACT_RIS_OUTPUT_CONTRACT_INVALID")

    try:
        artifact_records = list(rispy.loads(artifact_text))
        artifact_exports = _individual_exports(artifact_records)
    except Exception:
        reasons.append("ARTIFACT_RIS_PARSE_FAILED")
        return _result(False, reasons, _COMMITMENTS)

    # Compare records through rispy's own per-record serialization.  This
    # accepts equivalent RIS physical line endings/layout while requiring the
    # exact re-exported record semantics from the pinned upstream writer.
    if artifact_exports != expected_exports:
        reasons.append("RIS_REEXPORT_MISMATCH")
        reasons.extend([
            "EXACT_DUPLICATE_DEFINITION_MISMATCH",
            "RETAIN_FIRST_EXACT_DUPLICATE_MISMATCH",
            "PRESERVE_SURVIVING_ORDER_MISMATCH",
        ])

    if any(run not in artifact_text for run in source_chinese_runs):
        reasons.append("UNICODE_CHINESE_PRESERVATION_MISMATCH")

    return _result(not reasons, reasons, _COMMITMENTS)
