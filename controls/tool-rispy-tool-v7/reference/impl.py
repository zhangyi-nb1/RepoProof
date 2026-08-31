from pathlib import Path

import rispy


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        source_text = input_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise UserInputError("输入文件不是有效的 UTF-8 文本") from exc

    records = rispy.loads(source_text)
    if not records:
        raise UserInputError("输入文件不包含可导出的 RIS 记录")

    unique_records = []
    for record in records:
        if record not in unique_records:
            unique_records.append(record)

    serialized = rispy.dumps(unique_records)

    # rispy's display-oriented serializer can prefix records with ordinal
    # headings.  Keep only the actual RIS records it serialized.
    ris_lines = []
    in_record = False
    for line in serialized.splitlines():
        if line.startswith("TY  -"):
            in_record = True
        if in_record:
            ris_lines.append(line)
        if in_record and line.startswith("ER  -"):
            in_record = False

    result = "\n".join(ris_lines)
    if not result:
        raise UserInputError("无法生成有效的 RIS 记录")
    return result + "\n"
