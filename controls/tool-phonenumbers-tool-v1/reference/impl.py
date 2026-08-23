"""reference:真调 pinned 上游(出题人提供,绝不交付)。"""
from pathlib import Path

import phonenumbers


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
            n = phonenumbers.parse(s, None)
        except phonenumbers.NumberParseException as e:
            raise UserInputError(f"bad number {s}: {e}") from e
        out.append(phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164))
    return "\n".join(out)
