"""平凡回归:seam 包自身行为不被适配破坏。"""
import json
from pathlib import Path

import pytest

import user_capability


def test_health():
    assert user_capability.health() == "ok"


def test_examples_file_intact():
    p = Path(__file__).parent / "fixtures" / "public_documents.json"
    assert json.loads(p.read_text(encoding="utf-8"))["examples"]


def test_direct_mode_declares_not_implemented(monkeypatch):
    monkeypatch.delenv("REPOPROOF_ADAPTATION_DIR", raising=False)
    with pytest.raises(NotImplementedError):
        user_capability.run("x")
