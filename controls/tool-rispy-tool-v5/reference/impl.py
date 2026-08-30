from pathlib import Path
import re

import rispy


class UserInputError(ValueError):
    pass


_FIELD_WITH_OPTIONAL_PREFIX = re.compile(r"(?<![A-Z0-9])([A-Z0-9]{2}  -.*)$")


def extract(input_path: Path) -> str:
    try:
        source = input_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise UserInputError("输入文件不是有效的 UTF-8 文本") from exc

    parsed_records = rispy.loads(source)
    if not parsed_records:
        raise UserInputError("输入文件不包含完整的 RIS 记录")

    unique_records = []
    for record in parsed_records:
        if not any(record == retained for retained in unique_records):
            unique_records.append(record)

    serialized = rispy.dumps(unique_records)
    ris_lines = []
    inside_record = False
    complete_records = 0

    for line in serialized.splitlines():
        field_match = _FIELD_WITH_OPTIONAL_PREFIX.search(line)
        if field_match is not None:
            field_line = field_match.group(1)
            tag = field_line[:2]
            if tag == "TY":
                if inside_record:
                    raise RuntimeError("上游序列化产生了嵌套 RIS 记录")
                inside_record = True
                ris_lines.append(field_line)
            elif inside_record:
                ris_lines.append(field_line)
                if tag == "ER":
                    inside_record = False
                    complete_records += 1
        elif inside_record and line.startswith("      "):
            ris_lines.append(line)

    if inside_record or complete_records != len(unique_records):
        raise RuntimeError("无法从上游序列化结果提取完整 RIS 记录")

    result = "\n".join(ris_lines) + "\n"
    reparsed_records = rispy.loads(result)
    if reparsed_records != unique_records:
        raise RuntimeError("RIS 序列化结果未保留记录语义")

    return result
