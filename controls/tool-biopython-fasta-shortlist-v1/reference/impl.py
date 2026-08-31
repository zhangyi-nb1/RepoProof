from __future__ import annotations

from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from io import StringIO
import json
from pathlib import Path

from Bio import SeqIO
from Bio.SeqUtils import gc_fraction


class UserInputError(ValueError):
    pass


_TITLE = "# FASTA 候选序列筛选报告"
_TABLE_HEADER = "| id | length_bp | gc_percent | ambiguous_percent | decision | reasons |"
_TABLE_RULE = "|---|---:|---:|---:|:---:|---|"
_SCOPE = "- 处理边界：未修改、修剪、翻译或比对输入序列，未查询远程数据库。"
_TWO_PLACES = Decimal("0.01")


def _load_records(input_path: Path) -> list:
    try:
        text = input_path.read_text(encoding="utf-8")
        if not text.strip():
            raise ValueError("empty FASTA")
        records = list(SeqIO.parse(StringIO(text), "fasta"))
        if not records:
            raise ValueError("FASTA has no records")
        if any(str(record.id) == "" or len(record.seq) == 0 for record in records):
            raise ValueError("FASTA record has empty id or sequence")
        if any(not str(record.seq).isascii() for record in records):
            raise ValueError("FASTA sequence must be ASCII")
        return records
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise UserInputError("INVALID_FASTA") from exc


def _display_percent(value: Decimal) -> str:
    rounded = value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    return f"{rounded:.2f}"


def _encode_id(identifier: str) -> str:
    value = json.dumps(identifier, ensure_ascii=False, separators=(",", ":"))
    return (
        value.replace("&", "&amp;")
        .replace("\\", "&#92;")
        .replace("|", "&#124;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _item(record: object) -> dict[str, object]:
    sequence = str(record.seq)
    length = len(sequence)
    gc_raw = Decimal(str(gc_fraction(record.seq, ambiguous="ignore"))) * Decimal(100)
    ambiguous_count = sum(
        character.upper() not in {"A", "C", "G", "T"}
        for character in sequence
    )
    ambiguous_raw = (
        Decimal(ambiguous_count) * Decimal(100) / Decimal(length)
        if length
        else Decimal(0)
    )

    length_ok = 150 <= length <= 1000
    gc_ok = Decimal(35) <= gc_raw <= Decimal(65)
    ambiguous_ok = ambiguous_raw <= Decimal(1)
    passed = length_ok and gc_ok and ambiguous_ok

    reasons: list[str] = []
    if length < 150:
        reasons.append("LENGTH_BELOW_MIN")
    elif length > 1000:
        reasons.append("LENGTH_ABOVE_MAX")
    if gc_raw < Decimal(35):
        reasons.append("GC_BELOW_MIN")
    elif gc_raw > Decimal(65):
        reasons.append("GC_ABOVE_MAX")
    if ambiguous_raw > Decimal(1):
        reasons.append("AMBIGUOUS_ABOVE_MAX")

    return {
        "id": str(record.id),
        "length_bp": length,
        "gc_percent": _display_percent(gc_raw),
        "ambiguous_percent": _display_percent(ambiguous_raw),
        "decision": "PASS" if passed else "REJECT",
        "reasons": "NONE" if passed else ";".join(reasons),
    }


def _row(item: dict[str, object]) -> str:
    return (
        f"| {_encode_id(str(item['id']))} | {item['length_bp']} | "
        f"{item['gc_percent']} | {item['ambiguous_percent']} | "
        f"{item['decision']} | {item['reasons']} |"
    )


def extract(input_path: Path) -> str:
    records = _load_records(input_path)
    items = [_item(record) for record in records]
    passed = [item for item in items if item["decision"] == "PASS"]
    rejected = [item for item in items if item["decision"] == "REJECT"]
    duplicate_id_values = sum(
        count > 1 for count in Counter(str(record.id) for record in records).values()
    )

    lines = [
        _TITLE,
        "",
        "## 摘要",
        f"- 总记录数：{len(items)}",
        f"- PASS：{len(passed)}",
        f"- REJECT：{len(rejected)}",
        "",
        "## 通过序列",
        _TABLE_HEADER,
        _TABLE_RULE,
    ]
    lines.extend(_row(item) for item in passed)
    lines.extend(
        [
            "",
            "## 未通过序列",
            _TABLE_HEADER,
            _TABLE_RULE,
        ]
    )
    lines.extend(_row(item) for item in rejected)
    lines.extend(
        [
            "",
            "## 警告",
            _SCOPE,
            f"- 重复 id 值数量：{duplicate_id_values}",
        ]
    )
    return "\n".join(lines) + "\n"
