from pathlib import Path

import markdownify as upstream


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    path = Path(input_path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise UserInputError(f"cannot read input file: {exc}") from exc

    if not raw or not raw.strip():
        raise UserInputError("empty input")

    try:
        html = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UserInputError(f"input is not valid UTF-8 HTML: {exc}") from exc

    if not html.strip():
        raise UserInputError("empty input")

    try:
        markdown = upstream.markdownify(html, heading_style="ATX", bullets="-")
    except Exception as exc:
        raise UserInputError(f"failed to convert HTML to Markdown: {exc}") from exc

    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not markdown:
        raise UserInputError("input produced empty Markdown")

    return markdown + "\n"
