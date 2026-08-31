import csv
import io
import math
import re
import tokenize
import xml.etree.ElementTree as ET
from pathlib import Path

import pint
from pint.errors import DimensionalityError, PintError, UndefinedUnitError


_COMMITMENTS = [
    "table-columns",
    "row-preservation",
    "total-conversion",
    "successful-row",
    "failed-row",
    "document-static",
]
_INPUT_HEADER = ["item", "per_group_amount", "target_unit", "groups"]
_OUTPUT_HEADER = ["item", "per_group_amount", "groups", "total_amount", "status"]
_ERROR_CODES = {
    "INVALID_GROUPS",
    "INVALID_QUANTITY",
    "UNKNOWN_UNIT",
    "DIMENSION_MISMATCH",
}
_GROUPS_RE = re.compile(r"^[0-9]+$")
_XHTML_NS = "http://www.w3.org/1999/xhtml"
_ROW_INPUT_ERRORS = (
    PintError,
    ValueError,
    TypeError,
    ArithmeticError,
    AssertionError,
    tokenize.TokenError,
)


def _qname(local_name: str) -> str:
    return f"{{{_XHTML_NS}}}{local_name}"


def _add(reasons: list[str], code: str) -> None:
    if code not in reasons:
        reasons.append(code)


def _result(
    ok: bool,
    reasons: list[str],
    checked: list[str],
) -> dict:
    return {
        "ok": bool(ok),
        "reason_codes": reasons,
        "checked_commitment_ids": checked,
    }


def _xml_chars_allowed(value: str) -> bool:
    return all(
        code == 0x9
        or code == 0xA
        or code == 0xD
        or 0x20 <= code <= 0xD7FF
        or 0xE000 <= code <= 0xFFFD
        or 0x10000 <= code <= 0x10FFFF
        for code in map(ord, value)
    )


