"""DSH 隔离与安全负控(DSH 阶段 5,指导文档十项;ADR §4 信任边界)。

**范围的诚实声明**:首轮无容器,cwd 不是沙箱(ADR §4 原话)。本电池证明的
是**声明过的边界**:①我们递给不可信平面的一切落点离开裁决面与封存池
(拓扑闸);②环境过闸只剩 allowlist + 显式注入(最小泄漏面);③组合面
没有 docker/web/subagent/skills;④钉死物被动一字节即点名(供应链钉);
⑤伪造通道(DSH 会话 JSONL / final_response)在裁决面**无消费方**——
拓扑不可见,不是文本规则说"请勿采信"。OS 级容器化按 ADR 列为后续增强。

十项对位:N1 读 Oracle / N2 读验证器源码 / N3 写台账 → 拓扑闸 + 环境无
路径提示(oracle·验证器·台账全在仓树,workspace 禁入仓树);N4 他发
worktree → 逐发新目录 + fresh session(W4 已钉,此处钉 stateless);
N5 父进程 secrets → allowlist 过闸;N6 docker → 组合面文本;N7 改 cordis /
N8 改 wheel → 供应链钉现场复核;N9 伪造 JSONL / N10 伪造 final_response
→ 裁决面零消费(结构钉)。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from repoproof.agents.dsh_backend import (
    _ENV_ALLOWLIST,
    _forbidden_roots,
    run_dsh_worker,
    worker_env,
)

REPO = Path(__file__).resolve().parents[1]
RT_ROOT = Path.home() / "RepoProofRuntimes" / "rt-dsh-minimal-0.1.0rc6-v1"


def _job(tmp: Path) -> dict:
    (tmp / "ws").mkdir(exist_ok=True)
    return {"prompt": "x", "workspace": str(tmp / "ws"),
            "events_path": str(tmp / "ev" / "events.jsonl"),
            "session_root": str(tmp / "sess"), "cordis": str(tmp / "ws")}


# ---------------------------------------------------------- N1/N2/N3 拓扑闸

def test_n123_trusted_plane_roots_rejected(tmp_path: Path) -> None:
    """workspace/events/session 任一指进仓树或封存池 → 开跑前拒绝。
    Oracle 判据、验证器源码、run ledger 全在仓树里 —— 拒入仓树 = 三项同闸。"""
    roots = _forbidden_roots()
    assert REPO in roots, "仓树必须是受保护根"
    assert (Path.home() / "RepoProofArchive") in roots, "封存池必须是受保护根"
    for key in ("workspace", "events_path", "session_root"):
        for bad in (REPO / "benchmarks" / "v2", REPO,
                    Path.home() / "RepoProofArchive" / "d5-hunt"):
            job = _job(tmp_path)
            job[key] = str(bad)
            with pytest.raises(ValueError, match="受保护根"):
                run_dsh_worker(job, worker_python=sys.executable,
                               worker_argv=[sys.executable, "-c", "pass"])


# ---------------------------------------------------------------- N5 环境闸

def test_n5_env_gate_strips_parent_secrets(monkeypatch, tmp_path: Path) -> None:
    """父进程环境里的任何非 allowlist 变量(别家 key、token、仓路径)不过闸;
    显式注入的照传 —— 最小泄漏面,不是零泄漏的空话。"""
    monkeypatch.setenv("RP_PHANTOM_SECRET", "leak-me-if-you-can")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-ride-along")
    env = worker_env({"DEEPSEEK_API_KEY": "sk-explicit"})
    assert "RP_PHANTOM_SECRET" not in env
    assert "OPENAI_API_KEY" not in env
    assert env["DEEPSEEK_API_KEY"] == "sk-explicit"
    assert set(env) <= set(_ENV_ALLOWLIST) | {"DEEPSEEK_API_KEY"}
    # 活体探针:child 真看到的环境 == 过闸后的,而不是父进程全量
    probe = tmp_path / "probe.py"
    probe.write_text("import json,os\nprint(json.dumps(sorted(os.environ)))\n",
                     encoding="utf-8")
    out = subprocess.run([sys.executable, str(probe)], capture_output=True,
                         text=True, env=worker_env()).stdout
    keys = set(json.loads(out))
    assert "RP_PHANTOM_SECRET" not in keys and "OPENAI_API_KEY" not in keys
    # macOS 给一切子进程注入这两枚(libSystem/locale),不是父环境过闸 ——
    # 白名单外只许这俩,且都不携带信息量
    assert keys - set(_ENV_ALLOWLIST) <= {"__CF_USER_TEXT_ENCODING", "LC_CTYPE"}, keys


# ------------------------------------------------------------ N4 无跨发状态

def test_n4_backend_is_stateless_across_runs() -> None:
    """逐发隔离的模块面:dsh_backend 不得有模块级可变运行状态 ——
    上一发的计数/句柄漏进下一发,'不同发不串'就只剩运气。"""
    import repoproof.agents.dsh_backend as m
    mutable = [k for k, v in vars(m).items()
               if not k.startswith("__") and isinstance(v, (dict, list, set))]
    assert mutable == [], f"模块级可变状态:{mutable}"


# ------------------------------------------------------------ N6 组合面文本

def test_n6_composition_has_no_escape_hatches() -> None:
    """钉死的 minimal 组合无逃生舱:docker/web/subagent 全文不现;skills
    显式关死(enabled: false,不是"没写");compaction 只出现在声明其缺席
    的那句里。首轮禁面(ADR §8);改组合 = 换 hash = 供应链钉先红。"""
    text = (REPO / "configs" / "dsh" /
            "minimal.upstream.0.1.0rc6.cordis.yml").read_text(encoding="utf-8")
    low = text.lower()
    for banned in ("docker", "web", "subagent"):
        assert banned not in low, f"组合面出现禁词:{banned}"
    assert "skills:\n      enabled: false" in text, "skills 必须显式关死"
    assert low.count("skill") == 1, "skills 除关死声明外不得再现"
    assert "context compaction are absent" in text
    assert low.count("compaction") == 1, "compaction 除缺席声明外不得再现"


# ------------------------------------------------------- N7/N8 供应链现场核

@pytest.mark.skipif(not RT_ROOT.exists(), reason="封存 runtime 不在本机")
def test_n78_sealed_artifacts_verify_now() -> None:
    """cordis 与 wheel 的防篡改不是"曾经验过":现在、此刻,封存件必须
    逐枚对上钉的 hash(机制的失败方向由 test_dsh_provisioning_pins 钉死,
    这里核的是现场事实)。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "pdr", REPO / "scripts" / "provision_dsh_runtime.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)  # type: ignore[union-attr]
    ok, problems = m.check_pins(RT_ROOT, m.PINS)
    assert ok, problems


