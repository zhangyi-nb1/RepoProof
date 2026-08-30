from pathlib import Path
import re

import rispy


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        source = input_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise UserInputError("输入不是可读取的 UTF-8 RIS 文献文件") from exc

    records = rispy.loads(source)
    unique_records = []
    for record in records:
        if not any(record == earlier for earlier in unique_records):
            unique_records.append(record)

    if not unique_records:
        raise UserInputError("输入中没有可导出的 RIS 记录")

    serialized = rispy.dumps(unique_records)

    # rispy's writer may add ordinal presentation headings.  Retain only the
    # actual RIS record framing and its contents, including continuation lines.
    output_lines = []
    in_record = False
    for line in serialized.splitlines():
        if not in_record:
            record_start = re.sub(
                r"^[\t ]*\d+\.[\t ]*(?=TY  -)", "", line
            )
            if record_start.startswith("TY  -"):
                output_lines.append(record_start)
                in_record = True
        else:
            output_lines.append(line)
            if line.startswith("ER  -"):
                in_record = False

    if in_record or not output_lines:
        raise RuntimeError("rispy produced an incomplete RIS record")

    return "\n".join(output_lines) + "\n"
