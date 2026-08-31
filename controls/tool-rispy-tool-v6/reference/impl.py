import re
from pathlib import Path

import rispy


class UserInputError(ValueError):
    pass


_ORDINAL_TY_LINE = re.compile(r"^(?:\d+\.\s+)?(TY  -.*)$")


def _freeze(value):
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _ris_records(serialized: str, expected_count: int) -> str:
    records = []
    current = None

    for line in serialized.splitlines():
        ty_match = _ORDINAL_TY_LINE.fullmatch(line)
        if ty_match is not None:
            if current is not None:
                raise RuntimeError("rispy serialization contains a nested RIS record")
            current = [ty_match.group(1)]
            continue

        if current is not None:
            current.append(line)
            if line.startswith("ER  -"):
                records.append(current)
                current = None

    if current is not None or len(records) != expected_count:
        raise RuntimeError("rispy serialization did not produce complete RIS records")

    return "\n".join("\n".join(record) for record in records) + "\n"


def extract(input_path: Path) -> str:
    try:
        with input_path.open("r", encoding="utf-8", newline="") as source:
            entries = rispy.load(source)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise UserInputError(str(error)) from error

    if not entries:
        raise UserInputError("No RIS records found")

    retained = []
    seen = set()
    for entry in entries:
        fingerprint = _freeze(entry)
        if fingerprint not in seen:
            seen.add(fingerprint)
            retained.append(entry)

    serialized = rispy.dumps(retained)
    return _ris_records(serialized, len(retained))
