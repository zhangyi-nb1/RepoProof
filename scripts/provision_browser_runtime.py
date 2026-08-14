#!/usr/bin/env python3
"""构建 `rt-sidecar-browser-v1` 的封存 runtime —— **一次性联网**。

用户 2026-08-15 授权:允许 harness 侧做一次联网安装,定义为
**runtime provisioning / build 阶段**,**不是**给 agent 或 benchmark
execution 放开网络。这条边界由 `execution/provisioning.py` 的结构保证:

- 联网只在本脚本(provision)里发生;`verify_sealed()`(execute 侧)的签名里
  **根本没有 `allow_network` 这个参数** —— 想在发次期联网,得先改 API 形状。
- 产物封存在 `~/RepoProofRuntimes/`,已进保护目录(`host_guard.DEFAULT_PROTECTED`)
  —— agent 读写它都发不出去。不放 `~/RepoProofBench/` 下,是因为那里的护栏
  是"白名单外一律算游离物",往白名单里塞一个 runtime 正是 LESSONS #29 判过
  的错法。
- **agent 的会话环境一个字不改**:仍是 `PIP_NO_INDEX` + 冻结 wheelhouse。

钉版(与 T3 契约同源,不另起一套):

    browser-use 0.13.7 @ 32601887cfbc9f4f1e3cad3e2b678e56aeaeaae4

用法::

    .venv/bin/python scripts/provision_browser_runtime.py            # 干跑,只打印计划
    .venv/bin/python scripts/provision_browser_runtime.py --go       # 真联网构建
    .venv/bin/python scripts/provision_browser_runtime.py --verify   # 只核封存件
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from repoproof.execution.provisioning import (  # noqa: E402
    PinnedSource,
    ProvisioningError,
    RuntimeManifest,
    provision,
    verify_sealed,
)

PROFILE_ID = "rt-sidecar-browser-v1"
RUNTIME_ROOT = Path("~/RepoProofRuntimes").expanduser() / PROFILE_ID
UPSTREAM_SNAPSHOT = REPO / "upstream-cache" / "upstream-32601887cfbc"

PINNED = [
    PinnedSource(distribution="browser-use", version="0.13.7",
                 resolved_commit="32601887cfbc9f4f1e3cad3e2b678e56aeaeaae4",
                 url="https://github.com/browser-use/browser-use"),
]


def plan() -> list[list[str]]:
    """构建步骤。逐条固定 argv,不走 shell。

    从**本地钉版快照**装(`upstream-cache/upstream-32601887cfbc`),不从 PyPI
    拉 `browser-use` —— 快照的 commit 已经核过(`git rev-parse HEAD` 与契约
    的 `resolved_commit` 逐字相同)。联网只用来取它的**依赖**,那些依赖由
    pip 按上游自己的钉版解析,随后写进 lock。

    这样"上游本体是哪份字节"完全不依赖网络,可复现;网络只影响依赖闭包,
    而那一份会被 lock 住并连同摘要一起封存。
    """
    py = sys.executable
    venv_py = str(RUNTIME_ROOT / ".venv" / "bin" / "python")
    return [
        [py, "-m", "venv", str(RUNTIME_ROOT / ".venv")],
        [venv_py, "-m", "pip", "install", "-q", "--upgrade", "pip", "wheel"],
        # 上游本体来自本地钉版快照;它的依赖此刻联网解析
        [venv_py, "-m", "pip", "install", str(UPSTREAM_SNAPSHOT)],
        # 冻结依赖闭包 —— 封存后 execute 期不再解析
        [venv_py, "-m", "pip", "freeze", "--all"],
    ]


def _freeze_lock(root: Path) -> None:
    """把依赖闭包写成 lock 文件,进封存件的摘要。"""
    import subprocess

    venv_py = root / ".venv" / "bin" / "python"
    out = subprocess.run([str(venv_py), "-m", "pip", "freeze", "--all"],   # noqa: S603
                         capture_output=True, text=True, check=True).stdout
    (root / "requirements.lock").write_text(out, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--go", action="store_true", help="真联网构建")
    ap.add_argument("--verify", action="store_true", help="只核封存件")
    ap.add_argument("--force", action="store_true", help="已存在时重建")
    args = ap.parse_args()

    if args.verify:
        ok, why = verify_sealed(RUNTIME_ROOT)
        print(("✓ " if ok else "✗ ") + why)
        if ok:
            m = RuntimeManifest.load(RUNTIME_ROOT)
            for s in m.pinned:
                print(f"  钉版 {s.distribution}=={s.version} @ {s.resolved_commit[:12]}")
        return 0 if ok else 1

    if not UPSTREAM_SNAPSHOT.is_dir():
        print(f"钉版快照不在:{UPSTREAM_SNAPSHOT}", file=sys.stderr)
        return 2

    print(f"profile   {PROFILE_ID}")
    print(f"落点      {RUNTIME_ROOT}  (已在 host_guard 保护目录内)")
    print(f"上游本体  {UPSTREAM_SNAPSHOT.name}(本地快照,不走网络)")
    for s in PINNED:
        print(f"钉版      {s.distribution}=={s.version} @ {s.resolved_commit[:12]}")
    print("\n步骤:")
    for a in plan():
        print("  ", " ".join(a[:6]) + (" …" if len(a) > 6 else ""))

    if not args.go:
        print("\n干跑。真要构建请加 --go —— 那一步**会联网**"
              "(仅 provision 阶段;agent 权限与 benchmark 执行不受影响)。")
        return 0

    if RUNTIME_ROOT.exists():
        if not args.force:
            print(f"\n{RUNTIME_ROOT} 已存在;要重建请加 --force", file=sys.stderr)
            return 3
        shutil.rmtree(RUNTIME_ROOT)

    print("\n开始联网构建 …")
    try:
        m = provision(profile_id=PROFILE_ID, root=RUNTIME_ROOT, pinned=PINNED,
                      steps=plan(), allow_network=True)
    except ProvisioningError as e:
        print(f"\n构建失败:{e}", file=sys.stderr)
        return 1

    _freeze_lock(RUNTIME_ROOT)
    # lock 写在 provision 之后,摘要要重算一遍并回写
    from repoproof.execution.provisioning import digest_tree

    m.artifact_digest = digest_tree(RUNTIME_ROOT)
    (RUNTIME_ROOT / "runtime_manifest.json").write_text(m.to_json(), encoding="utf-8")

    ok, why = verify_sealed(RUNTIME_ROOT)
    print(f"\n{'✓' if ok else '✗'} {why}")
    print(f"lock:{(RUNTIME_ROOT / 'requirements.lock').stat().st_size} 字节")
    print("\n**下一步把网络关掉**,用封存件跑零模型 smoke —— 跑不通说明还有"
          "东西在偷偷联网。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
