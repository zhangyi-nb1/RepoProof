"""FrozenAdoptionIntent 落盘(RFC-008)。

产品产物,不是 evidence:写入 runs/_intents/(gitignored),内容
不可变(文件名含自身 sha 前缀,重复保存幂等)。UI 只读铁律不受
影响——写动作在本 core 模块完成,UI 仅调用。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

INTENTS_DIR = "_intents"


def save_frozen_intent(runs_root: Path, frozen: dict) -> Path:
    """保存冻结意向;同内容重复保存返回同一路径(幂等)。"""
    payload = json.dumps(frozen, ensure_ascii=False, sort_keys=True, indent=2)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    dest_dir = runs_root / INTENTS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"intent-{digest}.json"
    if not dest.exists():
        dest.write_text(payload, encoding="utf-8")
    return dest


def load_frozen_intents(runs_root: Path) -> list[dict]:
    """按文件名排序读取全部已冻结意向(缺目录 → 空表)。"""
    dest_dir = runs_root / INTENTS_DIR
    if not dest_dir.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(dest_dir.glob("intent-*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out
