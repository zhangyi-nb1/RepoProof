from pathlib import Path

import rispy


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        with input_path.open("r", encoding="utf-8") as source:
            references = rispy.load(source)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise UserInputError(f"无法读取或解析 RIS 文献文件：{exc}") from exc

    if not references:
        raise UserInputError("RIS 文献文件不包含可导出的记录")

    unique_references = []
    for reference in references:
        if reference not in unique_references:
            unique_references.append(reference)

    rendered = rispy.dumps(unique_references)
    record_lines = []
    inside_record = False
    for line in rendered.splitlines():
        if line.startswith("TY  -"):
            inside_record = True
        if inside_record:
            record_lines.append(line)
        if inside_record and line.startswith("ER  -"):
            inside_record = False

    return "\n".join(record_lines) + "\n"
