#!/usr/bin/env python3
"""构建 `rt-dsh-minimal-0.1.0rc6-v1` 的封存 runtime —— **一次性联网**。

DSH 集成线阶段 1(决策:`docs/adr/ADR-DSH-MINIMAL-AGENT-BACKEND.md`)。
联网边界沿 `execution/provisioning.py` 的结构保证:联网只发生在本脚本的
`--go`;`verify_sealed()`(execute 侧)的签名里**没有 `allow_network`**。
产物封存 `~/RepoProofRuntimes/rt-dsh-minimal-0.1.0rc6-v1/`(host_guard
保护目录,agent 够不着;不放 `~/RepoProofBench/` 的理由同
`rt-sidecar-browser-v1`:往宿主白名单里塞 runtime 是 LESSONS #29 判过的
错法)。

钉死之物(`PINS`,缺一或 hash 不符即 **fail closed** —— 装都不装,
遑论封存):

    deepseek-harness-sdk         0.1.0rc6   PyPI wheel(py3-none-any)
    deepseek-harness-runtime-bin 0.1.0rc6   PyPI wheel(macosx_14_0_arm64)
    examples/jsonrpc-agent/minimal.cordis.yml @ 47f94385   官方 SDK 正典
        minimal 组合,**原样不改**(派生配置必须换 composition id,第一轮
        不派生)
    LICENSE @ 同 commit(MIT)

版本与四枚 hash 于 **2026-08-17 对 PyPI JSON API 实核**,与指导文档
(`RepoProof_DSH_Minimal_SDK_集成开发指导报告_20260817.md` §6)所载逐字
一致。composition 钉 **commit 不钉 tag**:PyPI 版本 ↔ 官方 tag 的映射
官方未公示,凭猜测填 tag 正是指导文档 §6.4 明令禁止的事。

离线可重建:`--go` 的 venv 安装步用 `--no-index --find-links wheels/`
—— 安装本身不走网,断网重建 = 同一条命令再跑一遍。

用法::

    .venv/bin/python scripts/provision_dsh_runtime.py            # 干跑,只打印计划
    .venv/bin/python scripts/provision_dsh_runtime.py --go       # 真联网构建 + 封存
    .venv/bin/python scripts/provision_dsh_runtime.py --verify   # 只核封存件(无网)
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from repoproof.execution.provisioning import (  # noqa: E402
    PinnedSource,
    provision,
    verify_sealed,
)

PROFILE_ID = "rt-dsh-minimal-0.1.0rc6-v1"
RUNTIME_ROOT = Path("~/RepoProofRuntimes").expanduser() / PROFILE_ID
SDK_VERSION = "0.1.0rc6"
SOURCE_COMMIT = "47f943859bef60e4160492346772ded9b24f765a"  # 官方仓 master @ 2026-08-13
UPSTREAM_REPO = "https://github.com/deepseek-ai/deepseek-harness"
_RAW = f"https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/{SOURCE_COMMIT}"
_PYPI = "https://files.pythonhosted.org/packages"

REL_SDK_WHEEL = f"wheels/deepseek_harness_sdk-{SDK_VERSION}-py3-none-any.whl"
REL_RT_WHEEL = f"wheels/deepseek_harness_runtime_bin-{SDK_VERSION}-py3-none-macosx_14_0_arm64.whl"
REL_CONFIG = f"config/minimal.upstream.{SDK_VERSION}.cordis.yml"
REL_LICENSE = "config/LICENSE"

# 仓内参考副本(供评审与 diff;运行期用的是封存根里的那份)。两份都钉同一
# 枚 hash —— 漂移任何一份都会被 --verify 点名。
REPO_CONFIG_COPY = f"configs/dsh/minimal.upstream.{SDK_VERSION}.cordis.yml"
REPO_LICENSE_COPY = "third_party/deepseek-harness/LICENSE"

# SDK 的依赖闭包(0.1.0rc6 → pydantic<3,>=2.12 及其传递依赖)。
# 2026-08-17 由 `pip download` 实解;逐枚本地 sha256 与 PyPI 官方 JSON 摘要
# 交叉核验一致后才入表。pydantic_core 是 **cp312** wheel —— 封存 venv 钉在
# Python 3.12(`--go` 前置核,版本不符拒跑,不许"换个解释器碰运气")。
DEP_PINS: dict[str, str] = {
    "wheels/annotated_types-0.8.0-py3-none-any.whl":
        "f072f4d804ea359e4eaf198b1af7a8b0943881a87f31bb764f8bf219bb9419e0",
    "wheels/pydantic-2.13.4-py3-none-any.whl":
        "45a282cde31d808236fd7ea9d919b128653c8b38b393d1c4ab335c62924d9aba",
    "wheels/pydantic_core-2.46.4-cp312-cp312-macosx_11_0_arm64.whl":
        "962ccbab7b642487b1d8b7df90ef677e03134cf1fd8880bf698649b22a69371f",
    "wheels/typing_extensions-4.16.0-py3-none-any.whl":
        "481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8",
    "wheels/typing_inspection-0.4.4-py3-none-any.whl":
        "65b8397ba37ccbce054456aaccddfc91e6e3083c92824df348d96ca832f3f147",
}

DEP_FETCH: dict[str, str] = {
    "wheels/annotated_types-0.8.0-py3-none-any.whl":
        f"{_PYPI}/99/91/8acff4f5e50511b911bbccb72b8628a49c68ce14148cd9f6431094859a90/"
        "annotated_types-0.8.0-py3-none-any.whl",
    "wheels/pydantic-2.13.4-py3-none-any.whl":
        f"{_PYPI}/fd/7b/122376b1fd3c62c1ed9dc80c931ace4844b3c55407b6fb2d199377c9736f/"
        "pydantic-2.13.4-py3-none-any.whl",
    "wheels/pydantic_core-2.46.4-cp312-cp312-macosx_11_0_arm64.whl":
        f"{_PYPI}/19/95/6195171e385007300f0f5574592e467c568becce2d937a0b6804f218bc49/"
        "pydantic_core-2.46.4-cp312-cp312-macosx_11_0_arm64.whl",
    "wheels/typing_extensions-4.16.0-py3-none-any.whl":
        f"{_PYPI}/49/d3/b8441a820a491ddfc024b0b0cf0393375b75ea13866d9c66727e54c2fc80/"
        "typing_extensions-4.16.0-py3-none-any.whl",
    "wheels/typing_inspection-0.4.4-py3-none-any.whl":
        f"{_PYPI}/67/81/4add07e5172b7ac40d8ed5ff580409a7801a4fe26d529bdd915401dabfbe/"
        "typing_inspection-0.4.4-py3-none-any.whl",
}

PINS: dict[str, str] = {
    REL_SDK_WHEEL: "8a05421be4298196cf94383e0a3164b020f5f5977a8d30019cc5add64cb208eb",
    REL_RT_WHEEL: "2bbd65edd52dfc340d74f88a890e8031a272a820e58406c2de1f5f5dee51bd9f",
    REL_CONFIG: "4ddf99b5492fac7b578e3caddb0158815e44d5db176ba0aeab57012d35299fca",
    REL_LICENSE: "ebb4f09972aee8608be255debaf78451a68e95c290f55c240dec2ecfa16ea6be",
    **DEP_PINS,
}

FETCH: dict[str, str] = {
    REL_SDK_WHEEL: (f"{_PYPI}/47/10/efd7ad88cd6140be4883d055abf9acd7fa8e5424a20de8a224d310e67f2f/"
                    f"deepseek_harness_sdk-{SDK_VERSION}-py3-none-any.whl"),
    REL_RT_WHEEL: (f"{_PYPI}/72/19/548c84e9d02683612b6a3a23571d68480c657ef5f4aa1e3c656898ee1824/"
                   f"deepseek_harness_runtime_bin-{SDK_VERSION}-py3-none-macosx_14_0_arm64.whl"),
    REL_CONFIG: f"{_RAW}/examples/jsonrpc-agent/minimal.cordis.yml",
    REL_LICENSE: f"{_RAW}/LICENSE",
    **DEP_FETCH,
}

# 其它平台的 runtime wheel(本机不装,记进清单供跨机复现)
RUNTIME_OTHER_PLATFORMS = {
    "manylinux_2_28_x86_64": "d7261d3bdadfa8d10ab03fd06c6bbc66a182ae27d39892a0eb7c2ce9d63a5448",
    "manylinux_2_28_aarch64": "99d0ef334a4e3cb178d7b0302bbdd01c8dde6068ee5fe8b01e074541db5c7747",
}

# 安装后的自检:两个发行版的版本都得是钉的那个,SDK 入口可导入。
_CHECK_INSTALL_SRC = (
    "from importlib.metadata import version;"
    f"assert version('deepseek-harness-sdk') == '{SDK_VERSION}', version('deepseek-harness-sdk');"
    f"assert version('deepseek-harness-runtime-bin') == '{SDK_VERSION}',"
    " version('deepseek-harness-runtime-bin');"
    "import deepseek_harness;"
    "assert hasattr(deepseek_harness, 'DeepSeekHarness'), dir(deepseek_harness);"
    "print('sdk import ok', version('deepseek-harness-sdk'))"
)


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def check_pins(root: Path, pins: dict[str, str] | None = None) -> tuple[bool, list[str]]:
    """逐条核对钉死物。失败方向朝紧:缺文件、hash 不符都算破。"""
    pins = PINS if pins is None else pins
    problems: list[str] = []
    for rel, want in sorted(pins.items()):
        p = Path(root) / rel
        if not p.is_file():
            problems.append(f"缺失:{rel}")
            continue
        got = _sha256(p)
        if got != want:
            problems.append(f"hash 不符:{rel} 期望 {want[:12]}… 实得 {got[:12]}…")
    return (not problems), problems


def repo_copy_pins() -> dict[str, str]:
    """仓内参考副本与封存件钉同一枚 hash。"""
    return {REPO_CONFIG_COPY: PINS[REL_CONFIG], REPO_LICENSE_COPY: PINS[REL_LICENSE]}


def build_steps(root: Path) -> list[list[str]]:
    steps: list[list[str]] = []
    for rel, url in FETCH.items():
        steps.append(["curl", "-fsSL", "--retry", "2", "--max-time", "600",
                      "--create-dirs", "-o", str(root / rel), url])
    steps.append([sys.executable, str(Path(__file__).resolve()),
                  "--check-pins-only", str(root)])
    steps.append([sys.executable, "-m", "venv", str(root / ".venv")])
    steps.append([str(root / ".venv/bin/pip"), "install", "--no-index",
                  "--find-links", str(root / "wheels"),
                  f"deepseek-harness-sdk=={SDK_VERSION}"])
    steps.append([str(root / ".venv/bin/python"), "-c", _CHECK_INSTALL_SRC])
    return steps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--check-pins-only", metavar="ROOT")
    a = ap.parse_args()

    if a.check_pins_only:
        ok, problems = check_pins(Path(a.check_pins_only))
        for x in problems:
            print(f"  ✗ {x}")
        if ok:
            print(f"  钉死物 {len(PINS)} 条全部对上")
        return 0 if ok else 1

    if a.verify:
        ok1, msg = verify_sealed(RUNTIME_ROOT)
        print(("✓ " if ok1 else "✗ ") + msg)
        ok2, problems = check_pins(RUNTIME_ROOT)
        print("✓ 封存钉死物全部对上" if ok2 else "✗ 封存钉死物有破:")
        for x in problems:
            print(f"    {x}")
        ok3, problems3 = check_pins(REPO, repo_copy_pins())
        print("✓ 仓内参考副本未漂移" if ok3 else "✗ 仓内参考副本漂移:")
        for x in problems3:
            print(f"    {x}")
        return 0 if (ok1 and ok2 and ok3) else 1

    if a.go and sys.version_info[:2] != (3, 12):
        print(f"✗ 封存 venv 钉在 Python 3.12(pydantic_core cp312 wheel);"
              f"当前解释器 {sys.version_info[0]}.{sys.version_info[1]} —— 拒跑")
        return 1

    steps = build_steps(RUNTIME_ROOT)
    if not a.go:
        print(f"[干跑] profile={PROFILE_ID}")
        print(f"[干跑] root={RUNTIME_ROOT}")
        print(f"[干跑] source_commit={SOURCE_COMMIT}")
        for s in steps:
            print("  $", " ".join(x if len(x) < 100 else x[:97] + "…" for x in s))
        print("真跑加 --go(唯一联网点);跑完自动封存并复核")
        return 0

    pinned = [
        PinnedSource(distribution="deepseek-harness-sdk", version=SDK_VERSION,
                     url=FETCH[REL_SDK_WHEEL]),
        PinnedSource(distribution="deepseek-harness-runtime-bin", version=SDK_VERSION,
                     url=FETCH[REL_RT_WHEEL]),
        PinnedSource(distribution="deepseek-harness/examples/jsonrpc-agent/minimal.cordis.yml",
                     version=f"{SDK_VERSION}-upstream", resolved_commit=SOURCE_COMMIT,
                     url=FETCH[REL_CONFIG]),
    ]
    m = provision(profile_id=PROFILE_ID, root=RUNTIME_ROOT, pinned=pinned,
                  steps=steps, allow_network=True)
    # 框架的 extras 只带步骤日志;补上供跨机复现与审计的钉死表后重写清单
    # (清单本身不入自身摘要,重写不破 digest)。
    m.extras.update({
        "pins": PINS,
        "runtime_other_platforms": RUNTIME_OTHER_PLATFORMS,
        "source_commit": SOURCE_COMMIT,
        "upstream_repo": UPSTREAM_REPO,
        "pypi_verified_at": "2026-08-17",
        "tag_mapping": "PyPI 版本 ↔ 官方 tag 映射未公示,钉 commit 不钉 tag(指导文档 §6.4)",
    })
    (RUNTIME_ROOT / "runtime_manifest.json").write_text(m.to_json(), encoding="utf-8")
    print(f"✓ 封存完成:{RUNTIME_ROOT}")
    ok, msg = verify_sealed(RUNTIME_ROOT)
    print(("✓ " if ok else "✗ ") + msg)
    okp, problems = check_pins(RUNTIME_ROOT)
    print("✓ 钉死物复核全过" if okp else "✗ 钉死物复核有破:")
    for x in problems:
        print(f"    {x}")
    return 0 if (ok and okp) else 1


if __name__ == "__main__":
    sys.exit(main())
