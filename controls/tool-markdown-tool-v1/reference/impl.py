from pathlib import Path
import markdown as upstream_markdown


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        path = Path(input_path)
        if not path.exists():
            raise UserInputError(f"input file does not exist: {path}")
        if not path.is_file():
            raise UserInputError(f"input path is not a regular file: {path}")
        text = path.read_text(encoding="utf-8")
    except UserInputError:
        raise
    except UnicodeDecodeError as exc:
        raise UserInputError("input is not valid UTF-8") from exc
    except OSError as exc:
        raise UserInputError(f"cannot read input file: {exc}") from exc

    if not text.strip():
        raise UserInputError("input is empty")

    try:
        return upstream_markdown.markdown(
            text,
            extensions=[],
            output_format="html5",
        )
    except Exception as exc:
        raise UserInputError(f"failed to render Markdown: {exc}") from exc
