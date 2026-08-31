from pathlib import Path
import re

import rispy


_COMMITMENT_IDS = [
    "ris-upstream-parse-and-write",
    "parsed-record-exact-deduplication",
    "utf8-chinese-text-preservation",
]
_FIELD_LINE = re.compile(r"^([A-Z0-9]{2})  -(?: .*)?$")
_CONTINUATION_LINE = re.compile(r"^ {6}.*$")


def _result(ok: bool, reason_codes: list[str]) -> dict:
    return {
        "ok": ok,
        "reason_codes": reason_codes,
        "checked_commitment_ids": _COMMITMENT_IDS,
    }


def _has_ris_interchange_shape(text: str) -> bool:
    """Validate the public RIS interchange framing independently of rispy."""
    in_record = False
    complete_records = 0

    for line in text.splitlines():
        # Blank lines are not field or presentation lines and do not alter state.
        if line == "":
            continue

        field_match = _FIELD_LINE.fullmatch(line)
        if field_match is not None:
            tag = field_match.group(1)
            if not in_record:
                # No field, including a header-like field, may precede TY.
                if tag != "TY":
                    return False
                in_record = True
                continue

            if tag == "TY":
                # A second TY before ER is a nested record.
                return False
            if tag == "ER":
                in_record = False
                complete_records += 1
            continue

        # Continuations are meaningful only after a record has begun and before
        # its terminating ER.  Any other nonblank line is forbidden framing.
        if in_record and _CONTINUATION_LINE.fullmatch(line) is not None:
            continue
        return False

    return not in_record and complete_records > 0


def verify(input_path: Path, artifact_path: Path) -> dict:
    try:
        input_text = input_path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return _result(False, ["INPUT_NOT_UTF8"])
    except OSError:
        return _result(False, ["INPUT_UNREADABLE"])

    try:
        # This is the pinned rispy parser and deliberately operates on decoded
        # Unicode, preserving Chinese and other Unicode field values.
        parsed_records = rispy.loads(input_text)
    except Exception:
        return _result(False, ["INPUT_INVALID_RIS"])

    retained_records = []
    for record in parsed_records:
        if not any(record == retained for retained in retained_records):
            retained_records.append(record)

    try:
        # Really invoke the pinned upstream writer required by the commitment.
        # Its possible presentation framing is not compared byte-for-byte: the
        # public output profile forbids such framing and requires semantic RIS
        # comparison after parsing instead.
        upstream_serialization = rispy.dumps(retained_records)
        if not isinstance(upstream_serialization, str):
            return _result(False, ["UPSTREAM_SERIALIZATION_FAILED"])
    except Exception:
        return _result(False, ["UPSTREAM_SERIALIZATION_FAILED"])

    try:
        artifact_text = artifact_path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return _result(False, ["ARTIFACT_NOT_UTF8"])
    except OSError:
        return _result(False, ["ARTIFACT_UNREADABLE"])

    if not _has_ris_interchange_shape(artifact_text):
        return _result(False, ["ARTIFACT_INVALID_RIS"])

    try:
        artifact_records = rispy.loads(artifact_text)
    except Exception:
        return _result(False, ["ARTIFACT_INVALID_RIS"])

    # Equality of parsed dictionaries enforces both first-occurrence exact
    # deduplication and preservation of all Unicode field values, while allowing
    # only profile-valid presentation differences from rispy.dumps framing.
    if artifact_records != retained_records:
        return _result(False, ["RIS_OUTPUT_MISMATCH"])

    return _result(True, [])
