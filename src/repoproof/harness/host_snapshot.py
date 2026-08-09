"""宿主快照:排除 + 合成替身 + PII 出口扫描(TESTPLAN §4-5,Phase 0 ③)。

实测背景(2026-08-09 副本审计):OfferClaw 的 user_profile.md /
applications.md / daily_log.md 等 PII 文件**均为 untracked**,git
克隆天然不携带——风险登记册 L1 因此降级。真正的 PII 通道是 B 类
资源引导:把 `chroma_db/`(3538 条真实简历/JD 向量)等运行态数据
复制进副本时会一并带入。故本模块的职责是:

1. **排除**:运行态/密钥/缓存/PII 目录不进快照(默认清单 + 任务追加);
2. **合成替身**:宿主运行确实需要的 PII 文件,用合成内容顶替(真实
   内容永不进 agent 工作区);
3. **出口扫描**:快照建成后扫描明显 PII 形态(手机号/邮箱/身份证),
   命中即报警——防"排除清单漏了一项"静默泄漏(纵深防御,同
   bundle 的 oracle 内容兜底扫描思路)。
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

# 默认排除:密钥 / 运行态 / 缓存 / 已知 PII 载体
DEFAULT_EXCLUDES = (
    ".env", ".env.local", ".env.*",
    "*.lock", "*.log",
    ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    "chroma_db",            # 真实向量库(含简历/JD 内容)——须经引导显式处理
    "logs", "summaries", "_local_notes", "_gpt_exports",
    "user_profile.md", "applications.md", "applications_store.json",
    "daily_log.md", "gap_store.json",
)

# 扫描跳过目录(第三方源码里的作者邮箱会淹没真实信号)
_SCAN_SKIP_DIRS = frozenset({".venv", "venv", "node_modules", "__pycache__",
                             ".git", ".pytest_cache", ".ruff_cache", ".mypy_cache"})

# 合成替身:宿主代码/测试可能读取,但真实内容不得外泄
DEFAULT_SUBSTITUTES: dict[str, str] = {
    "user_profile.md": (
        "# 合成测试档案(RepoProof 生成,非真实个人信息)\n\n"
        "- 姓名:测试用户\n- 邮箱:test@example.invalid\n"
        "- 目标岗位:Test Engineer\n- 技能:Python, Testing\n"
    ),
    "applications.md": "# 合成投递记录(RepoProof 生成)\n\n(空)\n",
    "daily_log.md": "# 合成日志(RepoProof 生成)\n",
}

_PII_PATTERNS = (
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("邮箱", re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.(?:com|invalid))[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("身份证", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
)

_SCAN_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".py", ".csv", ".jsonl"}
_MAX_SCAN_BYTES = 2_000_000


class SnapshotError(RuntimeError):
    pass


def _excluded(rel: Path, patterns: tuple[str, ...]) -> bool:
    """路径是否被排除。

    `.git/` 内部**整体豁免**排除模式:真实副本实测发现 `logs` 模式
    会误伤 `.git/logs`(reflog),部分排除会破坏 git 仓库完整性——
    git 目录要么整体保留、要么由调用方整体排除,不允许挖洞。"""
    parts = rel.parts
    if parts and parts[0] == ".git":
        return ".git" in patterns
    for pat in patterns:
        if any(Path(part).match(pat) for part in parts):
            return True
        if rel.match(pat):
            return True
    return False


def prepare_host_snapshot(
    src: str | Path,
    dst: str | Path,
    *,
    excludes: tuple[str, ...] = DEFAULT_EXCLUDES,
    substitutes: dict[str, str] | None = None,
    extra_excludes: tuple[str, ...] = (),
) -> dict:
    """把宿主副本内容整理成可交给 agent 的快照。

    → {files, excluded, substituted}。src 只读;dst 必须为空/不存在。"""
    srcp = Path(src).expanduser().resolve()
    dstp = Path(dst).expanduser().resolve()
    if not srcp.is_dir():
        raise SnapshotError(f"宿主副本不存在:{srcp}")
    if dstp.exists() and any(dstp.iterdir()):
        raise SnapshotError(f"快照目标目录非空:{dstp}")
    pats = tuple(excludes) + tuple(extra_excludes)
    subs = DEFAULT_SUBSTITUTES if substitutes is None else substitutes

    n, excluded = 0, []
    for p in sorted(srcp.rglob("*")):
        rel = p.relative_to(srcp)
        if _excluded(rel, pats):
            excluded.append(str(rel))
            continue
        if p.is_symlink() or not p.is_file():
            continue
        out = dstp / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, out)
        n += 1

    substituted = []
    for name, body in subs.items():
        target = dstp / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        substituted.append(name)
        n += 1
    return {"files": n, "excluded": excluded, "substituted": sorted(substituted)}


def scan_for_pii(root: str | Path, *, max_hits: int = 20) -> list[dict]:
    """出口扫描:→ [{path, kind, sample}]。空列表 = 未检出明显 PII。

    必须跳过 _EXCLUDE_DIRS(venv/缓存等):第三方库源码里的作者邮箱
    会淹没真实信号——Phase 1 首测在真实副本上实测到 20 条全来自
    `.venv/site-packages`,而副本自身零命中。"""
    rootp = Path(root).expanduser().resolve()
    hits: list[dict] = []
    for p in sorted(rootp.rglob("*")):
        if len(hits) >= max_hits:
            break
        if not p.is_file() or p.is_symlink() or p.suffix.lower() not in _SCAN_SUFFIXES:
            continue
        if any(part in _SCAN_SKIP_DIRS for part in p.relative_to(rootp).parts):
            continue
        try:
            if p.stat().st_size > _MAX_SCAN_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for kind, pat in _PII_PATTERNS:
            m = pat.search(text)
            if m:
                raw = m.group(0)
                hits.append({"path": str(p.relative_to(rootp)), "kind": kind,
                             "sample": raw[:3] + "***" + raw[-2:]})
                break
    return hits
