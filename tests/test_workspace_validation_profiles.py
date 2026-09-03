"""新格式的 Harness-owned 结构校验(M6.3 前置):xlsx/pptx/png/ics/ipynb/mo。

不变量:结构层由 Harness 用 stdlib 独立机检,不依赖上游库;每个 profile 有
正控(最小合法字节)与负控(损坏/伪装字节),损坏必须得到稳定公开码。
"""

from __future__ import annotations

import io
import json
import struct
import zipfile
import zlib
from pathlib import Path

import pytest

from repoproof.domain.models import WorkspaceArtifactRule
from repoproof.execution.workspace_bundle import WorkspaceBundleError, _validate_format


def _rule(profile: str, pattern: str = "artifact.bin") -> WorkspaceArtifactRule:
    return WorkspaceArtifactRule(
        path_pattern=pattern,
        role="r",
        media_type="application/octet-stream",
        validation_profile=profile,
    )


def _ooxml(parts: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="x"/>')
        for name, payload in parts.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def _png(width: int = 1, height: int = 1) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = zlib.compress(b"\x00" + b"\x00\x00\x00" * width)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


def _mo(count: int = 1) -> bytes:
    header = struct.pack("<IIIIIII", 0x950412DE, 0, count, 28, 28 + count * 8, 0, 0)
    table = struct.pack("<II", 0, 0) * count * 2
    return header + table


_ICS_GOOD = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nSUMMARY:x\r\n folded\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
_ICS_UNBALANCED = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nEND:VCALENDAR\r\n"
_NB_GOOD = json.dumps(
    {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [{"cell_type": "code", "source": "1", "metadata": {}, "outputs": []}],
    }
).encode()
_NB_NO_OUTPUTS = json.dumps(
    {"nbformat": 4, "metadata": {}, "cells": [{"cell_type": "code", "source": "1", "metadata": {}}]}
).encode()
_XLSX_GOOD = _ooxml({"xl/worksheets/sheet1.xml": b"<worksheet/>"})


@pytest.mark.parametrize(
    ("profile", "good", "bad"),
    [
        ("xlsx_v1", _XLSX_GOOD, _ooxml({"xl/worksheets/sheet1.xml": b"<worksheet>"})),
        ("xlsx_v1", _XLSX_GOOD, _ooxml({"ppt/slides/slide1.xml": b"<sld/>"})),
        ("pptx_v1", _ooxml({"ppt/slides/slide1.xml": b"<sld/>"}), b"PK\x03\x04not-a-zip"),
        ("png_v1", _png(), _png()[:-8]),
        ("png_v1", _png(3, 2), b"\x89PNG\r\n\x1a\n" + b"\x00" * 30),
        ("ics_v1", _ICS_GOOD, _ICS_UNBALANCED),
        ("ics_v1", b"BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n", b"BEGIN:VCALENDAR\nEND:VCALENDAR\n"),
        ("ipynb_v1", _NB_GOOD, json.dumps({"nbformat": 3, "cells": []}).encode()),
        ("ipynb_v1", json.dumps({"nbformat": 4, "metadata": {}, "cells": []}).encode(), _NB_NO_OUTPUTS),
        ("mo_v1", _mo(2), b"\x00" * 40),
        ("mo_v1", _mo(0), _mo(50)[:40]),
    ],
)
def test_profile_accepts_minimal_valid_and_rejects_corrupt(
    tmp_path: Path, profile: str, good: bytes, bad: bytes
) -> None:
    path = tmp_path / "artifact.bin"
    path.write_bytes(good)
    _validate_format(path, _rule(profile))
    path.write_bytes(bad)
    with pytest.raises(WorkspaceBundleError) as caught:
        _validate_format(path, _rule(profile))
    assert caught.value.code.startswith("WORKSPACE_FORMAT_")


def test_new_profiles_are_visible_to_the_drafter_schema() -> None:
    from repoproof.adoption.intake.tool_drafter import _WORKSPACE_CONTRACT_DEFS

    rendered = json.dumps(_WORKSPACE_CONTRACT_DEFS)
    for profile in ("xlsx_v1", "pptx_v1", "png_v1", "ics_v1", "ipynb_v1", "mo_v1"):
        assert profile in rendered
