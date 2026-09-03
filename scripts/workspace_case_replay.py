"""M6.2 已完成工作区案例的零模型 replay 执行器(Core 修复后回归义务的官方载具)。

协议(与 2026-08-28 「不许第二把尺子」接缝纪律一致):
  1. 尺子 = 该 run 冻结的 oracle_snapshot/test_capability.py **原样执行**,
     公开样例 exact 金树、held-out 语义 verifier 的宽严分层由冻结契约自带,
     本脚本不重述、不重新发明任何比对逻辑;
  2. 运行时 = 该 task 的密封 bench wheelhouse(--no-index 离线装),
     与流水线测量环境同源 —— repo 开发 venv 不是合法测量环境;
  3. 被测物 = 导出工具包的临时副本,删 .venv 后 ./build.sh 离线重建
     (验证冻结 lock + vendor wheelhouse 自足,7db6e65 不变量);
  4. 结果 append-only 落 runs/evidence/workspace-replays/,不改写任何
     历史 run、合同或 ledger;失败不静默 —— exit 非零,按手册追 incident。

用法:
  .venv/bin/python scripts/workspace_case_replay.py \
      <tool_name>=<task_id>=<run_id> [...]
缺省跑当前全部 ACTIVE 工作区案例。
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEST_ROOT = Path("~/tools").expanduser()
BENCH_ROOT = Path("~/RepoProofBench").expanduser()
OUT_DIR = REPO / "runs" / "evidence" / "workspace-replays"

DEFAULT_CASES = [
    ("networkx-tool", "tool-networkx-tool-v4", "tool-networkx-tool-v4-20260901-013543"),
    ("datasette-tool", "tool-datasette-tool-v3", "tool-datasette-tool-v3-20260901-164106"),
    ("textual-taskdesk", "tool-textual-taskdesk-v3", "tool-textual-taskdesk-v3-20260901-180812"),
    ("marimo-tool", "tool-marimo-tool-v3", "tool-marimo-tool-v3-20260902-000237"),
    ("research-project-starter", "tool-research-project-starter-v3",
     "tool-research-project-starter-v3-20260902-005027"),
    ("csvkit-tool", "tool-csvkit-tool-v1", "tool-csvkit-tool-v1-20260902-014025"),
    ("pdfplumber-tool", "tool-pdfplumber-tool-v1", "tool-pdfplumber-tool-v1-20260902-020425"),
    ("trafilatura-tool", "tool-trafilatura-tool-v1", "tool-trafilatura-tool-v1-20260902-035547"),
]


def _current_framework_identity() -> dict[str, str]:
    head = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=10, check=True,
    ).stdout.strip()
    from repoproof.ui.services.product_jobs import _product_source_tree_sha256

    return {"framework_git_commit": head,
            "framework_tree_sha256": _product_source_tree_sha256()}


def replay_one(tool_name: str, task_id: str, run_id: str) -> dict:
    snapshot = REPO / "runs" / run_id / "oracle_snapshot"
    wheelhouse = BENCH_ROOT / task_id / "wheelhouse"
    tool_dir = DEST_ROOT / tool_name
    row: dict[str, object] = {
        "tool": tool_name, "task_id": task_id, "source_run_id": run_id,
    }
    for label, path in (("oracle_snapshot", snapshot),
                        ("task_wheelhouse", wheelhouse),
                        ("installed_tool", tool_dir)):
        if path.is_symlink() or not path.is_dir():
            row.update(ok=False, step="preconditions",
                       detail=f"{label} 缺失或不是普通目录")
            return row
    with tempfile.TemporaryDirectory(prefix="workspace-replay-") as raw:
        td = Path(raw)
        work = td / tool_name
        shutil.copytree(tool_dir, work, symlinks=False)
        shutil.rmtree(work / ".venv", ignore_errors=True)
        build = subprocess.run(["./build.sh"], cwd=work, capture_output=True,
                               text=True, timeout=900)
        if build.returncode != 0:
            row.update(ok=False, step="offline_rebuild",
                       detail=(build.stderr or build.stdout)[-400:])
            return row
        venv = td / "measure-venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)],
                       check=True, capture_output=True, timeout=300)
        # 业务运行时来自 task wheelhouse;pytest/verifier 依赖来自 Harness
        # 自有测试工具链(所有权分离,96e381d)—— 两个都离线。
        harness_toolchain = REPO / "upstream-cache" / "harness-test-wheelhouse-py312-v1"
        install = subprocess.run(
            [str(venv / "bin" / "pip"), "install", "-q",
             "--disable-pip-version-check", "--no-index",
             "--find-links", str(wheelhouse),
             "--find-links", str(harness_toolchain), "-r",
             str(work / "requirements.lock.txt"), "pytest"],
            capture_output=True, text=True, timeout=900,
        )
        if install.returncode != 0:
            row.update(ok=False, step="measure_runtime",
                       detail=(install.stderr or install.stdout)[-400:])
            return row
        stage = td / "oracle"
        shutil.copytree(snapshot, stage)
        env = dict(os.environ, REPOPROOF_TOOL_BIN=str(work / "bin" / tool_name))
        proc = subprocess.run(
            [str(venv / "bin" / "pytest"), "-q", "-p", "no:cacheprovider",
             str(stage / "test_capability.py")],
            capture_output=True, text=True, timeout=900, env=env, cwd=td,
        )
        row.update(ok=proc.returncode == 0, step="frozen_oracle_pytest",
                   pytest_exit=proc.returncode,
                   detail=proc.stdout.strip().splitlines()[-1][-300:]
                   if proc.stdout.strip() else proc.stderr[-300:])
        return row


def main(argv: list[str]) -> int:
    cases = DEFAULT_CASES
    if argv:
        parsed = []
        for item in argv:
            tool_name, task_id, run_id = item.split("=", 2)
            parsed.append((tool_name, task_id, run_id))
        cases = parsed
    identity = _current_framework_identity()
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    rows = [replay_one(*case) for case in cases]
    document = {
        "schema_version": 1,
        "protocol": "frozen-oracle-snapshot + sealed-task-wheelhouse + offline-rebuilt-package",
        "checked_at": stamp,
        **identity,
        "results": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"workspace-replay-{stamp}.json"
    out_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(json.dumps(document, ensure_ascii=False, indent=2))
    print(f"written: {out_path}")
    return 0 if all(row.get("ok") for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
