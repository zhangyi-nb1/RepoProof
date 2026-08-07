"""ORACLE — capability acceptance for adopt-frontmatter-local-ingest-v1-v2.

Reference-calibrated against the PINNED python-frontmatter v1.3.0 in
the pinned container. v2 record schema splits the old ambiguous flag:
frontmatter_present (upstream recognised+stripped a block) and
metadata_nonempty (>=1 key). Guard checks assert the HOST
InputContractGuard (code INVALID_DOCUMENT_INPUT); upstream parse
failures must surface as IngestError code UPSTREAM_PARSE_ERROR.
Runtime-held-out from agents; node ids are frozen in the collection
manifest and mapped in the RequirementSpec.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from rag_ingest import INGEST_RECORD_FIELDS, IngestError, ingest_documents

FIXDIR = Path(__file__).parent / "fixtures"
PUBLIC = FIXDIR / "public_documents.json"
HELD_OUT = FIXDIR / "held_out_documents.json"
REFERENCE = json.loads((FIXDIR / "reference_records.json").read_text(encoding="utf-8"))["fixtures"]

FIXTURES = (PUBLIC, HELD_OUT)
IDS = ["public", "held"]

BAD_YAML_TEXT = "---\nkey: [unclosed\n---\nBody.\n"


def _request(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _by_doc(response: dict) -> dict[str, dict]:
    return {r.get("doc_id", "?"): r for r in response["records"]}


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_output_matches_reference(fixture: Path) -> None:
    request = _request(fixture)
    by_doc = _by_doc(ingest_documents(request))
    ref = REFERENCE[fixture.name]
    for doc in request["documents"]:
        did = doc["doc_id"]
        assert did in by_doc, f"no record for {did}"
        got, want = by_doc[did], ref[did]
        assert got["frontmatter_present"] == want["frontmatter_present"], did
        assert got["metadata_nonempty"] == want["metadata_nonempty"], did
        assert got["metadata"] == want["metadata"], f"{did}: metadata differs"
        assert got["content"] == want["content"], f"{did}: content differs"


def test_flag_truth_table_public() -> None:
    """The public truth-table semantics, asserted on the public docs
    that embody each row (empty block true/false split, unclosed fence,
    JSON fences)."""
    by_doc = _by_doc(ingest_documents(_request(PUBLIC)))
    expected = {
        "d-101-standard-yaml": (True, True),
        "d-102-plain-no-frontmatter": (False, False),
        "d-104-empty-yaml-frontmatter": (True, False),
        "d-105-unclosed-fence": (False, False),
        "d-107-json-frontmatter-kv": (True, True),
        "d-108-json-frontmatter-empty": (True, False),
    }
    for did, (present, nonempty) in expected.items():
        rec = by_doc[did]
        assert (rec["frontmatter_present"], rec["metadata_nonempty"]) == (present, nonempty), did


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_record_schema(fixture: Path) -> None:
    for rec in ingest_documents(_request(fixture))["records"]:
        assert set(rec.keys()) == set(INGEST_RECORD_FIELDS)


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_order_one_to_one(fixture: Path) -> None:
    request = _request(fixture)
    got = [r["doc_id"] for r in ingest_documents(request)["records"]]
    assert got == [d["doc_id"] for d in request["documents"]]


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_json_serializable(fixture: Path) -> None:
    json.dumps(ingest_documents(_request(fixture)), ensure_ascii=False)


def test_repeat_stable_input_untouched() -> None:
    request = _request(PUBLIC)
    snapshot = copy.deepcopy(request)
    assert ingest_documents(request) == ingest_documents(_request(PUBLIC))
    assert request == snapshot


def test_upstream_parse_error_code() -> None:
    request = {"documents": [{"doc_id": "e-bad-yaml", "text": BAD_YAML_TEXT}]}
    with pytest.raises(IngestError) as exc:
        ingest_documents(request)
    assert exc.value.code == "UPSTREAM_PARSE_ERROR"


# ---- HOST InputContractGuard (owner: HOST_INPUT_GUARD) ----


def _expect_guard(documents: list) -> None:
    with pytest.raises(IngestError) as exc:
        ingest_documents({"documents": documents})
    assert exc.value.code == "INVALID_DOCUMENT_INPUT"


def test_guard_rejects_none_text() -> None:
    _expect_guard([{"doc_id": "g-none", "text": None}])


def test_guard_rejects_missing_text() -> None:
    _expect_guard([{"doc_id": "g-missing"}])


def test_guard_rejects_bad_doc_id() -> None:
    _expect_guard([{"doc_id": "", "text": "x"}])
    _expect_guard([{"text": "x"}])


@pytest.mark.parametrize("bad_text", [123, ["x"], {"x": 1}], ids=["int", "list", "dict"])
def test_guard_rejects_nonstring_text(bad_text) -> None:
    _expect_guard([{"doc_id": "g-type", "text": bad_text}])


def test_guard_rejects_nondict_document() -> None:
    _expect_guard(["not-a-dict"])
