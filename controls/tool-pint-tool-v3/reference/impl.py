import csv
import io
import math
from pathlib import Path

import pint


class UserInputError(ValueError):
    pass


INPUT_COLUMNS = ["sample_name", "value", "source_unit", "target_unit"]
OUTPUT_COLUMNS = [
    "sample_name",
    "value",
    "source_unit",
    "target_unit",
    "converted_value",
    "status",
    "reason",
]


def extract(input_path: Path) -> str:
    try:
        text = input_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise UserInputError("输入文件必须是 UTF-8 文本") from exc

    try:
        reader = csv.DictReader(io.StringIO(text), delimiter="\t", strict=True)
        if reader.fieldnames is None:
            raise UserInputError("输入表必须包含表头")
        if reader.fieldnames != INPUT_COLUMNS:
            raise UserInputError("输入表头必须且只能是 sample_name、value、source_unit、target_unit")
        rows = list(reader)
    except csv.Error as exc:
        raise UserInputError("输入不是有效的严格 TSV 表格") from exc

    if not rows:
        raise UserInputError("输入表至少需要一条数据行")

    registry = pint.UnitRegistry()
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=OUTPUT_COLUMNS, delimiter="\t", lineterminator="\n")
    writer.writeheader()

    for row in rows:
        if None in row or any(row[column] is None for column in INPUT_COLUMNS):
            raise UserInputError("每条数据行必须恰有四列")
        if not row["sample_name"] or not row["value"] or not row["source_unit"] or not row["target_unit"]:
            raise UserInputError("sample_name、value、source_unit 和 target_unit 均不能为空")
        try:
            number = float(row["value"])
        except ValueError as exc:
            raise UserInputError("value 必须是有限的十进制数") from exc
        if not math.isfinite(number):
            raise UserInputError("value 必须是有限的十进制数")

        result = dict(row)
        try:
            converted = registry.Quantity(number, row["source_unit"]).to(row["target_unit"])
        except pint.PintError as exc:
            result.update({
                "converted_value": "",
                "status": "unconverted",
                "reason": f"{type(exc).__name__}: {exc}",
            })
        else:
            result.update({
                "converted_value": format(float(converted.magnitude), ".6g"),
                "status": "converted",
                "reason": "",
            })
        writer.writerow(result)

    return output.getvalue()
