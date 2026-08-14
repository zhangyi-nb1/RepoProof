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
        # 阶段闸门语义(TESTPLAN §6):该阶段冻结任务 ≥1 真实模型 PASS。
        # `passes` 已扣除四类:已裁定无效 / 探索性加发 / 冒烟 / **机制消融**
        # (2026-08-14 增第四道:E1 消融与 AR 判据测试不回答"任务可判可过")。
        "gate_met": {s: stages[s]["passes"] >= 1 for s in STAGES},
        # 能力分母拆分(判据 K2):一个 passes 数字会被读成"模型能力通过数"。
        # 这里显式说明每一类各是什么,以及**目前没有任何 Held-out 能力发次**。
        "_denominators": {
            "passes": "阶段闸门数 —— 存在性证明(任务可判且可过),**不是能力率**",
            "all_valid_run_outcomes": "全部有效发次里的 PASS 数(含机制消融)",
            "development_baseline_runs": "开发套件(T1–T3)上的常规发次",
            "mechanism_ablation_runs": "E1/AR 机制与判据实验 —— 不计能力",
            "heldout_model_evaluation_runs": "未见任务能力评测 —— **第二宿主未建,恒为 0**",
            "treatment_not_delivered_runs": "处理臂分配了但实测零生效 —— 不计处理效应",
            "post_hoc_classified_runs": "分类发生在看到结果之后(自曝,防伪装成预注册)",
            "provisional_evidence_runs": "证据已降级 —— **仍计入 passes(未被改判)**,"
                                         "但引用时必须带上 caveat;见 provisional_evidence",
        },
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
