from pathlib import Path

import pygments
from pygments.formatters import HtmlFormatter
from pygments.lexers import guess_lexer_for_filename
from pygments.util import ClassNotFound


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        path = Path(input_path)
        if not path.exists() or not path.is_file():
            raise UserInputError("input path must be an existing regular file")

        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise UserInputError("input file must be valid UTF-8 text") from exc
        except OSError as exc:
            raise UserInputError(f"cannot read input file: {exc}") from exc

        if source == "":
            raise UserInputError("input file is empty")

        try:
            lexer = guess_lexer_for_filename(path.name, source)
        except ClassNotFound as exc:
            raise UserInputError("could not determine a Pygments lexer for the input") from exc

        formatter = HtmlFormatter(full=True, noclasses=True, encoding=None)
        return pygments.highlight(source, lexer, formatter)
    except UserInputError:
        raise
    except Exception as exc:
        raise UserInputError(f"failed to highlight input: {exc}") from exc
