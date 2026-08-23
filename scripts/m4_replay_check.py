"""M4 replay_success 自动口径的执行器(预注册冻结口径,append-only 记账)。

对注册表里每个已验证工具:临时拷贝全包 → 删 .venv → ./build.sh(联网,
从 lock 装)→ ./bin/<name> --help 必须 exit 0。结果逐行追加
benchmarks/v2/m4_replay.jsonl(不覆盖;重跑同 task_id 追加新行,指标
脚本取该文件**首行**?否 —— 取最后由 compute 的 dict 覆盖序决定,
故本脚本按 append-only + 后行覆盖前行读取语义,与台账惯例一致)。

口径边界(如实,预注册同文):自动口径 = 构建可重复 + 入口可达,
**弱于**每发已跑过的 clean replay(后者含全量验收);能力级真实输入
抽验并入 false_success 人工审计单。
"""

from __future__ import annotations

import datetime
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "benchmarks" / "v2" / "m4_replay.jsonl"


def check_one(tool_dir: Path, name: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="m4-replay-") as td:
        work = Path(td) / name
        shutil.copytree(tool_dir, work)
        shutil.rmtree(work / ".venv", ignore_errors=True)
        b = subprocess.run(["./build.sh"], cwd=work, capture_output=True,
                           text=True, timeout=600)
        if b.returncode != 0:
            return {"ok": False, "step": "build",
                    "detail": (b.stderr or b.stdout)[-300:]}
        h = subprocess.run([str(work / "bin" / name), "--help"],
                           capture_output=True, text=True, timeout=120)
        if h.returncode != 0:
            return {"ok": False, "step": "help",
                    "detail": (h.stderr or h.stdout)[-300:]}
        return {"ok": True, "step": "done", "detail": ""}


def main() -> int:
    dest_root = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 \
        else Path("~/tools").expanduser()
    reg_p = dest_root / ".repoproof-registry.json"
    tools = json.loads(reg_p.read_text(encoding="utf-8"))["tools"]
    rows = []
    for name, entry in sorted(tools.items()):
        if not entry.get("verdict"):
            continue
        got = check_one(Path(entry["path"]), name)
        row = {"task_id": entry.get("task_id"), "name": name, **got,
               "checked_at": datetime.datetime.now(datetime.UTC)
               .strftime("%Y-%m-%dT%H:%M:%SZ")}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
    with OUT.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
