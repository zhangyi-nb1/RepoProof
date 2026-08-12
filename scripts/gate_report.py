"""V2 宿主闸门数字的**唯一**产出器(零 LLM、确定性、可复算)。

背景(PROCESS-INDEPENDENCE-PLAN §5-P0-1):T1–T4 的通过数此前只以手打散文
活在 LESSONS_LOG/批报告里,`check_public_claims.py` 的事实源
(benchmark_summary.json)全文零 offerclaw —— 于是"T1 3 个 PASS"这种错数字
在闸门里躺了 3 天,靠用户质疑才被发现(LESSONS #30)。

规则:任何对外声明的闸门数字必须出自本脚本产出的 `docs/v2_gate.json`;
散文只解释、不下判断。输出确定性(sort_keys、无时间戳),并携带两个事实源
文件的 sha256 —— 台账变动后旧 json 立即可被 `--check` 判为过期。

用法:
    .venv/bin/python scripts/gate_report.py            # 打印到 stdout
    .venv/bin/python scripts/gate_report.py --write    # 写 docs/v2_gate.json
    .venv/bin/python scripts/gate_report.py --check    # 与已提交文件比对,漂移即非零退出
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from repoproof.persistence.bench_records import count_passes  # noqa: E402

GATE_JSON = REPO / "docs" / "v2_gate.json"
STAGES = ("T1", "T2", "T3", "T4")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "MISSING"


def compute(project_root: Path = REPO) -> dict:
    """从 runs.jsonl ⋈ adjudications.jsonl 重算闸门(唯一合法算法=count_passes)。"""
    stages = {s: count_passes(project_root, task_prefix=f"{s.lower()}-") for s in STAGES}
    bench = project_root / "benchmarks" / "v2"
    return {
        "_source": "scripts/gate_report.py — 闸门数字只能出自此脚本;散文只解释不下判断",
        "inputs": {
            "runs_jsonl_sha256": _sha256(bench / "runs.jsonl"),
            "adjudications_jsonl_sha256": _sha256(bench / "adjudications.jsonl"),
        },
        "stages": stages,
        # 阶段闸门语义(TESTPLAN §6):该阶段冻结任务 ≥1 真实模型 PASS
        "gate_met": {s: stages[s]["passes"] >= 1 for s in STAGES},
        "all_runs": count_passes(project_root),
    }


def render(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def check(project_root: Path = REPO) -> list[str]:
    """已提交的 v2_gate.json 必须与实时重算逐字节一致;缺失/漂移即报错。"""
    if not GATE_JSON.exists():
        return ["docs/v2_gate.json 缺失 —— 先跑 scripts/gate_report.py --write"]
    fresh = render(compute(project_root))
    committed = GATE_JSON.read_text(encoding="utf-8")
    if fresh != committed:
        return ["docs/v2_gate.json 与台账重算不一致(台账变动后未再生成,"
                "或有人手改了 json)—— 跑 scripts/gate_report.py --write 并复核 diff"]
    return []


if __name__ == "__main__":
    if "--check" in sys.argv:
        problems = check()
        print(json.dumps({"ok": not problems, "failures": problems},
                         ensure_ascii=False, indent=2))
        sys.exit(1 if problems else 0)
    out = render(compute())
    if "--write" in sys.argv:
        GATE_JSON.write_text(out, encoding="utf-8")
        print(f"已写 {GATE_JSON}")
    print(out)
