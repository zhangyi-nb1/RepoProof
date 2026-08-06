"""Deterministic fake model for FREE Gate 3B integration tests.

Implements the mini-swe-agent Model protocol with a fixed script of
responses. Never calls any network or LLM. cost per call = 0.0 and the
backend reports it honestly as 0.0 (is_free_fake marker)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeModel:
    script: list[dict]
    """Each entry: {"content": str, "actions": [{"command": ...}, ...]}"""
    is_free_fake: bool = True
    calls: int = 0
    observed: list[list[dict]] = field(default_factory=list)

    def query(self, messages: list[dict], **kwargs) -> dict:
        step = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return {
            "role": "assistant",
            "content": step.get("content", ""),
            "extra": {"actions": list(step.get("actions", [])), "cost": 0.0, "timestamp": time.time()},
        }

    def format_message(self, **kwargs) -> dict:
        extra = kwargs.pop("extra", {})
        return {**kwargs, "extra": extra}

    def format_observation_messages(self, message: dict, outputs: list[dict], template_vars: dict) -> list[dict]:
        self.observed.append(outputs)
        return [
            {
                "role": "user",
                "content": (
                    f"<returncode>{o.get('returncode')}</returncode>\n<output>\n{o.get('output', '')}\n</output>"
                ),
                "extra": {"raw_output": {k: v for k, v in o.items() if k != "extra"}, "obs_extra": o.get("extra", {})},
            }
            for o in outputs
        ]

    def get_template_vars(self, **kwargs) -> dict[str, Any]:
        return {"model_name": "fake-deterministic"}

    def serialize(self) -> dict:
        return {"model": {"name": "fake-deterministic", "calls": self.calls}}
