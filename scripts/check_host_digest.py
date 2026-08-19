"""发车绊线:bench 宿主母树摘要 ↔ 建包清单逐一核对(E1 事故 20260818 制度化)。

事故背景(E1-DSH-MINIMAL-BRIDGE-1 序 2,run 130403):dsh 臂真模型开局
`cd /` 自毁 cwd 信息后全盘寻路,把 `~/RepoProofBench/hb1-sqlglot-8042/host`
**母树**误认作工作区,在里面建 venv、跑 pytest、改写 sqlglot/lineage.py ——
判决工作区零改动(patch 0 字节),母树摘要与建包时不符。母树是后续所有
会话快照的源:若未察觉继续发车,污染树会被静默快照进每一发新会话。

本脚本 = 该缺口的检测面收口,进发车纪律:

- **发车前**:核对目标宿主摘要,不符即拒绝发车(停批,先查再修);
- **发次后**:再核一次,把破坏归因到刚结束的那一发(会话装配总在
  破坏之前,所以"发前绿 + 发后红"唯一指向本发的 worker)。

P0 起(2026-08-20)加**锁态执法**:母树须由 lock_bench_hosts.py 锁写
(全树零写位),未锁同样拒绝发车 —— 摘要是检测面,锁写是预防面,
发车纪律两道都要绿。锁不影响摘要:`_digest_tree` 只算路径 + 内容。

量法复用原件(prepare_hb1_hosts 同款):`blind_attack_admission._digest_tree`
对整树内容寻址,清单 = docs/evidence/hb1_hosts/prepare-hb1.json(建包自证)。
只读,零副作用;不符/未锁退出码 1,前置缺失退出码 2。

用法:
    .venv/bin/python scripts/check_host_digest.py            # 全部三宿主
    .venv/bin/python scripts/check_host_digest.py sqlglot-8042
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import blind_attack_admission as _baa  # noqa: E402

EVIDENCE = REPO / "docs" / "evidence" / "hb1_hosts" / "prepare-hb1.json"
BENCH_ROOT = Path("~/RepoProofBench").expanduser()


def check(cids: list[str] | None = None) -> int:
    if not EVIDENCE.is_file():
        print(f"[digest] 建包清单不在:{EVIDENCE}", file=sys.stderr)
        return 2
    hosts = json.loads(EVIDENCE.read_text(encoding="utf-8")).get("hosts", {})
    targets = cids or sorted(hosts)
    bad = 0
    for cid in targets:
        h = hosts.get(cid)
        if not h or not h.get("host_digest"):
            print(f"[digest] {cid}: 清单无摘要(deployed 失败或名字不对)",
                  file=sys.stderr)
            return 2
        host = Path(h["bench_dir"]) / "host"
        if not host.is_dir():
            print(f"[digest] {cid}: 宿主树不在:{host}", file=sys.stderr)
            return 2
        now = _baa._digest_tree(host)
        ok = now == h["host_digest"]
        print(f"[digest] {cid}: {'一致 ✓' if ok else '**不符 ✗ —— 停批,先查再修**'}")
        bad += 0 if ok else 1
        # 锁态执法:host 与 wheelhouse 全树零写位才放行(预防面)。
        import stat as _stat
        for sub in ("host", "wheelhouse"):
            d = Path(h["bench_dir"]) / sub
            if not d.is_dir():
                continue
            writable = sum(
                1 for p in [d, *sorted(d.rglob("*"))]
                if not p.is_symlink()
                and _stat.S_IMODE(p.stat().st_mode) & 0o222)
            locked = writable == 0
            print(f"[lock] {cid}/{sub}: "
                  f"{'已锁 ✓' if locked else f'**可写条目 {writable} ✗ —— 未锁写,先 lock_bench_hosts.py lock**'}")
            bad += 0 if locked else 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(check(sys.argv[1:] or None))
