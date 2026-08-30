import io
import json
from pathlib import Path

import rispy


class UserInputError(ValueError):
    pass


def _record_key(record: dict) -> str:
    return json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def extract(input_path: Path) -> str:
    try:
        with input_path.open("r", encoding="utf-8", newline=None) as source:
            records = rispy.load(source)
    except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError, PermissionError) as exc:
        raise UserInputError(str(exc)) from exc

    if not records:
        raise UserInputError("RIS input contains no records")

    seen = set()
    unique_records = []
    for record in records:
        key = _record_key(record)
        if key not in seen:
            seen.add(key)
            unique_records.append(record)

    rendered = rispy.dumps(unique_records)
    record_lines = []
    in_record = False
    for line in rendered.splitlines():
        if line.startswith("TY  -"):
            in_record = True
        if in_record:
            record_lines.append(line)
            if line.startswith("ER  -"):
                in_record = False

    result = "\n".join(record_lines)
    if not result:
        raise UserInputError("RIS writer produced no complete records")
    return result + "\n"
