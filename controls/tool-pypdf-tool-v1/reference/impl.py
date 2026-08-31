import json
from pathlib import Path

import pypdf


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    """Return a deterministic searchable manifest for one unencrypted PDF."""
    def metadata_value(info, name: str):
        value = getattr(info, name, None) if info is not None else None
        return None if value is None else str(value)

    def bookmark_nodes(reader, entries):
        nodes = []
        previous_node = None
        for entry in entries:
            if isinstance(entry, list):
                children = bookmark_nodes(reader, entry)
                if previous_node is None:
                    # A malformed leading nested list has no parent; preserve its order.
                    nodes.extend(children)
                else:
                    previous_node["children"].extend(children)
                continue

            title = getattr(entry, "title", None)
            if title is None:
                title = str(entry)
            try:
                page_number = reader.get_destination_page_number(entry) + 1
            except Exception:
                page_number = None

            previous_node = {
                "title": str(title),
                "page_number": page_number,
                "children": [],
            }
            nodes.append(previous_node)
        return nodes

    try:
        input_path = Path(input_path)
        if not input_path.is_file() or input_path.stat().st_size == 0:
            raise UserInputError("Input is missing, unreadable, or empty.")

        with input_path.open("rb") as source:
            reader = pypdf.PdfReader(source)
            if reader.is_encrypted:
                raise UserInputError("Input PDF is encrypted and cannot be processed without a password.")

            info = reader.metadata
            pages = []
            for page_number, page in enumerate(reader.pages, start=1):
                text = page.extract_text()
                pages.append({"page_number": page_number, "text": "" if text is None else str(text)})

            manifest = {
                "author": metadata_value(info, "author"),
                "bookmarks": bookmark_nodes(reader, reader.outline),
                "page_count": len(pages),
                "pages": pages,
                "title": metadata_value(info, "title"),
            }
            return json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except UserInputError:
        raise
    except Exception as exc:
        raise UserInputError(f"Invalid, damaged, or unreadable PDF: {exc}") from exc
