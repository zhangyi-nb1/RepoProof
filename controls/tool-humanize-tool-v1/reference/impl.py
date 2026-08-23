from pathlib import Path
import re
import humanize


class UserInputError(ValueError):
    pass


_DECIMAL_INTEGER = re.compile(r"^(0|[1-9][0-9]*)$")


def extract(input_path: Path) -> str:
    try:
        text = input_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise UserInputError(f"cannot read input: {exc}") from exc

    if text == "":
        raise UserInputError("empty input")

    try:
        humanize.i18n.deactivate()
    except AttributeError:
        pass

    lines = text.splitlines()
    if not lines:
        raise UserInputError("empty input")

    rendered_lines = []
    try:
        for line_number, line in enumerate(lines, start=1):
            token = line.strip()
            if token == "":
                raise UserInputError(f"empty line at {line_number}")
            if not _DECIMAL_INTEGER.fullmatch(token):
                raise UserInputError(f"invalid byte count at line {line_number}: {line!r}")
            byte_count = int(token)
            rendered_lines.append(
                humanize.naturalsize(byte_count, binary=False, gnu=False, format="%.1f")
            )
    except UserInputError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise UserInputError(f"invalid input: {exc}") from exc

    return "\n".join(rendered_lines) + "\n"
