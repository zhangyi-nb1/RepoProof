"""fixture builder 的失败也要点名消息与位置(incident-builder-failure-diagnostics-opaque-*)。

现象:两个仓库上 `FIXTURE_BUILDER_FAILED` 的诊断只有裸异常类(`ValueError`),builder 被盲修
四次——reference 子进程早就带 `exception_message` 与源内帧定位,builder 子进程只发
`exception_type`。builder 与 reference 同为模型自己起草的控制件,消息与帧不是答案钥匙。

不变量:
  I1 builder 失败的公开细节形如 `Type: message @ fixture_builder.py:line fn (innermost file:line fn)`,
     消息去空白、有界(≤240),私有临时根被掩蔽;
  I2 该细节进 `FixtureBuilderError.detail`,自检轮的 `FIXTURE_BUILDER_FAILED` 诊断随行;
  I3 标记行缺失/损坏时回落为空串(既有行为),真跑成功路径不受影响。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from repoproof.adoption.intake.workspace_fixtures import (
    FixtureBlueprintV1,
    FixtureBuilderError,
    build_fixture_candidate,
)

_FAILING_BUILDER = '''from pathlib import Path


def _load_rows(parameters):
    raise ValueError("locale %r is not in the supported set" % parameters.get("locale"))


def build(blueprint, output_path: Path):
    rows = _load_rows(blueprint["parameters"])
    output_path.mkdir(parents=True)
    (output_path / "rows.txt").write_text(str(rows), encoding="utf-8")
'''

_WORKING_BUILDER = '''from pathlib import Path


def build(blueprint, output_path: Path):
    output_path.mkdir(parents=True)
    (output_path / "ok.txt").write_text("ok", encoding="utf-8")
'''


def _blueprint() -> FixtureBlueprintV1:
    return FixtureBlueprintV1(
        blueprint_id="anon-scn", title="anon", scenario="anon scenario", input_kind="directory",
        parameters={"locale": "xx-YY"},
    )


def _build(tmp_path: Path, source: str):
    builder = tmp_path / "fixture_builder.py"
    builder.write_text(source, encoding="utf-8")
    return build_fixture_candidate(
        blueprint=_blueprint(), builder_id="anon-builder", builder_source=builder,
        fixture_root=tmp_path / "fixtures", python_exe=sys.executable, isolation_required=False,
    )


def test_builder_failure_detail_names_message_and_location(tmp_path: Path) -> None:
    with pytest.raises(FixtureBuilderError) as caught:
        _build(tmp_path, _FAILING_BUILDER)
    assert caught.value.code == "FIXTURE_BUILDER_FAILED"
    detail = caught.value.detail
    assert detail.startswith("ValueError: ")
    assert "'xx-YY' is not in the supported set" in detail
    assert "fixture_builder.py:" in detail and "_load_rows" in detail
    assert "/rp-fixture-builder-" not in detail  # private temp root masked
    assert "\n" not in detail and len(detail) <= 400


def test_successful_builder_is_untouched(tmp_path: Path) -> None:
    candidate = _build(tmp_path, _WORKING_BUILDER)
    assert Path(candidate.fixture_path).is_dir()
