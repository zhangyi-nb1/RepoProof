"""reference:真调 pinned 上游(出题人提供,绝不交付)。"""
from pathlib import Path

import re

from spellchecker import SpellChecker


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        text = input_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        raise UserInputError(str(e)) from e
    words = re.findall(r"[a-zA-Z']+", text.lower())
    return "\n".join(sorted(SpellChecker().unknown(words)))
