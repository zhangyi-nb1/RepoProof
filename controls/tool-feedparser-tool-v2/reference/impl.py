import calendar
import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

import feedparser


class UserInputError(ValueError):
    pass


_WS = re.compile(r"\s+")


def _text(value) -> str:
    if value is None:
        return ""
    return _WS.sub(" ", unicodedata.normalize("NFC", str(value))).strip()


def _authors(value) -> list[dict[str, str]]:
    authors = list(value.get("authors") or [])
    if not authors and value.get("author"):
        detail = value.get("author_detail") or {"name": value.get("author")}
        authors = [detail]
    return [
        {
            "email": _text(author.get("email")),
            "href": _text(author.get("href")),
            "name": _text(author.get("name")),
        }
        for author in authors
    ]


def _tags(value) -> list[dict[str, str]]:
    return [
        {
            "label": _text(tag.get("label")),
            "scheme": _text(tag.get("scheme")),
            "term": _text(tag.get("term")),
        }
        for tag in (value.get("tags") or [])
    ]


def _timestamp(value, name: str) -> dict[str, str]:
    raw = _text(value.get(name))
    parsed = value.get(f"{name}_parsed")
    utc = ""
    if parsed:
        utc = datetime.fromtimestamp(calendar.timegm(parsed), UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    return {"raw": raw, "utc": utc}


def _record(value) -> dict:
    return {
        "authors": _authors(value),
        "id": _text(value.get("id")),
        "link": _text(value.get("link")),
        "published": _timestamp(value, "published"),
        "tags": _tags(value),
        "title": _text(value.get("title")),
        "updated": _timestamp(value, "updated"),
    }


def extract(input_path: Path) -> str:
    try:
        data = input_path.read_bytes()
    except OSError as exc:
        raise UserInputError(f"cannot read feed: {exc}") from exc
    if not data.strip():
        raise UserInputError("feed input is empty")

    try:
        parsed = feedparser.parse(
            data,
            resolve_relative_uris=False,
            sanitize_html=False,
        )
    except Exception as exc:
        raise UserInputError(f"cannot parse feed: {exc}") from exc

    feed = parsed.get("feed") or {}
    entries = list(parsed.get("entries") or [])
    version = _text(parsed.get("version"))
    recognizable = bool(
        version
        or entries
        or any(feed.get(key) for key in ("title", "link", "id"))
    )
    if not recognizable:
        raise UserInputError("input is not a recognizable RSS or Atom feed")

    warnings = []
    if parsed.get("bozo"):
        exc = parsed.get("bozo_exception")
        warnings.append(
            {
                "message": _text(exc) or "recoverable malformed feed",
                "type": type(exc).__name__ if exc is not None else "FeedParseWarning",
            }
        )

    payload = {
        "entries": [_record(entry) for entry in entries],
        "feed": _record(feed),
        "format": version or "unknown",
        "warnings": warnings,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
