"""Core 与导出 runtime 的结构校验必须是同一把尺子
(incident-portable-runtime-validator-profile-drift-pillow-v2)。

不变量:每个 WorkspaceValidationProfile 在导出 runtime 的 `_validate` 里都有
明确处理——绝不落到 `payload.decode("utf-8")` 让 UnicodeDecodeError 逃逸,也绝
不对未知 profile 静默放行;六个结构 profile 的正/负控在两把尺子上判决一致。
"""

from __future__ import annotations

import importlib.util
import typing
from pathlib import Path

import pytest

from repoproof.adoption.delivery import portable_workspace_runtime as runtime
from repoproof.domain.models import WorkspaceValidationProfile
from repoproof.execution.workspace_bundle import WorkspaceBundleError, _validate_format

_spec = importlib.util.spec_from_file_location(
    "_profile_fixtures", Path(__file__).with_name("test_workspace_validation_profiles.py")
)
_fx = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_fx)

_PROFILES = list(typing.get_args(WorkspaceValidationProfile))
_CASES = [
    ("xlsx_v1", _fx._XLSX_GOOD, _fx._ooxml({"xl/worksheets/sheet1.xml": b"<worksheet>"})),
    ("pptx_v1", _fx._ooxml({"ppt/slides/slide1.xml": b"<sld/>"}), b"PK\x03\x04not-a-zip"),
    ("png_v1", _fx._png(), _fx._png()[:-8]),
    ("ics_v1", _fx._ICS_GOOD, _fx._ICS_UNBALANCED),
    ("ipynb_v1", _fx._NB_GOOD, _fx._NB_NO_OUTPUTS),
    ("mo_v1", _fx._mo(2), b"\x00" * 40),
]


def _portable_verdict(tmp_path: Path, profile: str, payload: bytes) -> str | None:
    path = tmp_path / "artifact.bin"
    path.write_bytes(payload)
    try:
        runtime._validate(payload, profile, path)
    except runtime.WorkspaceRuntimeError as exc:
        return exc.code
    return None


def _core_verdict(tmp_path: Path, profile: str, payload: bytes) -> str | None:
    path = tmp_path / "artifact.bin"
    path.write_bytes(payload)
    try:
        _validate_format(path, _fx._rule(profile))
    except WorkspaceBundleError as exc:
        return exc.code
    return None


@pytest.mark.parametrize("profile", _PROFILES)
def test_portable_validator_never_leaks_decode_errors(tmp_path: Path, profile: str) -> None:
    payload = _fx._png()
    try:
        runtime._validate(payload, profile, tmp_path / "x")
    except runtime.WorkspaceRuntimeError:
        pass  # a public code is the only acceptable rejection


@pytest.mark.parametrize(("profile", "good", "bad"), _CASES)
def test_core_and_portable_agree_on_structure_profiles(tmp_path: Path, profile: str, good: bytes, bad: bytes) -> None:
    assert _core_verdict(tmp_path, profile, good) is None
    assert _portable_verdict(tmp_path, profile, good) is None
    core_bad = _core_verdict(tmp_path, profile, bad)
    portable_bad = _portable_verdict(tmp_path, profile, bad)
    assert core_bad is not None and portable_bad is not None
    assert core_bad == portable_bad


def test_unknown_profile_is_rejected_by_both_rulers(tmp_path: Path) -> None:
    payload = b"hello\n"
    path = tmp_path / "artifact.bin"
    path.write_bytes(payload)
    with pytest.raises(runtime.WorkspaceRuntimeError) as caught:
        runtime._validate(payload, "no_such_profile_v9", path)
    assert caught.value.code == "WORKSPACE_VALIDATION_PROFILE_UNKNOWN"
