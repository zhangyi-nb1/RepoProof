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
import os
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

# Playwright 在这里**只是钉版 Chromium 的分发器**,不是运行期依赖 ——
# browser-use 0.13.7 直接走 CDP(`cdp_use`)+ `executable_path`,与 playwright
# 无关。选它是因为它把"哪个 playwright 版本对应哪个 Chromium build"钉得很死,
# 是本机能拿到的最可复现的 Chromium 来源。
PLAYWRIGHT_PIN = "1.62.0"

# 浏览器落点在 runtime 根**之内**(而不是 ~/Library/Caches/ms-playwright):
# 这样它自动进封存摘要,并且随 runtime 一起受 host_guard 保护。用户
# 2026-08-15 指令:这一份封存后一直用,后面的 candidate / T3-SIDECAR /
# 真实模型发次都用它,**不要每次重下"当前 playwright 对应的 Chromium"**。
BROWSERS_SUBDIR = "browsers"

PINNED = [
    PinnedSource(distribution="browser-use", version="0.13.7",
                 resolved_commit="32601887cfbc9f4f1e3cad3e2b678e56aeaeaae4",
                 url="https://github.com/browser-use/browser-use"),
    PinnedSource(distribution="playwright", version=PLAYWRIGHT_PIN,
                 url="https://pypi.org/project/playwright/"),
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
        # Chromium 的分发器,钉版
        [venv_py, "-m", "pip", "install", "-q", f"playwright=={PLAYWRIGHT_PIN}"],
        # **完整 Chromium,不用 --only-shell**(用户 2026-08-15 指令)。
        # headless shell 是独立的精简构建;完整 Chromium 的新 headless 模式更
        # 接近真实 Chrome、功能也更全。第一次就该把"浏览器能力缺失"这个混杂
        # 变量减掉 —— 否则将来一条负控红了,分不清是判据抓住了它,还是浏览器
        # 少了个能力。
        [venv_py, "-m", "playwright", "install", "chromium"],
        # 冻结依赖闭包 —— 封存后 execute 期不再解析
        [venv_py, "-m", "pip", "freeze", "--all"],
    ]


def find_chromium(root: Path) -> Path | None:
    """封存件里的 Chromium 可执行文件。**只在封存目录里找,绝不回落到系统 Chrome。**

    回落是很自然的一个"顺手":找不到就用系统的。但那会让 runtime 悄悄不可
    复现 —— 系统 Chrome 会自动更新,而我们封存这份浏览器的全部理由就是让它
    不再变。找不到就报找不到。
    """
    b = Path(root) / BROWSERS_SUBDIR
    if not b.is_dir():
        return None
    # 只认 `chromium-<build>/`,**不认 `chromium_headless_shell-<build>/`**。
    # playwright 会把两者都装下来;用户 2026-08-15 明确要完整构建 —— headless
    # shell 是独立的精简构建,拿它当浏览器等于自带一个"能力缺失"的混杂变量,
    # 将来某条负控红了会分不清是判据抓住了它还是浏览器少了个能力。
    roots = [d for d in b.glob("chromium-*") if d.is_dir()
             and not d.name.startswith("chromium_headless_shell")]
    for d in sorted(roots):
        # macOS 是 app bundle,Linux 是裸二进制。不写死名字 —— 名字改过好几次
        # (Chromium / Google Chrome for Testing),写死必然过期。
        #
        # 但**必须限定在顶层 bundle**:用 `**` 递归会掉进
        # `…/Frameworks/…/Helpers/Google Chrome for Testing Helper (Alerts).app/…`,
        # 那是渲染器/告警辅助进程,不是浏览器主程序。实测第一次就选中了它 ——
        # 一个"能找到可执行文件"式的查找,找到的未必是要的那一个。
        for exe in sorted(d.glob("chrome-*/*.app/Contents/MacOS/*")):
            if exe.is_file() and os.access(exe, os.X_OK):
                return exe
        for exe in sorted(d.glob("chrome-*/chrome")):
            if exe.is_file() and os.access(exe, os.X_OK):
                return exe
    return None


def chromium_version(exe: Path) -> str:
    """让它**真跑一下**报版本 —— 找到一个文件不等于拿到一个能用的浏览器。

    这是封存的最后一道:文件在、可执行位在、路径也对,但它可能是个辅助进程
    (实测踩过)或者缺依赖起不来。跑一次 `--version` 才算数。
    """
    import subprocess

    r = subprocess.run([str(exe), "--version"],                      # noqa: S603
                       capture_output=True, text=True, check=False, timeout=60)
    return (r.stdout or r.stderr).strip()


