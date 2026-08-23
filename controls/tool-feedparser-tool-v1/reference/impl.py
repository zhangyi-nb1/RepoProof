from pathlib import Path
import re
import unicodedata

import feedparser


class UserInputError(ValueError):
    pass


_WS_RE = re.compile(r"\s+")


def _norm(value) -> str:
    if value is None:
        return ""
    text = str(value)
    text = unicodedata.normalize("NFC", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def extract(input_path: Path) -> str:
    try:
        data = input_path.read_bytes()
    except OSError as exc:
        raise UserInputError(f"cannot read input file: {exc}") from exc

    if not data.strip():
        raise UserInputError("empty input")

    try:
        parsed = feedparser.parse(data)
    except Exception as exc:
        raise UserInputError(f"failed to parse feed: {exc}") from exc

    if getattr(parsed, "bozo", False):
        exc = getattr(parsed, "bozo_exception", None)
        message = str(exc) if exc else "malformed feed"
        raise UserInputError(f"malformed feed: {message}")

    entries = list(getattr(parsed, "entries", []) or [])
    if not entries:
        raise UserInputError("no feed entries found")

    lines = ["title\tlink"]
    for entry in entries:
        title = _norm(entry.get("title", ""))
        link = _norm(entry.get("link", ""))
        lines.append(f"{title}\t{link}")

    return "\n".join(lines) + "\n"
