from pathlib import Path
import json
import re

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


class UserInputError(ValueError):
    pass


_HEADING_RE = re.compile(r"^(?:heading|标题)\s*([1-9][0-9]*)$", re.IGNORECASE)


def _normalise_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _heading_level(paragraph: Paragraph):
    style = paragraph.style
    for candidate in (getattr(style, "style_id", ""), getattr(style, "name", "")):
        match = _HEADING_RE.match(candidate or "")
        if match:
            return int(match.group(1))
    return None


def _cell_text(cell) -> str:
    return "\n".join(_normalise_text(paragraph.text) for paragraph in cell.paragraphs)


def _table_block(table: Table) -> dict:
    column_count = len(table.columns)
    row_count = len(table.rows)
    flat_cells = table._cells

    groups = {}
    for row_index in range(row_count):
        for column_index in range(column_count):
            cell = flat_cells[row_index * column_count + column_index]
            key = id(cell._tc)
            groups.setdefault(key, {"cell": cell, "positions": []})["positions"].append(
                (row_index, column_index)
            )

    rendered = {}
    for group in groups.values():
        positions = group["positions"]
        origin = (min(row for row, _ in positions), min(column for _, column in positions))
        max_row = max(row for row, _ in positions)
        max_column = max(column for _, column in positions)
        row_span = max_row - origin[0] + 1
        column_span = max_column - origin[1] + 1
        for position in positions:
            if position == origin:
                rendered[position] = {
                    "text": _cell_text(group["cell"]),
                    "row_span": row_span,
                    "col_span": column_span,
                }
            else:
                rendered[position] = {"covered": True}

    return {
        "type": "table",
        "rows": [
            [rendered[(row_index, column_index)] for column_index in range(column_count)]
            for row_index in range(row_count)
        ],
    }


def extract(input_path: Path) -> str:
    try:
        input_path = Path(input_path)
        if not input_path.is_file() or input_path.stat().st_size == 0:
            raise UserInputError("input must be a non-empty readable DOCX file")

        document = docx.Document(input_path)
        blocks = []
        paragraph_count = 0
        heading_count = 0
        table_count = 0

        for child in document.element.body.iterchildren():
            if child.tag == qn("w:p"):
                paragraph = Paragraph(child, document)
                level = _heading_level(paragraph)
                blocks.append(
                    {
                        "type": "paragraph",
                        "text": _normalise_text(paragraph.text),
                        "heading_level": level,
                    }
                )
                paragraph_count += 1
                if level is not None:
                    heading_count += 1
            elif child.tag == qn("w:tbl"):
                blocks.append(_table_block(Table(child, document)))
                table_count += 1

        payload = {
            "blocks": blocks,
            "metadata": {
                "block_count": len(blocks),
                "paragraph_count": paragraph_count,
                "heading_count": heading_count,
                "table_count": table_count,
            },
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except UserInputError:
        raise
    except Exception as exc:
        raise UserInputError("unable to read a valid DOCX document") from exc
