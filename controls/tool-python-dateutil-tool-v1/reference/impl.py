from pathlib import Path
from datetime import datetime
import warnings

import dateutil.parser
from dateutil.parser import ParserError, UnknownTimezoneWarning


class UserInputError(ValueError):
    pass


_DEFAULT_DATETIME = datetime(1900, 1, 1, 0, 0, 0)


def _parse_one_line(line: str, line_number: int) -> str:
    value = line.strip()
    if value == "":
        raise UserInputError(f"line {line_number}: empty date line")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", UnknownTimezoneWarning)
            dt = dateutil.parser.parse(
                value,
                default=_DEFAULT_DATETIME,
                fuzzy=False,
                ignoretz=False,
            )
    except (ParserError, UnknownTimezoneWarning, OverflowError, ValueError, TypeError) as exc:
        raise UserInputError(f"line {line_number}: invalid date: {value!r}") from exc

    return dt.isoformat()


def extract(input_path: Path) -> str:
    try:
        text = input_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise UserInputError("input is not valid UTF-8 text") from exc

    if text == "":
        raise UserInputError("input is empty")

    lines = text.splitlines()
    if not lines:
        raise UserInputError("input is empty")

    output_lines = [_parse_one_line(line, i) for i, line in enumerate(lines, start=1)]
    return "\n".join(output_lines) + "\n"
