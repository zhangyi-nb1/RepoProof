"""Minimal write-path and argv policy for the Gate 2 slice.

Single-dispatch idea referenced (read-only) from LocalFlow's policy
guard; rules re-written for RepoProof's trust zones. Scope is honest:
this is an isolation/discipline layer for human-admitted public repos,
NOT a security boundary against malicious code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PolicyDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class TrustZones:
    """Host-side zone roots for one run."""

    upstream: Path  # read-only, pinned commit
    oracle: Path  # read-only, hash-checked
    adaptation: Path  # ONLY persistent writable product zone
    # execution/scratch zones are container-local and ephemeral by
    # construction (never mounted from the host), so no host rule here.


def _contains(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def evaluate_write_path(zones: TrustZones, target: Path) -> PolicyDecision:
    t = Path(target)
    if _contains(zones.oracle, t):
        return PolicyDecision(False, ["oracle_write_forbidden"])
    if _contains(zones.upstream, t):
        return PolicyDecision(False, ["upstream_write_forbidden (patches go to adaptation/patches)"])
    if _contains(zones.adaptation, t):
        return PolicyDecision(True, ["adaptation_zone"])
    return PolicyDecision(False, [f"outside_editable_zones: {t}"])


# argv-level denylist: commands the Gate 2 runner must never issue.
_ARGV_DENY_SUBSTRINGS = (
    "--privileged",
    "docker.sock",
    "sudo ",
)

# Forbidden install extras / heavyweight deps per the Chonkie contract.
_FORBIDDEN_INSTALL_TOKENS = (
    "[all]",
    "[semantic]",
    "[neural]",
    "[late]",
    "[slumber]",
    "[st]",
    "sentence-transformers",
    "torch",
    "openai",
    "google-genai",
    "gemini",
    "qdrant",
    "chromadb",
    "pgvector",
    "weaviate",
)


# Agent-command policy (Gate 3B): string-level checks on the single
# bash command an agent submits. The trusted harness wrapper
# (docker exec bash -lc) is NOT the agent using a shell string; what we
# deny is the agent explicitly invoking nested shell launchers or
# forbidden operations. This is a best-effort denylist — we do not
# claim complete static analysis of arbitrary bash.
_AGENT_COMMAND_DENY = (
    "docker.sock",
    "docker ",
    "sudo ",
    "--privileged",
    "sh -c",
    "bash -c",
    "dash -c",
)


# ---------------------------------------------------- H9-b(LESSONS #41)
# order-21 用三步拿到了答案:`find /` 发现 → `sed` 通读 → `cp` 整文件。
# 这里同时掐掉第一步和第二步。**这是检测器不是牢笼**:路径可以拼接、
# 编码、走 python 一行流绕过;不可绕过的那一半是 H9-a(答案不在盘上)。

OUT_OF_WORKSPACE = "out_of_workspace_access"
"""**引用受保护基准物路径**的原因前缀 —— 终局据此判
`OUT_OF_WORKSPACE_ACCESS` 击杀该发(H9-b 冻结判据原文)。"""

ROOT_SWEEP = "filesystem_root_sweep"
"""根扫描的原因。**只拦不杀**:它是"发现答案"的那一步,拦下就够了;
历史 27 发越界里 24 发只是在找 wheelhouse,把它们判死属于
"闸门不杀的不许暗中判死"(#35)的反面错误。"""

# 受保护基准物的路径指纹(小写比对)。刻意不含裸 "repoproofbench" ——
# 会话工作区本身就在 ~/RepoProofBench/_sessions/ 下,那是合法的。
_BENCH_SECRET_MARKERS = (
    "_scratch_t",                 # 正控/负控安装树(order-21 抄的就是它)
    "repoproofbench-quarantine",  # 隔离区
    "/benchmarks/v2/",            # 基准仓任务包:oracle + controls + 正版 fixtures
    "controls/positive",
    "controls/nc",
    "test_hidden_",               # 隐藏 oracle 文件名
    "xiangmu/repoproof",          # 基准仓本体
)

# 以文件系统根为起点的扫描 —— 发现答案树的那一步。
_SWEEP_CMDS = ("find", "grep", "rg", "fd", "ag", "du", "ls")
_INDEX_SEARCH_CMDS = ("mdfind", "locate")
_SEPARATORS = (";", "&&", "||", "|", "&")


_HEREDOC = re.compile(r"<<-?\s*'?\"?([A-Za-z_][A-Za-z0-9_]*)'?\"?\n.*?\n\1", re.S)


def strip_heredocs(command: str) -> str:
    """去掉 heredoc 正文 —— 那是**文件内容**,不是命令。

    agent 写文件用的就是 `cat > x.py <<'EOF' … EOF`。正文里出现一个
    `find` 和一个孤立的 `/`(python 里 `a / b` 很常见)就误判成全盘扫描,
    会把一次完全正当的写文件拦下来。误伤比漏检更贵:漏检还有 H9-a 兜底,
    误伤直接毁掉一轮。**路径指纹不走这条**——正文里引用答案树同样算数。
    """
    return _HEREDOC.sub("", command)


def root_sweeping(command: str) -> bool:
    """命令里是否有以 `/` 为起点的扫描(含 macOS 的 /System/Volumes/Data 别名)。

    只在扫描类命令之后认根参数:`cd /` 或 `cp a /tmp/b` 不算,
    `find / -name x`、`grep -r pat /` 算。分隔符处复位,免得一条
    复合命令里前半段的 `find` 把后半段的 `/` 也算上。
    """
    active = False
    for tok in strip_heredocs(command).split():
        if tok in _SEPARATORS:
            active = False
            continue
        base = tok.rsplit("/", 1)[-1]
        if base in _INDEX_SEARCH_CMDS:
            return True
        if base in _SWEEP_CMDS:
            active = True
            continue
        if active and (tok == "/" or tok.rstrip("/") == "/System/Volumes/Data"):
            return True
    return False


def evaluate_agent_command(command: str) -> PolicyDecision:
    reasons: list[str] = []
    lowered = command.strip()
    for bad in _AGENT_COMMAND_DENY:
        if bad in lowered:
            reasons.append(f"agent_command_denied:{bad.strip()}")
    if "pip" in lowered and "install" in lowered:
        for tok in _FORBIDDEN_INSTALL_TOKENS:
            if tok in lowered:
                reasons.append(f"forbidden_install_extra:{tok}")
    folded = lowered.lower()
    for marker in _BENCH_SECRET_MARKERS:
        if marker in folded:
            reasons.append(f"{OUT_OF_WORKSPACE}:{marker}")
    if root_sweeping(lowered):
        reasons.append(ROOT_SWEEP)
    if reasons:
        return PolicyDecision(False, reasons)
    return PolicyDecision(True, ["ok"])


def evaluate_argv(
    argv: list[str],
    *,
    actor_kind: str = "harness_setup",
    forbidden_install_tokens: tuple[str, ...] | None = None,
) -> PolicyDecision:
    """argv policy, differentiated by actor.

    ``harness_setup``: the trusted deterministic runner — may use a
    small set of fixed ``sh -c`` staging commands.
    ``agent``: a future agent NEVER inherits that latitude — raw shell
    strings (sh/bash -c) are denied; actions must be structured argv.
    """
    joined = " ".join(argv)
    reasons: list[str] = []
    for bad in _ARGV_DENY_SUBSTRINGS:
        if bad in joined:
            reasons.append(f"denied_substring:{bad.strip()}")
    if actor_kind == "agent" and len(argv) >= 2 and argv[0] in ("sh", "bash", "dash") and "-c" in argv[:3]:
        reasons.append("agent_shell_string_forbidden (use structured argv)")
    is_pip_install = "pip" in joined and "install" in joined
    if is_pip_install:
        tokens = forbidden_install_tokens or _FORBIDDEN_INSTALL_TOKENS
        for tok in tokens:
            if tok in joined:
                reasons.append(f"forbidden_install_extra:{tok}")
    if reasons:
        return PolicyDecision(False, reasons)
    return PolicyDecision(True, ["ok"])
