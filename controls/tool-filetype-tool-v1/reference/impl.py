"""reference:真调 pinned 上游(出题人提供,绝不交付)。"""
from pathlib import Path

import json

import filetype


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        data = input_path.read_bytes()
    except OSError as e:
        raise UserInputError(str(e)) from e
    ft = filetype.guess(data)
    return json.dumps({"ext": ft.extension if ft else None,
                       "mime": ft.mime if ft else None})
