"""宿主 Git 只读查询(RFC-008)— 与静态分析器分离的唯一原因:

host_analyzer 被钉死为「零 subprocess」;而 RFC-008 §4.1 要求分析
输出宿主的 git commit 与工作区干净度(Drift 检测基线)。git 是我们
自己的只读工具调用,不是「执行项目代码」,但为了让原钉死约束继续
成立,所有 subprocess 集中在本模块。本模块自身的钉死约束:只读
git 查询(rev-parse / status --porcelain),禁写、禁网络、禁 LLM、禁容器。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from repoproof.adoption.analysis.host_analyzer import Finding


def git_facts(root: Path) -> tuple[Finding, Finding]:
    """(git_commit, workspace_dirty) — 只读查询,10s 超时,失败如实 UNKNOWN。"""
    try:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10, check=False)
        if head.returncode != 0:
            return (Finding.unknown(f"git rev-parse 失败:{head.stderr.strip()[:120]}"),
                    Finding.unknown("git 状态不可用"))
        status = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                                capture_output=True, text=True, timeout=10, check=False)
        if status.returncode != 0:
            return (Finding.fact(head.stdout.strip(), "git rev-parse HEAD"),
                    Finding.unknown("git status 失败"))
        return (Finding.fact(head.stdout.strip(), "git rev-parse HEAD"),
                Finding.fact(bool(status.stdout.strip()), "git status --porcelain"))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (Finding.unknown(f"git 不可用:{exc}"), Finding.unknown("git 不可用"))
