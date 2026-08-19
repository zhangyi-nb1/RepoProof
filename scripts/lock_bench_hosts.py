#!/usr/bin/env python3
"""bench 宿主母树锁写(P0 越区硬隔离,2026-08-20)。

背景(E1 代 1 事故,预注册附录二登记的结构性隐患):worker 以本机用户
身份跑,母树可写 —— 序 2 pro 越区在 `~/RepoProofBench/hb1-sqlglot-8042/host`
里建 venv、跑测、改 lineage.py。发车摘要绊线(check_host_digest.py)是
**检测面**;本脚本是**预防面**:母树全树去写位,越区写直接 EPERM,
污染从"事后发现"变成"根本写不进"。

三个动作:
    lock    host/ 与 wheelhouse/ 全树(含目录)去掉**所有**写位(a-w)。
            目录去写尤其关键 —— 代 1 的越区是往母树里**建新文件**
            (.venv/…),只锁文件锁不住建新。
    unlock  属主写位恢复(u+w)。仅供重建包(prepare_hb1_hosts.py)期间
            使用 —— 它的 measure 步会在母树旁建临时 venv、redeploy 会
            rmtree 重铺,锁着必然响亮失败。建完必须立刻再 lock。
    status  逐宿主报告可写条目计数(0 = 已锁)。

安全边界:
  - 只动 `~/RepoProofBench/<cid>/` 下的 `host` 与 `wheelhouse` 两个子树,
    cid 清单取自建包清单(与绊线同一事实源);路径 resolve 后必须仍在
    BENCH_ROOT 之内,否则拒绝(符号链接不跟出去)。
  - 摘要不受影响:`_digest_tree` 只算路径 + 内容,不算权限位 ——
    lock/unlock 前后 host_digest 同值(实测见 P0 收口记录)。
  - 会话区 `_sessions/` 不在目标内,永不触碰。

用法:
    .venv/bin/python scripts/lock_bench_hosts.py status
    .venv/bin/python scripts/lock_bench_hosts.py lock
    .venv/bin/python scripts/lock_bench_hosts.py unlock sqlglot-8042
"""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EVIDENCE = REPO / "docs" / "evidence" / "hb1_hosts" / "prepare-hb1.json"
BENCH_ROOT = Path("~/RepoProofBench").expanduser().resolve()
SUBTREES = ("host", "wheelhouse")


def _targets(cids: list[str] | None) -> list[tuple[str, Path]]:
    if not EVIDENCE.is_file():
        print(f"[lock] 建包清单不在:{EVIDENCE}", file=sys.stderr)
        raise SystemExit(2)
    hosts = json.loads(EVIDENCE.read_text(encoding="utf-8")).get("hosts", {})
    out: list[tuple[str, Path]] = []
    for cid in (cids or sorted(hosts)):
        h = hosts.get(cid)
        if not h or not h.get("bench_dir"):
            print(f"[lock] {cid}: 清单无此宿主", file=sys.stderr)
            raise SystemExit(2)
        base = Path(h["bench_dir"]).expanduser().resolve()
        if not str(base).startswith(str(BENCH_ROOT) + "/"):
            print(f"[lock] {cid}: bench_dir 出界 {base} —— 拒绝", file=sys.stderr)
            raise SystemExit(2)
        for sub in SUBTREES:
            d = base / sub
            if d.is_dir():
                out.append((f"{cid}/{sub}", d))
    return out


def _entries(root: Path):
    yield root
    for p in sorted(root.rglob("*")):
        if not p.is_symlink():          # 符号链接不 chmod(会跟到目标)
            yield p


def _apply(root: Path, op: str) -> tuple[int, int]:
    changed = total = 0
    for p in _entries(root):
        total += 1
        mode = stat.S_IMODE(p.stat().st_mode)
        new = (mode & ~0o222) if op == "lock" else (mode | 0o200)
        if new != mode:
            p.chmod(new)
            changed += 1
    return changed, total


def _writable_count(root: Path) -> tuple[int, int]:
    n = total = 0
    for p in _entries(root):
        total += 1
        if stat.S_IMODE(p.stat().st_mode) & 0o222:
            n += 1
    return n, total


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"lock", "unlock", "status"}:
        print(__doc__, file=sys.stderr)
        return 2
    op, cids = argv[0], argv[1:] or None
    rc = 0
    for label, d in _targets(cids):
        if op == "status":
            n, total = _writable_count(d)
            state = "已锁 ✓" if n == 0 else f"**可写条目 {n} ✗**"
            print(f"[lock] {label}: {state}({total} 条)")
            rc = rc or (1 if n else 0)
        else:
            changed, total = _apply(d, op)
            n, _ = _writable_count(d)
            verdict = ("已锁 ✓" if n == 0 else f"仍有可写 {n} ✗") if op == "lock" \
                else f"可写 {n}"
            print(f"[lock] {label}: {op} 改 {changed}/{total} 条 → {verdict}")
            if op == "lock" and n:
                rc = 1
    if op == "unlock":
        print("[lock] 提醒:unlock 仅供重建包;建完立刻 lock 并跑 "
              "check_host_digest.py 验摘要+锁态。")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
