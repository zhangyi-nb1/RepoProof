"""reference:真调 pinned dateutil 的参考实现(出题人材料,绝不交付)。"""
from datetime import datetime
from pathlib import Path

from dateutil.rrule import rrulestr


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        text = input_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        raise UserInputError(str(e)) from e
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) != 2 or not lines[0].startswith("DTSTART:") \
            or not lines[1].startswith("RRULE:"):
        raise UserInputError("input must be exactly DTSTART:<iso> and RRULE:<rule>")
    try:
        dtstart = datetime.fromisoformat(lines[0][len("DTSTART:"):])
    except ValueError as e:
        raise UserInputError(f"bad DTSTART: {e}") from e
    try:
        rule = rrulestr(lines[1][len("RRULE:"):], dtstart=dtstart)
    except (ValueError, KeyError) as e:
        raise UserInputError(f"bad RRULE: {e}") from e
    out = []
    for i, occ in enumerate(rule):
        if i >= 10:
            break
        out.append(occ.isoformat())
    return "\n".join(out)
