from pathlib import Path
from decimal import Decimal, ROUND_HALF_EVEN
import re
import xml.etree.ElementTree as ET

from Bio import SeqIO


_COMMITMENTS = [
    "fastq-record-count",
    "total-base-count",
    "read-length-summary",
    "mean-phred-quality",
    "phred-threshold-summary",
]

_OBSERVATIONS = {
    "read-count": ("integer", "fastq-record-count"),
    "total-base-count": ("integer", "total-base-count"),
    "minimum-read-length": ("integer", "read-length-summary"),
    "maximum-read-length": ("integer", "read-length-summary"),
    "mean-read-length": ("decimal", "read-length-summary"),
    "mean-phred-quality": ("decimal_or_na", "mean-phred-quality"),
    "q20-or-higher-base-count": ("integer", "phred-threshold-summary"),
    "q30-or-higher-base-count": ("integer", "phred-threshold-summary"),
    "q20-or-higher-percent": ("decimal_or_na", "phred-threshold-summary"),
    "q30-or-higher-percent": ("decimal_or_na", "phred-threshold-summary"),
}


def _result(ok, codes, checked):
    return {
        "ok": bool(ok),
        "reason_codes": sorted(set(codes)),
        "checked_commitment_ids": checked,
    }


def _round_two(numerator, denominator):
    value = Decimal(numerator) / Decimal(denominator)
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN), ".2f")


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def _valid_encoding(kind, value):
    if kind == "integer":
        return re.fullmatch(r"[0-9]+", value) is not None
    if kind == "decimal":
        return re.fullmatch(r"[0-9]+\.[0-9]{2}", value) is not None
    if kind == "decimal_or_na":
        return value == "not-applicable" or re.fullmatch(r"[0-9]+\.[0-9]{2}", value) is not None
    return False


def _observation_values(root):
    containers = [
        element for element in root.iter()
        if _local_name(element.tag) == "dl"
        and element.attrib.get("id") == "fastq-quality-observations"
    ]
    values = {}
    for observation_id in _OBSERVATIONS:
        matches = []
        for container in containers:
            for element in container.iter():
                if (_local_name(element.tag) == "dd" and
                        element.attrib.get("data-observation-id") == observation_id):
                    matches.append("".join(element.itertext()))
        values[observation_id] = matches
    return values


def verify(input_path: Path, artifact_path: Path) -> dict:
    # SeqIO.parse is deliberately used as the authoritative FASTQ interpretation.
    try:
        with Path(input_path).open("r", encoding="utf-8") as input_stream:
            records = list(SeqIO.parse(input_stream, "fastq"))
    except Exception:
        return _result(False, ["UPSTREAM_PARSE_FAILURE"], [])

    read_count = len(records)
    lengths = [len(record.seq) for record in records]
    total_bases = sum(lengths)

    # The public commitments do not define minimum/maximum/mean read length,
    # nor mean Phred quality, for a successfully parsed file containing no reads.
    if read_count == 0:
        return _result(
            False,
            ["INSUFFICIENT_EMPTY_READ_SEMANTICS"],
            [
                "fastq-record-count",
                "total-base-count",
                "phred-threshold-summary",
            ],
        )

    try:
        qualities = [
            quality
            for record in records
            for quality in record.letter_annotations["phred_quality"]
        ]
    except Exception:
        return _result(False, ["UPSTREAM_QUALITY_DATA_FAILURE"], [])

    q20_count = sum(quality >= 20 for quality in qualities)
    q30_count = sum(quality >= 30 for quality in qualities)

    expected = {
        "read-count": str(read_count),
        "total-base-count": str(total_bases),
        "minimum-read-length": str(min(lengths)),
        "maximum-read-length": str(max(lengths)),
        "mean-read-length": _round_two(total_bases, read_count),
        "q20-or-higher-base-count": str(q20_count),
        "q30-or-higher-base-count": str(q30_count),
    }
    if total_bases == 0:
        expected["mean-phred-quality"] = "not-applicable"
        expected["q20-or-higher-percent"] = "not-applicable"
        expected["q30-or-higher-percent"] = "not-applicable"
    else:
        expected["mean-phred-quality"] = _round_two(sum(qualities), total_bases)
        expected["q20-or-higher-percent"] = _round_two(100 * q20_count, total_bases)
        expected["q30-or-higher-percent"] = _round_two(100 * q30_count, total_bases)

    try:
        root = ET.parse(Path(artifact_path)).getroot()
    except Exception:
        return _result(False, ["ARTIFACT_PARSE_ERROR"], _COMMITMENTS)

    values = _observation_values(root)
    codes = []
    for observation_id, (encoding, _commitment) in _OBSERVATIONS.items():
        matches = values[observation_id]
        if not matches:
            codes.append("ARTIFACT_OBSERVATION_MISSING")
            continue
        if len(matches) != 1:
            codes.append("ARTIFACT_OBSERVATION_AMBIGUOUS")
            continue
        delivered = matches[0]
        if not _valid_encoding(encoding, delivered):
            codes.append("ARTIFACT_VALUE_ENCODING_INVALID")
            continue
        if delivered != expected[observation_id]:
            codes.append("SEMANTIC_MISMATCH")

    return _result(not codes, codes, _COMMITMENTS)