def _finite_scalar(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _read_input(input_path: Path) -> list[dict[str, str]] | None:
    try:
        text = input_path.read_text(encoding="utf-8")
        rows = list(
            csv.reader(
                io.StringIO(text, newline=""),
                dialect="excel-tab",
                strict=True,
            )
        )
    except (OSError, UnicodeError, csv.Error):
        return None

    if not rows or rows[0] != _INPUT_HEADER:
        return None

    parsed: list[dict[str, str]] = []
    for row in rows[1:]:
        if len(row) != 4:
            return None
        if not all(_xml_chars_allowed(value) for value in row):
            return None
        parsed.append(
            {
                "item": row[0],
                "per_group_amount": row[1],
                "target_unit": row[2],
                "groups": row[3],
            }
        )
    return parsed


def _independent_outcome(
    registry: pint.UnitRegistry,
    source: dict[str, str],
) -> dict[str, str]:
    groups_text = source["groups"]
    if _GROUPS_RE.fullmatch(groups_text) is None:
        return {"status": "INVALID_GROUPS", "total_amount": ""}

    try:
        groups = int(groups_text, 10)
    except (ValueError, OverflowError):
        return {"status": "INVALID_GROUPS", "total_amount": ""}
    if groups <= 0:
        return {"status": "INVALID_GROUPS", "total_amount": ""}

    amount_text = source["per_group_amount"]
    if not amount_text.strip():
        return {"status": "INVALID_QUANTITY", "total_amount": ""}

    try:
        quantity = registry.Quantity(amount_text)
    except UndefinedUnitError:
        return {"status": "UNKNOWN_UNIT", "total_amount": ""}
    except _ROW_INPUT_ERRORS:
        return {"status": "INVALID_QUANTITY", "total_amount": ""}

    if not _finite_scalar(quantity.magnitude):
        return {"status": "INVALID_QUANTITY", "total_amount": ""}

    target_text = source["target_unit"]
    if not target_text.strip():
        return {"status": "UNKNOWN_UNIT", "total_amount": ""}

    try:
        target_unit = registry.Unit(target_text)
    except UndefinedUnitError:
        return {"status": "UNKNOWN_UNIT", "total_amount": ""}
    except _ROW_INPUT_ERRORS:
        return {"status": "INVALID_QUANTITY", "total_amount": ""}

    try:
        converted = (quantity * groups).to(target_unit)
    except UndefinedUnitError:
        return {"status": "UNKNOWN_UNIT", "total_amount": ""}
    except DimensionalityError:
        return {"status": "DIMENSION_MISMATCH", "total_amount": ""}
    except _ROW_INPUT_ERRORS:
        return {"status": "INVALID_QUANTITY", "total_amount": ""}

    if not _finite_scalar(converted.magnitude):
        return {"status": "INVALID_QUANTITY", "total_amount": ""}

    try:
        rendered = format(converted, "~.6gP")
    except _ROW_INPUT_ERRORS:
        return {"status": "INVALID_QUANTITY", "total_amount": ""}

    return {"status": "OK", "total_amount": rendered}


def _has_stray_container_text(element: ET.Element) -> bool:
    if (element.text or "").strip():
        return True
    return any((child.tail or "").strip() for child in list(element))


def _leaf_text(
    element: ET.Element,
    expected_tag: str,
    expected_attributes: dict[str, str],
    reasons: list[str],
    code: str,
) -> str:
    if element.tag != _qname(expected_tag):
        _add(reasons, code)
    if dict(element.attrib) != expected_attributes:
        _add(reasons, code)
    if list(element):
        _add(reasons, code)
    if (element.tail or "").strip():
        _add(reasons, "DOCUMENT_STRAY_TEXT")
    return element.text if element.text is not None else ""


def _validate_dom(
    root: ET.Element,
    reasons: list[str],
) -> tuple[ET.Element, list[ET.Element]] | None:
    if root.tag != _qname("html") or root.attrib:
        _add(reasons, "DOCUMENT_ROOT_INVALID")
        return None

    root_children = list(root)
    if [element.tag for element in root_children] != [
        _qname("head"),
        _qname("body"),
    ]:
        _add(reasons, "DOCUMENT_STRUCTURE_INVALID")
        return None

    head, body = root_children
    if head.attrib or body.attrib:
        _add(reasons, "DOCUMENT_ATTRIBUTE_INVALID")

    head_children = list(head)
    if [element.tag for element in head_children] != [
        _qname("meta"),
        _qname("title"),
    ]:
        _add(reasons, "DOCUMENT_HEAD_INVALID")
        return None

    meta, title = head_children
    meta_text = _leaf_text(
        meta,
        "meta",
        {"charset": "utf-8"},
        reasons,
        "DOCUMENT_META_INVALID",
    )
    if meta_text.strip():
        _add(reasons, "DOCUMENT_META_INVALID")

    title_text = _leaf_text(
        title,
        "title",
        {},
        reasons,
        "DOCUMENT_TITLE_INVALID",
    )
    if title_text != "现场准备单":
        _add(reasons, "DOCUMENT_TITLE_INVALID")

    body_children = list(body)
    if [element.tag for element in body_children] != [
        _qname("h1"),
        _qname("p"),
        _qname("table"),
    ]:
        _add(reasons, "DOCUMENT_BODY_INVALID")
        return None

    heading, summary, table = body_children
    heading_text = _leaf_text(
        heading,
        "h1",
        {},
        reasons,
        "DOCUMENT_HEADING_INVALID",
    )
    if heading_text != "现场准备单":
        _add(reasons, "DOCUMENT_HEADING_INVALID")

    _leaf_text(
        summary,
        "p",
        {"id": "summary"},
        reasons,
        "REPORT_SUMMARY_STRUCTURE_INVALID",
    )

    if table.tag != _qname("table") or dict(table.attrib) != {
        "id": "preparation-list"
    }:
        _add(reasons, "PREPARATION_TABLE_INVALID")
        return None

    table_children = list(table)
    if [element.tag for element in table_children] != [
        _qname("thead"),
        _qname("tbody"),
    ]:
        _add(reasons, "PREPARATION_TABLE_STRUCTURE_INVALID")
        return None

    thead, tbody = table_children
    if thead.attrib or tbody.attrib:
        _add(reasons, "PREPARATION_TABLE_STRUCTURE_INVALID")

    header_rows = list(thead)
    if (
        len(header_rows) != 1
        or header_rows[0].tag != _qname("tr")
        or header_rows[0].attrib
    ):
        _add(reasons, "TABLE_HEADER_STRUCTURE_INVALID")
        return None

    header_row = header_rows[0]
    header_cells = list(header_row)
    if len(header_cells) != len(_OUTPUT_HEADER):
        _add(reasons, "TABLE_HEADER_STRUCTURE_INVALID")
    else:
        actual_header = [
            _leaf_text(
                cell,
                "th",
                {},
                reasons,
                "TABLE_HEADER_STRUCTURE_INVALID",
            )
            for cell in header_cells
        ]
        if actual_header != _OUTPUT_HEADER:
            _add(reasons, "TABLE_COLUMNS_MISMATCH")

    body_rows = list(tbody)
    if any(row.tag != _qname("tr") for row in body_rows):
        _add(reasons, "INPUT_ROW_STRUCTURE_INVALID")
        return None

    for container in [
        root,
        head,
        body,
        table,
        thead,
        tbody,
        header_row,
        *body_rows,
    ]:
        if _has_stray_container_text(container):
            _add(reasons, "DOCUMENT_STRAY_TEXT")

    return summary, body_rows


def verify(input_path: Path, artifact_path: Path) -> dict:
    reasons: list[str] = []
    checked: list[str] = []

    input_rows = _read_input(input_path)
    if input_rows is None:
        return _result(False, ["INPUT_TSV_CONTRACT_UNAVAILABLE"], checked)

    try:
        registry = pint.UnitRegistry()
        outcomes = [
            _independent_outcome(registry, source)
            for source in input_rows
        ]
    except Exception:
        return _result(False, ["UPSTREAM_EVALUATION_ERROR"], checked)

    checked = list(_COMMITMENTS)

    try:
        raw_artifact = artifact_path.read_bytes()
        artifact_text = raw_artifact.decode("utf-8")
    except OSError:
        return _result(False, ["ARTIFACT_UNAVAILABLE"], checked)
    except UnicodeDecodeError:
        return _result(False, ["ARTIFACT_UTF8_INVALID"], checked)

    if re.search(r"<!\s*(?:doctype|entity)\b", artifact_text, re.IGNORECASE):
        return _result(False, ["DOCUMENT_DECLARATION_FORBIDDEN"], checked)
    if "<!--" in artifact_text:
        return _result(False, ["DOCUMENT_COMMENT_FORBIDDEN"], checked)

    processing_targets = re.findall(
        r"<\?\s*([A-Za-z_:][A-Za-z0-9_.:-]*)",
        artifact_text,
    )
    if any(target.lower() != "xml" for target in processing_targets):
        return _result(
            False,
            ["DOCUMENT_PROCESSING_INSTRUCTION_FORBIDDEN"],
            checked,
        )

    try:
        root = ET.fromstring(artifact_text)
    except (ET.ParseError, ValueError):
        return _result(False, ["ARTIFACT_XML_INVALID"], checked)

    validated = _validate_dom(root, reasons)
    if validated is None:
        return _result(False, reasons, checked)

    summary_element, body_rows = validated

    success_count = sum(
        outcome["status"] == "OK" for outcome in outcomes
    )
    failed_count = len(outcomes) - success_count
    expected_summary = (
        f"总行数：{len(input_rows)}；"
        f"成功数：{success_count}；"
        f"失败数：{failed_count}"
    )
    actual_summary = (
        summary_element.text if summary_element.text is not None else ""
    )
    if actual_summary != expected_summary:
        _add(reasons, "REPORT_SUMMARY_MISMATCH")

    if len(body_rows) != len(input_rows):
        _add(reasons, "INPUT_ROW_COUNT_MISMATCH")

    for index, source in enumerate(input_rows):
        if index >= len(body_rows):
            break

        row = body_rows[index]
        if dict(row.attrib) != {"data-input-row": str(index + 1)}:
            _add(reasons, "INPUT_ROW_NUMBER_MISMATCH")

        cells = list(row)
        if len(cells) != len(_OUTPUT_HEADER):
            _add(reasons, "INPUT_ROW_CELL_STRUCTURE_INVALID")
            continue

        values = [
            _leaf_text(
                cell,
                "td",
                {},
                reasons,
                "INPUT_ROW_CELL_STRUCTURE_INVALID",
            )
            for cell in cells
        ]

        expected_source = [
            source["item"],
            source["per_group_amount"],
            source["groups"],
        ]
        if values[:3] != expected_source:
            _add(reasons, "INPUT_ROW_VALUES_MISMATCH")

        outcome = outcomes[index]
        if values[3] != outcome["total_amount"]:
            _add(reasons, "TOTAL_AMOUNT_MISMATCH")
        if values[4] != outcome["status"]:
            _add(reasons, "ROW_STATUS_MISMATCH")

        if values[4] != "OK" and values[4] not in _ERROR_CODES:
            _add(reasons, "ROW_STATUS_INVALID")
        if values[4] in _ERROR_CODES and values[3] != "":
            _add(reasons, "FAILED_ROW_TOTAL_NOT_EMPTY")

    return _result(not reasons, reasons, checked)
