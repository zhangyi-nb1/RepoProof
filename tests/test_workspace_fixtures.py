from __future__ import annotations

import sys
from pathlib import Path

import pytest

from repoproof.adoption.intake.workspace_fixtures import (
    FixtureBlueprintV1,
    FixtureBuilderError,
    InputFixtureBundleV1,
    build_fixture_candidate,
    confirm_fixture_candidate,
    merge_regenerated_fixture_bundle,
    validate_fixture_blueprint_portable_paths,
)

_BUILDER = '''from pathlib import Path

def build(blueprint, output_path: Path):
    output_path.mkdir()
    (output_path / "brief.txt").write_text(blueprint["parameters"]["text"])
    (output_path / "data.bin").write_bytes(bytes([0, 1, 2, 255]))
'''


def _blueprint(identifier: str = "normal-study") -> FixtureBlueprintV1:
    return FixtureBlueprintV1(
        blueprint_id=identifier,
        title="Normal study",
        scenario="A realistic directory with text and binary data.",
        input_kind="directory",
        parameters={"text": "study"},
    )


def _build(tmp_path: Path, identifier: str = "normal-study"):
    source = tmp_path / f"{identifier}-builder.py"
    source.write_text(_BUILDER, encoding="utf-8")
    return build_fixture_candidate(
        blueprint=_blueprint(identifier),
        builder_id="synthetic-fixture-builder-v1",
        builder_source=source,
        fixture_root=tmp_path / "fixtures",
        python_exe=sys.executable,
        isolation_required=False,
    )


def test_frozen_builder_generates_real_directory_fixture(tmp_path: Path) -> None:
    candidate = _build(tmp_path)
    assert candidate.fixture_identity.kind == "directory"
    assert candidate.fixture_identity.file_count == 2
    assert Path(candidate.fixture_path, "data.bin").read_bytes() == bytes([0, 1, 2, 255])
    assert candidate.confirmed is False


def test_fixture_bundle_rejects_distinct_blueprints_with_identical_input_bytes(
    tmp_path: Path,
) -> None:
    first = _build(tmp_path, "ordinary-study")
    second = _build(tmp_path, "edge-study")

    assert first.blueprint.blueprint_id != second.blueprint.blueprint_id
    assert first.fixture_identity == second.fixture_identity
    with pytest.raises(ValueError, match="fixture inputs must be unique"):
        InputFixtureBundleV1(
            generation_id="anonymous-collision",
            candidates=(first, second),
        )


def test_model_blueprint_rejects_nonportable_generated_paths_but_allows_unicode_content(
) -> None:
    seed = FixtureBlueprintV1(
        blueprint_id="seed-project",
        title="Seed",
        scenario="Portable seed tree",
        input_kind="directory",
        parameters={"files": {"src/main.py": "print('seed')\n"}},
    )
    unsafe = FixtureBlueprintV1(
        blueprint_id="fresh-project",
        title="Fresh",
        scenario="A natural Unicode project scenario",
        input_kind="directory",
        parameters={"files": {"入口.py": "print('你好')\n"}},
    )
    safe = unsafe.model_copy(
        update={"parameters": {"files": {"src/entry.py": "print('你好')\n"}}}
    )

    with pytest.raises(
        FixtureBuilderError,
        match="FIXTURE_BLUEPRINT_NONPORTABLE_PATH",
    ):
        validate_fixture_blueprint_portable_paths(unsafe, seeds=(seed,))

    validate_fixture_blueprint_portable_paths(safe, seeds=(seed,))


def test_regeneration_preserves_exact_confirmed_fixture(tmp_path: Path) -> None:
    original = confirm_fixture_candidate(_build(tmp_path, "confirmed-study"))
    previous = InputFixtureBundleV1(
        generation_id="generation-one", candidates=(original,)
    )
    fresh = _build(tmp_path, "new-study")
    generated = InputFixtureBundleV1(
        generation_id="generation-two", candidates=(fresh,)
    )
    merged = merge_regenerated_fixture_bundle(previous, generated)
    assert [item.blueprint.blueprint_id for item in merged.candidates] == [
        "confirmed-study",
    ]
    assert merged.candidates[0].confirmed is True


def test_changed_regeneration_cannot_replace_or_duplicate_confirmed_id(
    tmp_path: Path,
) -> None:
    original = confirm_fixture_candidate(_build(tmp_path, "confirmed-study"))
    changed = original.model_copy(
        update={
            "confirmed": False,
            "fixture_identity": original.fixture_identity.model_copy(
                update={"sha256": "f" * 64}
            ),
        }
    )

    merged = merge_regenerated_fixture_bundle(
        InputFixtureBundleV1(
            generation_id="generation-one",
            candidates=(original,),
        ),
        InputFixtureBundleV1(
            generation_id="generation-two",
            candidates=(changed,),
        ),
    )

    assert merged.candidates == (original,)


def test_builder_cannot_publish_symlink_fixture(tmp_path: Path) -> None:
    source = tmp_path / "builder.py"
    source.write_text(
        "def build(blueprint, output_path):\n"
        "    output_path.symlink_to('/tmp', target_is_directory=True)\n",
        encoding="utf-8",
    )
    with pytest.raises(FixtureBuilderError) as caught:
        build_fixture_candidate(
            blueprint=_blueprint(),
            builder_id="unsafe-builder-v1",
            builder_source=source,
            fixture_root=tmp_path / "fixtures",
            python_exe=sys.executable,
            isolation_required=False,
        )
    assert caught.value.code == "WORKSPACE_SYMLINK_FORBIDDEN"


def test_builder_output_kind_must_match_blueprint(tmp_path: Path) -> None:
    source = tmp_path / "builder.py"
    source.write_text(
        "def build(blueprint, output_path):\n"
        "    output_path.write_text('not a directory')\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="output kind"):
        build_fixture_candidate(
            blueprint=_blueprint(),
            builder_id="wrong-kind-v1",
            builder_source=source,
            fixture_root=tmp_path / "fixtures",
            python_exe=sys.executable,
            isolation_required=False,
        )
