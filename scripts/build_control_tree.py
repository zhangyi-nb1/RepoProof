"""控制组(正控/负控)对象的**唯一**装配器 —— 建完就拆,不留残留。

背景(LESSONS #41):五物验证此前是手工做的 —— 在 `~/RepoProofBench-quarantine/`
下手搓 7 棵 `_scratch_t2_*` 树,跑完不拆。装配方法没有任何地方记录过,于是
那 7 棵树成了**唯一**的配方载体,谁也不敢删;它们同时是 H9-a 意义上的答案
残留(树里就有 `controls/` 的正文),order-21 直接 `cp` 走的就是这一类东西。

配方(2026-08-13 逐路径核对,nc1 与上游差集为 5 项、上游无缺失):
    钉版上游 + 任务包 `fixtures/` + 任务包 `public_tests/`
    + `controls/<name>/research_jobs.py` + 追加到 `rag_api.py` 末尾的挂载两行

**默认建完即拆**。想留下必须显式 `--keep`,并且脚本会告诉你它现在是残留 ——
H9-a 会因此拒开下一发真实运行(这是设计,不是故障)。

用法:
    # 建树、在树里跑一条命令、然后拆掉(推荐,残留窗口 = 命令时长)
    .venv/bin/python scripts/build_control_tree.py \
        --task benchmarks/v2/tasks/t2_open_deep_research_v4 \
        --control nc1_no_odr --dest /tmp/ctl_nc1 -- pytest -q public_tests

    # 只建不跑(建完立刻拆,只用来验证配方能装上)
    .venv/bin/python scripts/build_control_tree.py --task ... --control positive --dest ...

    # 留在盘上(会打印残留警告)
    ... --keep
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

DEFAULT_UPSTREAM = Path.home() / "RepoProofBench" / "offerclaw-t2-odr"
SKIP_DIRS = {".venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}
COPIED_TASK_DIRS = ("fixtures", "public_tests")

# 追加到 rag_api.py 末尾。正控那棵手搓树在 import 前多一行中文注释,纯装饰,
# 这里统一用不带注释的形式 —— 没有任何检查器逐字节比对 rag_api.py。
MOUNT_BLOCK = "\nfrom research_jobs import mount_research_api  # noqa: E402\nmount_research_api(app)\n"
MOUNT_MARKER = "mount_research_api(app)"


def _ignore(_dir: str, names: list[str]) -> set[str]:
    return {n for n in names if n in SKIP_DIRS}


def build(task_dir: Path, control: str, dest: Path, upstream: Path) -> Path:
    """把一个控制组对象装配到 dest,返回 dest。dest 必须不存在。"""
    src_control = task_dir / "controls" / control
    if not src_control.is_dir():
        available = sorted(p.name for p in (task_dir / "controls").iterdir() if p.is_dir())
        raise SystemExit(f"没有这个控制组:{control};可选 {available}")
    if not upstream.is_dir():
        raise SystemExit(f"钉版上游不在:{upstream}")
    if dest.exists():
        raise SystemExit(f"dest 已存在,拒绝覆盖:{dest}")

    shutil.copytree(upstream, dest, ignore=_ignore, symlinks=True)
    for name in COPIED_TASK_DIRS:
        src = task_dir / name
        if src.is_dir():
            shutil.copytree(src, dest / name, ignore=_ignore, dirs_exist_ok=True)
    for f in sorted(src_control.glob("*.py")):
        shutil.copy2(f, dest / f.name)

    rag = dest / "rag_api.py"
    text = rag.read_text()
    if MOUNT_MARKER not in text:
        rag.write_text(text + MOUNT_BLOCK)

    verify(dest, src_control)
    return dest


def verify(dest: Path, src_control: Path) -> None:
    """装配后自检 —— 装错了要当场知道,不能等到五物验证的结论出来才发现。"""
    for f in sorted(src_control.glob("*.py")):
        got = dest / f.name
        if not got.is_file():
            raise SystemExit(f"自检失败:控制组文件没落地 {f.name}")
        if got.read_bytes() != f.read_bytes():
            raise SystemExit(f"自检失败:{f.name} 与 controls/ 下的原件不一致")
    text = (dest / "rag_api.py").read_text()
    n = text.count(MOUNT_MARKER)
    if n != 1:
        raise SystemExit(f"自检失败:rag_api.py 里挂载出现 {n} 次(应为 1)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", required=True, type=Path, help="任务包目录(含 controls/)")
    ap.add_argument("--control", required=True, help="控制组名,如 positive / nc1_no_odr")
    ap.add_argument("--dest", required=True, type=Path, help="装配目标目录(必须不存在)")
    ap.add_argument("--upstream", type=Path, default=DEFAULT_UPSTREAM, help=f"钉版上游(默认 {DEFAULT_UPSTREAM})")
    ap.add_argument("--keep", action="store_true", help="跑完不拆(会打印残留警告)")
    ap.add_argument("cmd", nargs="*", help="在树里执行的命令,置于 -- 之后")
    args = ap.parse_args(argv)

    dest = args.dest.resolve()
    build(args.task.resolve(), args.control, dest, args.upstream.expanduser().resolve())
    print(f"已装配 {args.control} -> {dest}")

    rc = 0
    try:
        if args.cmd:
            rc = subprocess.run(args.cmd, cwd=dest).returncode
    finally:
        if args.keep:
            print(f"!! 保留在盘上:{dest}\n"
                  f"!! 它含 controls/ 正文,是 H9-a 意义上的答案残留 —— "
                  f"下一发真实运行会被 preflight 拒开,跑之前请自行删除。", file=sys.stderr)
        else:
            shutil.rmtree(dest, ignore_errors=True)
            print(f"已拆除 {dest}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
