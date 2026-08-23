"""reference:真调 pinned 上游(出题人提供,绝不交付)。"""
from pathlib import Path

from num2words import num2words


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        text = input_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        raise UserInputError(str(e)) from e
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            n = float(s) if "." in s else int(s)
        except ValueError as e:
            raise UserInputError(f"not a number: {s}") from e
        out.append(num2words(n))
    return "\n".join(out)
