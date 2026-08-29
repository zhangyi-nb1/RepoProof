from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pypdf


class UserInputError(ValueError):
    pass


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _outline_entries(reader: pypdf.PdfReader) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    def walk(items: Any, level: int) -> None:
        if not isinstance(items, list):
            items = [items]
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1)
                continue
            title = _as_text(getattr(item, "title", item))
            try:
                page_number: int | None = reader.get_destination_page_number(item) + 1
            except Exception:
                page_number = None
            result.append({"level": level, "page_number": page_number, "title": title or ""})

    try:
        walk(reader.outline, 0)
    except Exception as exc:
        raise UserInputError(f"invalid PDF outline: {exc}") from exc
    return result


def extract(input_path: Path) -> str:
    try:
        if not input_path.is_file() or input_path.stat().st_size == 0:
            raise UserInputError("input is missing, unreadable, or empty")
        reader = pypdf.PdfReader(str(input_path), strict=False)
        if reader.is_encrypted:
            raise UserInputError("encrypted PDF is not supported")

        metadata = reader.metadata
        document = {
            "metadata": {
                "author": _as_text(getattr(metadata, "author", None)),
                "title": _as_text(getattr(metadata, "title", None)),
            },
            "outlines": _outline_entries(reader),
            "pages": [
                {
                    "page_number": index,
                    "text": page.extract_text() or "",
                }
                for index, page in enumerate(reader.pages, start=1)
            ],
        }
        return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except UserInputError:
        raise
    except Exception as exc:
        raise UserInputError(f"malformed or unreadable PDF: {exc}") from exc
