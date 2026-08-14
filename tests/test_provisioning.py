"""一次性联网 provisioning 的边界钉死(用户 2026-08-15 授权)。

授权原文的要害是**定义**,不是许可:允许 harness 侧联网一次,但那必须是
"runtime provisioning / build 阶段",**不是**给 agent 或 benchmark execution
放开网络。所以这里钉的全是"两个阶段没有混"。

- N1 **联网必须显式**。`provision()` 的 `allow_network` 是必填,不给就拒跑
  —— 让"这一步会联网"在调用点上肉眼可见,而不是藏在默认值里。
- N2 **execute 侧根本没有联网这个参数**。`verify_sealed()` 的签名里没有
  `allow_network` —— 想在发次期联网,得先改 API 形状。反例:加一个默认
  False 的开关 → 迟早有人传 True,而那时它看起来完全合法。
- N3 **不钉版不给封存**。反例:装个 latest 就封存 → 那份 runtime 不可复现,
  封存它没有意义。
- N4 **封存件被动过就拒开**。反例:只看清单在不在 → 装完之后有人手动动过、
  或别的脚本顺手改过,那就不再是被验过的那份。
- N5 **摘要按内容算,不按 mtime/size**。反例:用 mtime → 复制/解压/touch
  都会误报,而误报会训练人去忽略这道检查,比没有检查更坏。
- N6 **runtime 根受保护**,且**不在 bench 根白名单里**。反例:塞进
  `~/RepoProofBench/` 的白名单 → 正是 LESSONS #29 判过的"给兄弟目录开口子"。
- N7 **agent 的会话环境一个字不改**:仍是 PIP_NO_INDEX + 冻结 wheelhouse。
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from repoproof.execution.provisioning import (
    PROVISION_MARKER,
    PinnedSource,
    ProvisioningError,
    RuntimeManifest,
    digest_tree,
    provision,
    verify_sealed,
)
from repoproof.harness.host_guard import _BENCH_ALLOWED_NAMES, is_protected

REPO = Path(__file__).resolve().parents[1]


def _ok_steps(tmp_path):
    return [["/bin/sh", "-c", "echo hi > f.txt"]]


def test_n1_network_must_be_explicit(tmp_path):
    """N1:不显式写 allow_network=True 就拒跑。"""
    with pytest.raises(ProvisioningError, match="allow_network"):
        provision(profile_id="x", root=tmp_path, pinned=[PinnedSource("a", "1")],
                  steps=[], allow_network=False)


def test_n2_execute_side_has_no_network_knob():
    """N2:execute 侧的签名里根本没有联网参数。

    反例:加一个默认 False 的开关 —— 迟早有人传 True,而那时它看起来完全
    合法。没有这个参数,想联网就得先改 API 形状,改不动就是改不动。"""
    assert "allow_network" not in inspect.signature(verify_sealed).parameters
    assert "allow_network" in inspect.signature(provision).parameters

    src = (REPO / "src" / "repoproof" / "execution"
           / "provisioning.py").read_text(encoding="utf-8")
    # 解除离线钉的那两行只应出现在 provision 里
    assert src.count('e.pop(k, None)') == 1


def test_n3_unpinned_upstream_is_refused(tmp_path):
    """N3:不钉版本不给封存 —— 不可复现的 runtime 封存了也没意义。"""
    with pytest.raises(ProvisioningError, match="没有钉死|没有钉版本|不猜"):
        provision(profile_id="x", root=tmp_path, pinned=[], steps=[],
                  allow_network=True)
    with pytest.raises(ProvisioningError, match="没有钉版本"):
        provision(profile_id="x", root=tmp_path, pinned=[PinnedSource("a", "")],
                  steps=[], allow_network=True)


def test_n4_tampered_seal_is_refused(tmp_path):
    """N4:封存件被动过就拒开。"""
    provision(profile_id="x", root=tmp_path, pinned=[PinnedSource("a", "1", "c")],
              steps=_ok_steps(tmp_path), allow_network=True)
    ok, why = verify_sealed(tmp_path)
    assert ok, why

    (tmp_path / "f.txt").write_text("tampered\n", encoding="utf-8")
    ok, why = verify_sealed(tmp_path)
    assert not ok and "被动过" in why


def test_n4b_missing_manifest_is_refused(tmp_path):
    """N4 的另一半:没清单一律拒开,不假设"大概装好了"。"""
    ok, why = verify_sealed(tmp_path)
    assert not ok and "没有 runtime 清单" in why


def test_n5_digest_is_content_not_metadata(tmp_path):
    """N5:摘要按内容算 —— 改 mtime 不该让它变,改内容必须让它变。"""
    import os
    import time

    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    before = digest_tree(tmp_path)
    os.utime(tmp_path / "a.txt", (time.time() + 10_000, time.time() + 10_000))
    assert digest_tree(tmp_path) == before, "改 mtime 竟然让摘要变了 —— 会误报"

    (tmp_path / "a.txt").write_text("y", encoding="utf-8")
    assert digest_tree(tmp_path) != before, "改内容却没让摘要变 —— 漏报"


def test_n5b_manifest_excludes_itself_from_its_own_digest(tmp_path):
    """N5:清单不算进自己的摘要,否则写清单这一步就把摘要弄失效了。"""
    m = provision(profile_id="x", root=tmp_path, pinned=[PinnedSource("a", "1")],
                  steps=_ok_steps(tmp_path), allow_network=True)
    assert (tmp_path / PROVISION_MARKER).is_file()
    assert digest_tree(tmp_path) == m.artifact_digest


def test_n6_runtime_root_is_protected_and_not_in_bench_whitelist():
    """N6:runtime 根受保护,且**不在** bench 根白名单里。

    反例:塞进 `~/RepoProofBench/` 的白名单 —— 正是 LESSONS #29 判过的
    "给兄弟目录开口子"(M29b/M29c 两条变异守的就是它)。"""
    assert is_protected("~/RepoProofRuntimes/rt-sidecar-browser-v1/.venv")
    assert not any("runtime" in n.lower() for n in _BENCH_ALLOWED_NAMES), (
        "runtime 混进 bench 根白名单了 —— 那是 #29 判过的错法")


def test_n7_agent_session_env_still_offline():
    """N7:agent 的会话环境一个字不改 —— 仍是 PIP_NO_INDEX + 冻结 wheelhouse。"""
    src = (REPO / "src" / "repoproof" / "runner"
           / "host_guided.py").read_text(encoding="utf-8")
    assert '"PIP_NO_INDEX": "1"' in src
    assert '"PIP_FIND_LINKS": str(self.wheelhouse)' in src
    assert "allow_network" not in src, (
        "会话环境里出现了联网开关 —— provisioning 的口子漏到 execute 侧了")


def test_sealed_browser_runtime_if_provisioned():
    """接线:若已构建 rt-sidecar-browser-v1,封存件必须完好且钉版对得上。"""
    root = Path("~/RepoProofRuntimes/rt-sidecar-browser-v1").expanduser()
    if not (root / PROVISION_MARKER).is_file():
        pytest.skip("尚未 provision —— 跑 scripts/provision_browser_runtime.py --go")
    ok, why = verify_sealed(root)
    assert ok, why
    m = RuntimeManifest.load(root)
    assert m.profile_id == "rt-sidecar-browser-v1"
    s = next(x for x in m.pinned if x.distribution == "browser-use")
    assert s.version == "0.13.7"
    assert s.resolved_commit == "32601887cfbc9f4f1e3cad3e2b678e56aeaeaae4", (
        "钉版 commit 与 T3 契约不同源了 —— 两处各写一份必然漂移")
    lock = root / "requirements.lock"
    assert lock.is_file() and lock.stat().st_size > 0, "依赖闭包没被冻结"


def test_sealed_chromium_is_full_build_and_actually_runs():
    """封存的浏览器:**完整构建**、是主程序不是辅助进程、且真跑得起来。

    用户 2026-08-15 指令:第一次就下完整 Chromium,不要为省体积用
    `--only-shell` —— headless shell 是独立的精简构建,拿它当浏览器等于自带
    一个"能力缺失"的混杂变量,将来某条负控红了会分不清是判据抓住了它还是
    浏览器少了个能力。

    三条都是踩过的:
      - playwright 会同时装下 `chromium-<build>` 与
        `chromium_headless_shell-<build>`,选错就成了 shell;
      - 递归 glob 会掉进 `…/Helpers/… Helper (Alerts).app/…`,那是辅助进程
        (实测第一次就选中了它)——"能找到可执行文件"不等于找到了要的那个;
      - 文件在、可执行位在、路径也对,仍可能起不来。跑一次 `--version` 才算数。
    """
    import subprocess

    root = Path("~/RepoProofRuntimes/rt-sidecar-browser-v1").expanduser()
    if not (root / PROVISION_MARKER).is_file():
        pytest.skip("尚未 provision")
    m = RuntimeManifest.load(root)

    assert m.extras.get("chromium_full_build") is True, "封存的是 headless shell?"
    rel = m.extras.get("chromium_executable") or ""
    assert rel, "清单里没记 Chromium 可执行文件"
    assert "headless_shell" not in rel, f"选中了 headless shell:{rel}"
    assert "Helper" not in rel, f"选中了辅助进程:{rel}"

    exe = root / rel
    assert exe.is_file(), f"清单指向的浏览器不在:{exe}"
    out = subprocess.run([str(exe), "--version"], capture_output=True,   # noqa: S603
                         text=True, check=False, timeout=60)
    ver = (out.stdout or out.stderr).strip()
    assert "Chrome" in ver or "Chromium" in ver, f"跑不出版本:{ver!r}"
    assert m.extras.get("chromium_version_string", "") in ver or ver, ver

    pin = next((s for s in m.pinned if s.distribution == "chromium"), None)
    assert pin is not None and pin.version, "Chromium 没被钉进清单"
    assert pin.resolved_commit.startswith("playwright-"), (
        "没记下它是哪个 playwright 版本钉的 —— 那样'同一份浏览器'无从复现")


def test_chromium_lives_inside_the_sealed_root():
    """浏览器必须在 runtime 根**之内** —— 否则它不进封存摘要、也不受保护。

    反例:落在 `~/Library/Caches/ms-playwright`(playwright 的默认位置)——
    那是共用缓存,别的项目一句 `playwright install` 就可能把它换掉,而我们
    封存这份浏览器的全部理由就是让它不再变。"""
    root = Path("~/RepoProofRuntimes/rt-sidecar-browser-v1").expanduser()
    if not (root / PROVISION_MARKER).is_file():
        pytest.skip("尚未 provision")
    m = RuntimeManifest.load(root)
    exe = (root / m.extras["chromium_executable"]).resolve()
    assert exe.is_relative_to(root.resolve()), f"浏览器跑到封存件之外了:{exe}"
    assert is_protected(exe), "浏览器不在保护目录内"


def test_manifest_round_trips(tmp_path):
    """清单读写往返不丢字段(它是 execute 期唯一认的东西)。"""
    m = provision(profile_id="p", root=tmp_path,
                  pinned=[PinnedSource("d", "1.2", "abc", "http://x")],
                  steps=_ok_steps(tmp_path), allow_network=True)
    back = RuntimeManifest.load(tmp_path)
    assert back.profile_id == m.profile_id
    assert back.pinned[0].resolved_commit == "abc"
    assert json.loads(m.to_json())["pinned"][0]["url"] == "http://x"
