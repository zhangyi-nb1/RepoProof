from pathlib import Path

import ftfy


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        path = Path(input_path)
        if not path.exists():
            raise UserInputError(f"Input path does not exist: {path}")
        if not path.is_file():
            raise UserInputError(f"Input path is not a file: {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise UserInputError("Input is not valid UTF-8 text") from exc
        except OSError as exc:
            raise UserInputError(f"Could not read input file: {exc}") from exc
        if text.strip() == "":
            raise UserInputError("Input text is empty")
        try:
            return ftfy.fix_text(text)
        except (UnicodeError, ValueError, TypeError) as exc:
            raise UserInputError(f"Could not fix input text: {exc}") from exc
    except UserInputError:
        raise