def _chromium_pin(root: Path) -> PinnedSource | None:
    exe = find_chromium(root)
    if exe is None:
        return None
    # playwright 的目录名就是它钉的 build 号:chromium-1234
    build = exe.relative_to(Path(root) / BROWSERS_SUBDIR).parts[0].split("-", 1)[-1]
    return PinnedSource(distribution="chromium", version=build,
                        resolved_commit=f"playwright-{PLAYWRIGHT_PIN}",
                        url=str(exe.relative_to(root)))


def _freeze_lock(root: Path) -> None:
    """把依赖闭包写成 lock 文件,进封存件的摘要。"""
    import subprocess

    venv_py = root / ".venv" / "bin" / "python"
    out = subprocess.run([str(venv_py), "-m", "pip", "freeze", "--all"],   # noqa: S603
                         capture_output=True, text=True, check=True).stdout
    (root / "requirements.lock").write_text(out, encoding="utf-8")


def _seal(m: RuntimeManifest) -> int:
    """把树封存成清单。幂等、不联网。

    封存不完整时**删掉清单**,而不是留一份看起来完整的 —— 留着的话
    `verify_sealed` 会报"被动过",把"没封完"误诊成"有人改过",而这两件事的
    修法完全不同。
    """
    from repoproof.execution.provisioning import digest_tree

    _freeze_lock(RUNTIME_ROOT)
    chrome = _chromium_pin(RUNTIME_ROOT)
    if chrome is None:
        (RUNTIME_ROOT / "runtime_manifest.json").unlink(missing_ok=True)
        print("\n✗ 封存目录里找不到完整 Chromium —— 浏览器没装进 runtime 根,"
              "那样它不进封存摘要、也不受保护。清单已删除(封存未完成)。",
              file=sys.stderr)
        return 1

    m.pinned = [s for s in m.pinned if s.distribution != "chromium"] + [chrome]
    exe = find_chromium(RUNTIME_ROOT)
    m.extras["chromium_executable"] = str(exe.relative_to(RUNTIME_ROOT))
    m.extras["chromium_full_build"] = True          # 非 --only-shell
    ver = chromium_version(exe)
    if "Chrome" not in ver and "Chromium" not in ver:
        (RUNTIME_ROOT / "runtime_manifest.json").unlink(missing_ok=True)
        print(f"\n✗ 找到的可执行文件跑不出浏览器版本({ver!r})—— 很可能选中了"
              "辅助进程而不是主程序。清单已删除(封存未完成)。", file=sys.stderr)
        return 1
    if "Helper" in exe.name:
        (RUNTIME_ROOT / "runtime_manifest.json").unlink(missing_ok=True)
        print(f"\n✗ 选中的是辅助进程:{exe.name}。清单已删除。", file=sys.stderr)
        return 1
    m.extras["chromium_version_string"] = ver
    m.artifact_digest = digest_tree(RUNTIME_ROOT)
    (RUNTIME_ROOT / "runtime_manifest.json").write_text(m.to_json(), encoding="utf-8")

    ok, why = verify_sealed(RUNTIME_ROOT)
    print(f"\n{'✓' if ok else '✗'} {why}")
    print(f"lock:{(RUNTIME_ROOT / 'requirements.lock').stat().st_size} 字节")
    print(f"Chromium:build {chrome.version}(完整构建,非 headless shell)")
    print(f"  {m.extras['chromium_version_string']}")
    print(f"  {m.extras['chromium_executable']}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--go", action="store_true", help="真联网构建")
    ap.add_argument("--verify", action="store_true", help="只核封存件")
    ap.add_argument("--force", action="store_true", help="已存在时重建")
    ap.add_argument("--seal", action="store_true",
                    help="**不联网**,只对已存在的树重做封存(lock/浏览器登记/摘要)")
    args = ap.parse_args()

    if args.seal:
        # 封存是幂等的、且**不联网** —— 分出来是因为为了改一行清单重下 554M
        # 的浏览器毫无道理,而"重下一次"恰恰会引入"这次拿到的是不是同一份"
        # 的问题,正是用户要避免的。
        try:
            m = RuntimeManifest.load(RUNTIME_ROOT)
        except ProvisioningError as e:
            print(str(e), file=sys.stderr)
            return 2
        return _seal(m)

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
                      steps=plan(), allow_network=True,
                      env={"PLAYWRIGHT_BROWSERS_PATH":
                           str(RUNTIME_ROOT / BROWSERS_SUBDIR)})
    except ProvisioningError as e:
        print(f"\n构建失败:{e}", file=sys.stderr)
        return 1

    rc = _seal(m)
    if rc:
        return rc
    print("\n**下一步把网络关掉**,用封存件跑零模型 smoke —— 跑不通说明还有"
          "东西在偷偷联网。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