# ------------------------------------------------- N9/N10 伪造通道零消费

_ADJUDICATION_TREES = ("verification", "harness", "adoption", "persistence",
                       "runner", "probes", "receipts")


def _grep_tree(needle: str) -> list[str]:
    hits = []
    for sub in _ADJUDICATION_TREES:
        root = REPO / "src" / "repoproof" / sub
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.py")):
            if needle in p.read_text(encoding="utf-8"):
                hits.append(str(p.relative_to(REPO)))
    return hits


def test_n9_dsh_session_jsonl_has_no_consumer() -> None:
    """DSH 自己的会话 JSONL(DSH_SESSION_ROOT 下)在裁决面零消费 ——
    伪造它没有下游。可信 trace 只有宿主侧 events.jsonl(dsh_worker 亲写)。"""
    assert _grep_tree("DSH_SESSION_ROOT") == []
    assert _grep_tree("session-persistence") == []


def test_n10_final_response_has_no_adjudication_consumer() -> None:
    """final_response 在裁决树零消费,台账允许字段也不收它 ——
    "ALL TESTS PASS"写得再好看,没有任何 Verdict 读它。"""
    assert _grep_tree("final_response") == []
    from repoproof.persistence.bench_records import REQUIRED_FIELDS
    assert "final_response" not in REQUIRED_FIELDS
    src = (REPO / "src" / "repoproof" / "agents" / "dsh_worker.py").read_text(
        encoding="utf-8")
    assert "仅诊断" in src, "worker 源码必须标注 final_response 仅诊断"
