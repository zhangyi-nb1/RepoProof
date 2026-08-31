import csv
import io
import math
from pathlib import Path

import pint


class UserInputError(ValueError):
    pass


def _short_number(magnitude) -> str:
    return format(magnitude, ".6f").rstrip("0").rstrip(".")


def extract(input_path: Path) -> str:
    try:
        with input_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle, dialect="excel-tab", strict=True)
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise UserInputError(str(exc)) from exc

    expected_header = ["样本名", "原数值", "目标单位"]
    if not rows:
        raise UserInputError("输入 TSV 不能为空")
    if rows[0] != expected_header:
        raise UserInputError("TSV 表头必须依次为：样本名、原数值、目标单位")

    for row_number, row in enumerate(rows[1:], start=2):
        if len(row) != 3:
            raise UserInputError(f"第 {row_number} 行必须恰有 3 列")
        if any(not cell.strip() for cell in row):
            raise UserInputError(f"第 {row_number} 行不能含有空白单元格")

    registry = pint.UnitRegistry()
    output = io.StringIO(newline="")
    writer = csv.writer(output, dialect="excel-tab", lineterminator="\n")
    writer.writerow(["样本名", "原数值", "目标单位", "换算结果", "状态", "说明"])

    for sample, raw_value, target_unit in rows[1:]:
        try:
            quantity = registry.Quantity(raw_value)
            converted = quantity.to(target_unit)
        except pint.PintError as exc:
            writer.writerow([
                sample,
                raw_value,
                target_unit,
                "",
                "未换算",
                f"无法换算：{type(exc).__name__}: {exc}",
            ])
            continue

        if not math.isfinite(converted.magnitude):
            writer.writerow([
                sample,
                raw_value,
                target_unit,
                "",
                "未换算",
                "无法换算：结果不是有限实数",
            ])
            continue

        writer.writerow([
            sample,
            raw_value,
            target_unit,
            _short_number(converted.magnitude),
            "已换算",
            "",
        ])

    return output.getvalue()
