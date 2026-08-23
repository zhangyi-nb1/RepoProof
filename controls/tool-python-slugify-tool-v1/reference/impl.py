from pathlib import Path
import slugify as upstream


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        text = input_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise UserInputError(f"invalid input file: {exc}") from exc

    if text == "":
        raise UserInputError("input file is empty")

    try:
        lines = text.splitlines()
        slugs = [upstream.slugify(line) for line in lines]
    except Exception as exc:
        raise UserInputError(f"could not slugify input: {exc}") from exc

    return "\n".join(slugs) + "\n"
