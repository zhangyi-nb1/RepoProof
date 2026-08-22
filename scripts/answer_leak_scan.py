#!/usr/bin/env python3
"""答案泄漏扫描 —— 盲攻**开打之前**的前置自证(prereg-v2 §5 prep)。

盲攻的全部意义是"攻击者没见过答案"。这句话上一轮是**手工核对**的:
两条记录(`leak-scan-round2.json`)只留下了数字,没留下判据,复核者拿不到
可重跑的东西 —— 这正是 P1 要消灭的那种"经验没变成闸门"。本脚本把它变成
可复算的仪器。

三步,缺一步就判死:

1. **自校准取指纹** —— 指纹 = 答案补丁的新增行里,**parent 树上没有的**那些。
   为什么要减 parent:攻击者合法可见整棵 parent 树,parent 上已有的行出现
   在交付件里天经地义,拿它当泄漏会把每个候选都误杀(自校准的字面含义)。
2. **扫交付面** —— 交付树 + 题面 + 攻击者能看的一切。任一指纹命中即泄漏。
3. **种植自证** —— 往一份合成文档里种一条已知指纹,扫描器必须逮住它。
   没有这步,"命中 0"和"扫描器根本没在跑"在证据上一模一样(M69c 同律:
   沉默不是通过)。

判决遵循同一条线:**没扫 ≠ 干净**(`judge_leak_scan(None)` 判死),
**指纹为 0 ≠ 干净**(校准不出指纹说明尺子没搭上,扫了个寂寞)。

用法:
    .venv/bin/python scripts/answer_leak_scan.py \\
        --candidate sqlglot-7953 \\
        --parent-tree <candidates/<cid>/parent_tree> \\
        --answer-patch <candidates/<cid>/answer/full.patch> \\
        --statement <candidates/<cid>/statement.md> \\
        --delivery <盲攻交付树> \\
        --out docs/evidence/d5_hunt/leak-scan-<轮次>.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: 太短的行没有识别力("return", "}", "else:" 满树都是),当指纹只会制造
#: 假阳性。24 个规范化字符是实测下来能把 click/sqlglot 的样板行滤干净的线。
MIN_FINGERPRINT_LEN = 24

_WS = re.compile(r"\s+")
#: 只读文本;二进制与构建残渣不进扫描面(它们不是攻击者的阅读材料)
_SKIP_PARTS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache"}
_SKIP_SUFFIX = {".pyc", ".pyo", ".so", ".png", ".jpg", ".gif", ".ico", ".whl"}


def normalize(line: str) -> str:
    """空白规范化 —— 缩进/换行样式不同不该让同一行躲过扫描。"""
    return _WS.sub(" ", line).strip()


def is_fingerprint_candidate(norm_line: str) -> bool:
    return len(norm_line) >= MIN_FINGERPRINT_LEN


def added_lines(patch_text: str) -> list[str]:
    """unified diff 的新增行(`+++` 文件头不算)。"""
    out: list[str] = []
    for raw in patch_text.splitlines():
        if raw.startswith("+++") or not raw.startswith("+"):
            continue
        out.append(raw[1:])
    return out


def calibrate_fingerprints(patch_text: str, parent_lines: set[str]) -> list[str]:
    """答案新增行 − parent 已有行 = 指纹。

    去重后排序输出,好让证据可逐条复核(集合直接落盘顺序不稳,复核者
    diff 两次跑会看到假差异)。
    """
    seen: set[str] = set()
    for line in added_lines(patch_text):
        n = normalize(line)
        if is_fingerprint_candidate(n) and n not in parent_lines:
            seen.add(n)
    return sorted(seen)


def scan_documents(fingerprints: list[str], documents: dict[str, str]) -> list[dict]:
    """指纹 × 文档 → 命中清单。

    逐行规范化后比对(而不是子串搜原文):否则交付件里一处缩进差异就能让
    整条答案行溜过去 —— 泄漏检测被格式打败是最没道理的漏法。
    """
    fps = set(fingerprints)
    if not fps:
        return []
    hits: list[dict] = []
    for where, text in sorted(documents.items()):
        for i, raw in enumerate(text.splitlines(), start=1):
            n = normalize(raw)
            if n in fps:
                hits.append({"fingerprint": n, "where": where, "line": i})
    return hits


def selfcheck(fingerprints: list[str]) -> bool:
    """种植自证:把一条真指纹埋进合成文档,扫描器必须逮住。

    用**真**指纹而不是造一条假的:假指纹只证明"能匹配某个字符串",真指纹
    才证明"能匹配这一批指纹"(长度门槛、规范化都在链路上)。
    """
    if not fingerprints:
        return False
    planted = fingerprints[0]
    doc = f"# 合成自证文档\n无关行\n{planted}\n再一行无关的\n"
    return bool(scan_documents(fingerprints, {"_selfcheck_planted": doc}))


def judge_leak_scan(scan: dict | None) -> tuple[bool, list[str]]:
    """扫描结果 → 准入判决。没扫、扫空、扫到,三种都判死。"""
    if scan is None:
        return False, ["未做答案泄漏扫描 —— 没扫不等于干净,盲攻前置必须给证据"]
    problems: list[str] = []
    if not scan.get("selfcheck_planted_detected"):
        problems.append(
            "种植自证未命中 —— 扫描器没被证明活着,'命中 0'与'根本没扫'不可分辨")
    if scan.get("fingerprints_calibrated", 0) <= 0:
        problems.append(
            "校准不出任何指纹 —— 答案新增行全在 parent 上已有(或全被长度门槛"
            "滤掉),这把尺子没搭上被测面,扫了个寂寞")
    hits = scan.get("leak_hits") or []
    if hits:
        preview = [f"{h['where']}:{h['line']}" for h in hits[:5]]
        problems.append(
            f"答案指纹在攻击者可见面命中 {len(hits)} 处(如 {preview})—— "
            "盲攻不成立,攻击者能直接抄")
    return (not problems), problems


# ------------------------------------------------------------------ 驱动
def read_tree_lines(root: Path) -> set[str]:
    out: set[str] = set()
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix in _SKIP_SUFFIX:
            continue
        if _SKIP_PARTS & set(f.parts):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for raw in text.splitlines():
            out.add(normalize(raw))
    return out


def read_tree_documents(root: Path, label: str) -> dict[str, str]:
    docs: dict[str, str] = {}
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix in _SKIP_SUFFIX:
            continue
        if _SKIP_PARTS & set(f.parts):
            continue
        try:
            docs[f"{label}/{f.relative_to(root).as_posix()}"] = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
    return docs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--parent-tree", required=True, help="自校准基准(攻击者合法可见)")
    ap.add_argument("--answer-patch", required=True)
    ap.add_argument("--statement", required=True,
                    help="题面 —— 泄漏风险最高的一件(上游正文可能贴了 diff)")
    ap.add_argument("--delivery", default="", help="盲攻交付树(有就一并扫)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    parent = Path(a.parent_tree).expanduser()
    patch = Path(a.answer_patch).expanduser().read_text(encoding="utf-8")
    parent_lines = read_tree_lines(parent)
    fingerprints = calibrate_fingerprints(patch, parent_lines)

    documents = {"statement.md": Path(a.statement).expanduser().read_text(encoding="utf-8")}
    if a.delivery:
        documents.update(read_tree_documents(Path(a.delivery).expanduser(), "delivery"))

    hits = scan_documents(fingerprints, documents)
    scan = {
        "candidate": a.candidate,
        "fingerprints_calibrated": len(fingerprints),
        "parent_lines_calibrated": len(parent_lines),
        "documents_scanned": len(documents),
        "leak_hits": hits,
        "selfcheck_planted_detected": selfcheck(fingerprints),
        "note": "自校准:parent 已有行不算指纹(攻击者合法可见整棵 parent)",
    }
    ok, problems = judge_leak_scan(scan)
    scan["verdict"] = {"ok": ok, "problems": problems}

    dest = Path(a.out).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if dest.exists():
        existing = json.loads(dest.read_text(encoding="utf-8"))
    existing[a.candidate] = scan
    dest.write_text(json.dumps(existing, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")

    print(f"指纹 {len(fingerprints)} 条(parent 基准 {len(parent_lines)} 行)"
          f"/ 扫 {len(documents)} 份 / 命中 {len(hits)} / "
          f"自证 {'活' if scan['selfcheck_planted_detected'] else '死'}")
    print("判决:" + ("**通过**" if ok else "**判死**"))
    for p in problems:
        print("  -", p)
    print(f"记录:{dest}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
