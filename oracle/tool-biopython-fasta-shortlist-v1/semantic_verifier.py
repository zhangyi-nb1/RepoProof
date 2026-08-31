from __future__ import annotations

from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from html import unescape
from io import StringIO
import json
from pathlib import Path
import re

import Bio
from Bio import SeqIO
from Bio.SeqUtils import gc_fraction


_COMMITMENTS = [
    "record-coverage-and-order",
    "sequence-preservation",
    "length-and-composition-metrics",
    "screening-decision",
    "failure-reasons",
    "behavior-6",
]
_TITLE = "# FASTA 候选序列筛选报告"
_TABLE_HEADER = "| id | length_bp | gc_percent | ambiguous_percent | decision | reasons |"
_TABLE_RULE = "|---|---:|---:|---:|:---:|---|"
_SCOPE = "- 处理边界：未修改、修剪、翻译或比对输入序列，未查询远程数据库。"
_UINT = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_PERCENT = re.compile(r"(?:0|[1-9][0-9]*)\.[0-9]{2}\Z")
_TWO_PLACES = Decimal("0.01")


def _result(ok: bool, codes: list[str], checked: list[str]) -> dict:
    return {
        "ok": bool(ok),
        "reason_codes": list(dict.fromkeys(codes)),
        "checked_commitment_ids": checked,
    }


def _encode_id(identifier: str) -> str:
    value = json.dumps(identifier, ensure_ascii=False, separators=(",", ":"))
    return (
        value.replace("&", "&amp;")
        .replace("\\", "&#92;")
        .replace("|", "&#124;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _decode_id(cell: str) -> str:
    try:
        value = json.loads(unescape(cell))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid id encoding") from exc
    if not isinstance(value, str) or _encode_id(value) != cell:
        raise ValueError("non-canonical id encoding")
    return value


def _display_percent(value: Decimal) -> str:
    rounded = value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    return f"{rounded:.2f}"


def _expected_item(record: object) -> dict[str, object]:
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


def _parse_row(line: str) -> dict[str, object]:
    if not line.startswith("| ") or not line.endswith(" |"):
        raise ValueError("invalid table row frame")
    cells = line[2:-2].split(" | ")
    if len(cells) != 6:
        raise ValueError("invalid table column count")
    identifier, length, gc_value, ambiguous, decision, reasons = cells
    if _UINT.fullmatch(length) is None:
        raise ValueError("invalid length")
    if _PERCENT.fullmatch(gc_value) is None or _PERCENT.fullmatch(ambiguous) is None:
        raise ValueError("invalid percentage")
    if decision not in {"PASS", "REJECT"}:
        raise ValueError("invalid decision")
    if not reasons:
        raise ValueError("missing reasons")
    return {
        "id": _decode_id(identifier),
        "length_bp": int(length),
        "gc_percent": gc_value,
        "ambiguous_percent": ambiguous,
        "decision": decision,
        "reasons": reasons,
    }


def _parse_table(lines: list[str], index: int) -> tuple[list[dict[str, object]], int]:
    if index + 1 >= len(lines):
        raise ValueError("missing table")
    if lines[index] != _TABLE_HEADER or lines[index + 1] != _TABLE_RULE:
        raise ValueError("invalid table grammar")
    index += 2
    rows = []
    while index < len(lines) and lines[index].startswith("| "):
        rows.append(_parse_row(lines[index]))
        index += 1
    return rows, index


def _summary_number(line: str, prefix: str) -> int:
    value = line.removeprefix(prefix)
    if not line.startswith(prefix) or _UINT.fullmatch(value) is None:
        raise ValueError("invalid summary")
    return int(value)


def _parse_document(text: str) -> dict[str, object]:
    if not text.endswith("\n") or text.endswith("\n\n"):
        raise ValueError("invalid terminal newline")
    lines = text[:-1].split("\n")
    index = 0

    def expect(value: str) -> None:
        nonlocal index
        if index >= len(lines) or lines[index] != value:
            raise ValueError("unexpected document grammar")
        index += 1

    expect(_TITLE)
    expect("")
    expect("## 摘要")
    total = _summary_number(lines[index], "- 总记录数：")
    index += 1
    passed_count = _summary_number(lines[index], "- PASS：")
    index += 1
    rejected_count = _summary_number(lines[index], "- REJECT：")
    index += 1
    expect("")
    expect("## 通过序列")
    passed, index = _parse_table(lines, index)
    expect("")
    expect("## 未通过序列")
    rejected, index = _parse_table(lines, index)
    expect("")
    expect("## 警告")
    expect(_SCOPE)
    duplicate_values = _summary_number(lines[index], "- 重复 id 值数量：")
    index += 1
    if index != len(lines):
        raise ValueError("unexpected trailing content")

    return {
        "total": total,
        "passed_count": passed_count,
        "rejected_count": rejected_count,
        "passed": passed,
        "rejected": rejected,
        "duplicate_values": duplicate_values,
    }


def _load_records(input_path: Path) -> list:
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


def verify(input_path: Path, artifact_path: Path) -> dict:
    if Bio.__version__ != "1.88":
        return _result(False, ["UPSTREAM_VERSION_MISMATCH"], [])

    try:
        records = _load_records(input_path)
    except (OSError, UnicodeError, TypeError, ValueError):
        return _result(False, ["UPSTREAM_PARSE_FAILURE"], [])

    expected = [_expected_item(record) for record in records]
    expected_passed = [item for item in expected if item["decision"] == "PASS"]
    expected_rejected = [item for item in expected if item["decision"] == "REJECT"]
    expected_duplicate_values = sum(
        count > 1 for count in Counter(str(record.id) for record in records).values()
    )

    try:
        text = artifact_path.read_text(encoding="utf-8")
        actual = _parse_document(text)
    except (OSError, UnicodeError, ValueError, IndexError):
        return _result(False, ["ARTIFACT_PROTOCOL_INVALID"], [])

    codes: list[str] = []
    if (
        actual["total"] != len(expected)
        or actual["passed_count"] != len(expected_passed)
        or actual["rejected_count"] != len(expected_rejected)
        or actual["passed_count"] + actual["rejected_count"] != actual["total"]
    ):
        codes.append("SUMMARY_MISMATCH")
    if actual["passed"] != expected_passed:
        codes.append("PASS_TABLE_MISMATCH")
    if actual["rejected"] != expected_rejected:
        codes.append("REJECT_TABLE_MISMATCH")
    if actual["duplicate_values"] != expected_duplicate_values:
        codes.append("WARNING_MISMATCH")

    return _result(not codes, codes, list(_COMMITMENTS))
