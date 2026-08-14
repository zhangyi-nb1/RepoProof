"""从发次的会话里取出交付 —— **harness 侧**,在会话销毁之前。

取件失败要**明说取件失败**,不能含糊成"采纳不成立":前者是 harness 的问题
(路径变了、作业没落盘),后者是被测方的问题,两者修法完全不同。
"""
from __future__ import annotations

import json
from pathlib import Path

JOBS_DIRNAME = "page_facts_jobs"


def extract(host_dir: Path) -> list[dict] | None:
    """返回 [{"request_nonce":..., "facts":...}, ...];取不到返回 None。"""
    d = Path(host_dir) / JOBS_DIRNAME
    if not d.is_dir():
        return None
    out: list[dict] = []
    for f in sorted(d.glob("*.json")):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except Exception:                                        # noqa: BLE001
            continue
        for item in doc.get("facts") or []:
            if "request_nonce" in item:
                out.append({"request_nonce": item["request_nonce"],
                            "facts": item.get("facts", "")})
    return out or None
