"""reference:真调 pinned Unidecode(宽松转写,人闸裁定)。"""
from pathlib import Path

from unidecode import unidecode


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    path = Path(input_path)
    if not path.is_file():
        raise UserInputError(f"input is not a regular file: {path}")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise UserInputError(f"cannot read input file: {exc}") from exc
    if not data:
        raise UserInputError("input file is empty")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UserInputError(f"input is not valid UTF-8: {exc}") from exc
    return unidecode(text)
