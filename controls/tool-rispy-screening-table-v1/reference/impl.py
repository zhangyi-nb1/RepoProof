from pathlib import Path
import csv
import io
import re

import rispy


class UserInputError(ValueError):
    pass


_FIELD_LINE = re.compile(r"^[A-Z0-9]{2}  -(?: .*)?$")


def _validate_complete_ris(text: str) -> int:
    in_record = False
    record_count = 0
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line == "":
            continue
        if line.startswith("      "):
            if not in_record:
                raise UserInputError(f"第 {line_number} 行的续行不在 RIS 记录内")
            continue
        if not _FIELD_LINE.fullmatch(line):
            raise UserInputError(f"第 {line_number} 行不是有效的 RIS 字段行")
        tag = line[:2]
        if tag == "TY":
            if in_record:
                raise UserInputError(f"第 {line_number} 行开始了嵌套 RIS 记录")
            in_record = True
        elif tag == "ER":
            if not in_record:
                raise UserInputError(f"第 {line_number} 行结束了不存在的 RIS 记录")
            in_record = False
            record_count += 1
        elif not in_record:
            raise UserInputError(f"第 {line_number} 行的 RIS 字段不在记录内")
    if in_record:
        raise UserInputError("RIS 文件以未结束的记录结尾")
    if record_count == 0:
        raise UserInputError("RIS 文件不含完整记录")
    return record_count


def _text_cell(record: dict, key: str) -> str:
    value = record.get(key, "")
    return "" if value is None else str(value)


def _authors_cell(record: dict) -> str:
    value = record.get("authors", [])
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(str(author) for author in value)
    return str(value)


def extract(input_path: Path) -> str:
    try:
        text = input_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise UserInputError("RIS 文件不是有效的 UTF-8 文本") from exc

    expected_count = _validate_complete_ris(text)
    try:
        records = list(rispy.load(io.StringIO(text)))
    except ValueError as exc:
        raise UserInputError("rispy 无法解析 RIS 文件") from exc
    if len(records) != expected_count:
        raise UserInputError("rispy 未产生每个完整 RIS 记录")

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n", strict=True)
    writer.writerow(["record_index", "title", "authors", "year", "doi", "type", "missing_fields"])
    for index, record in enumerate(records, start=1):
        title = _text_cell(record, "title")
        authors = _authors_cell(record)
        year = _text_cell(record, "year")
        doi = _text_cell(record, "doi")
        reference_type = _text_cell(record, "type_of_reference")
        missing = [
            name
            for name, value in (("title", title), ("authors", authors), ("year", year), ("doi", doi))
            if value == ""
        ]
        writer.writerow([index, title, authors, year, doi, reference_type, ";".join(missing)])
    return output.getvalue()
