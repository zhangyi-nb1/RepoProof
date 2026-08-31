import csv
import io
from pathlib import Path

import pint


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        source = input_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise UserInputError("输入文件必须是 UTF-8 文本") from exc

    try:
        dialect = csv.Sniffer().sniff(source, delimiters=",\t")
        reader = csv.DictReader(io.StringIO(source), dialect=dialect)
        if reader.fieldnames != ["样本名", "原数值", "目标单位"]:
            raise UserInputError("表头必须依次为：样本名、原数值、目标单位")
        records = list(reader)
    except csv.Error as exc:
        raise UserInputError("输入必须是格式正确的 CSV 或 TSV 表格") from exc

    for record in records:
        if None in record or any(record[name] is None or not record[name].strip() for name in ("样本名", "原数值", "目标单位")):
            raise UserInputError("每一行都必须提供非空的样本名、原数值和目标单位")

    registry = pint.UnitRegistry()
    output = io.StringIO(newline="")
    writer = csv.writer(output, dialect="excel-tab", lineterminator="\n")
    writer.writerow(["样本名", "原数值", "目标单位", "换算结果", "状态", "说明"])

    conversion_errors = (
        pint.UndefinedUnitError,
        pint.DimensionalityError,
        pint.OffsetUnitCalculusError,
        pint.LogarithmicUnitCalculusError,
        ValueError,
    )
    for record in records:
        sample = record["样本名"]
        original = record["原数值"]
        target = record["目标单位"]
        try:
            converted = registry.Quantity(original).to(target)
            result = f"{format(float(converted.magnitude), '.6g')} {target}"
            status = "已换算"
            note = ""
        except conversion_errors as exc:
            result = ""
            status = "未换算"
            note = f"无法换算：{type(exc).__name__}"
        writer.writerow([sample, original, target, result, status, note])

    return output.getvalue()
