"""本地工具注册表(M3-b · RFC-010 §六 M3)。

一个 append-friendly 的 JSON 索引(`<dest_root>/.repoproof-registry.json`),
记录"这台机器上有哪些已验证工具、证据在哪"。纪律:
  - 注册表是**索引不是事实源** —— verdict/哈希以工具包内 tool.json 与
    evidence/ 为准;list 时逐项复核 manifest 是否仍在、verification 是否
    仍非空,漂移如实标注(MISSING/UNVERIFIED),不静默剔除;
  - `--scan` 可补录目录下未经注册的工具包(exported_at 记 null,
    provenance 标 scan —— 不伪造导出时间)。
"""

from __future__ import annotations

import json
from pathlib import Path

REGISTRY_NAME = ".repoproof-registry.json"


def _load(dest_root: Path) -> dict:
    p = Path(dest_root) / REGISTRY_NAME
    if not p.is_file():
        return {"schema_version": 1, "tools": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def _save(dest_root: Path, doc: dict) -> None:
    (Path(dest_root) / REGISTRY_NAME).write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")


def register_tool(dest_root: Path, tool_dir: Path, *,
                  run_id: str | None, exported_at: str | None) -> dict:
    """导出后登记(pipeline 显式调用;export 本身保持纯函数)。"""
    tool_dir = Path(tool_dir)
    manifest = json.loads((tool_dir / "tool.json").read_text(encoding="utf-8"))
    prov_p = tool_dir / "evidence" / "provenance.json"
    task_id = ""
    if prov_p.is_file():
        task_id = json.loads(prov_p.read_text(encoding="utf-8")).get("task_id", "")
    entry = {
        "path": str(tool_dir),
        "task_id": task_id,
        "run_id": run_id or (manifest.get("verification") or {}).get("run_id"),
        "verdict": (manifest.get("verification") or {}).get("verdict"),
        "contract_sha256": (manifest.get("verification") or {}).get("contract_sha256"),
        "source": manifest.get("source", {}),
        "summary": manifest.get("summary", ""),
        "exported_at": exported_at,
    }
    doc = _load(Path(dest_root))
    doc["tools"][manifest["name"]] = entry
    _save(Path(dest_root), doc)
    return entry


def list_tools(dest_root: Path, *, scan: bool = False) -> list[dict]:
    """→ 每项 {name, status, ...};status ∈ OK|MISSING|UNVERIFIED。"""
    dest_root = Path(dest_root)
    doc = _load(dest_root)
    if scan and dest_root.is_dir():
        for d in sorted(p for p in dest_root.iterdir() if p.is_dir()):
            mf = d / "tool.json"
            if not mf.is_file():
                continue
            try:
                m = json.loads(mf.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if m.get("name") and m["name"] not in doc["tools"]:
                doc["tools"][m["name"]] = {
                    "path": str(d),
                    "run_id": (m.get("verification") or {}).get("run_id"),
                    "verdict": (m.get("verification") or {}).get("verdict"),
                    "contract_sha256": (m.get("verification") or {}).get(
                        "contract_sha256"),
                    "source": m.get("source", {}),
                    "summary": m.get("summary", ""),
                    "exported_at": None,           # scan 补录:不伪造导出时间
                    "provenance": "scan",
                }
        _save(dest_root, doc)

    out: list[dict] = []
    for name, entry in sorted(doc["tools"].items()):
        row = {"name": name, **entry}
        mf = Path(entry["path"]) / "tool.json"
        if not mf.is_file():
            row["status"] = "MISSING"
        else:
            try:
                m = json.loads(mf.read_text(encoding="utf-8"))
                row["status"] = ("OK" if (m.get("verification") or {}).get("verdict")
                                 else "UNVERIFIED")
            except ValueError:
                row["status"] = "MISSING"
        out.append(row)
    return out
