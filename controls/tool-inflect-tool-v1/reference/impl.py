"""reference:真调 pinned 上游(出题人提供,绝不交付)。"""
from pathlib import Path

import inflect


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        text = input_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        raise UserInputError(str(e)) from e
    eng = inflect.engine()
    return "\n".join(eng.plural(l.strip()) for l in text.splitlines() if l.strip())
