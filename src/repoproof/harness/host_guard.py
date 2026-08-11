"""主目录硬护栏 + 保护目录指纹对账(TESTPLAN-V2 §4 第 1/6 层,Phase 0 ①)。

红线:用户真实开发目录(OfferClaw / LocalFlow / RepoProof 自身)绝不
允许成为任何写入目标;每次运行前后对保护目录做指纹对账,被写必当场
发现。教训来源(CASEBOOK 案例 1 系/审核实证):路径比较必须 realpath
归一化 + 大小写不敏感(APFS),软链/相对路径/`~` 变体全覆盖。

指纹范围:工作树含 untracked(排除 .git 与高噪声缓存目录,见
_SKIP)+ git HEAD/refs 摘要(护住历史与分支指针)。mismatch 语义:
立即停止一切自动动作,人工判定;用户在 run 期间自改主目录属违纪,
判定时如实区分。
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

_SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__",
         ".mypy_cache", ".ruff_cache", ".pytest_cache", ".DS_Store"}

DEFAULT_PROTECTED = (
    "~/Desktop/XIANGMU/offerclaw",
    "~/Desktop/XIANGMU/localflow",
    "~/Desktop/XIANGMU/RepoProof",
)


class HostGuardError(RuntimeError):
    pass


def _norm(p: str | Path) -> str:
    """realpath 归一化 + 小写(APFS 大小写不敏感)。"""
    return os.path.realpath(os.path.expanduser(str(p))).lower().rstrip("/")


def protected_dirs(extra_env: bool = True) -> list[str]:
    """当前保护目录(归一化)。可经 REPOPROOF_PROTECTED_DIRS(冒号分隔)追加。"""
    dirs = [_norm(d) for d in DEFAULT_PROTECTED]
    if extra_env:
        for d in os.environ.get("REPOPROOF_PROTECTED_DIRS", "").split(":"):
            if d.strip():
                dirs.append(_norm(d))
    return dirs


def is_protected(path: str | Path, protected: list[str] | None = None) -> bool:
    target = _norm(path)
    for p in (protected if protected is not None else protected_dirs()):
        if target == p or target.startswith(p + "/"):
            return True
    return False


def assert_writable_target(path: str | Path, *, purpose: str,
                           protected: list[str] | None = None) -> None:
    """一切写路径的准入检查——命中保护目录立即拒绝,无任何旁路。"""
    if is_protected(path, protected):
        raise HostGuardError(
            f"拒绝{purpose}:目标路径命中受保护的真实开发目录({path})。"
            "请使用 ~/RepoProofBench/ 下的独立副本(git clone --no-hardlinks,"
            "并移除 origin)。此护栏无旁路。")


# ---------------------------------------------------------------- 指纹对账

def _git_refs_digest(root: Path) -> str:
    """HEAD + 全部 refs 的摘要;非 git 目录返回空串。"""
    if not (root / ".git").exists():
        return ""
    try:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=30).stdout
        refs = subprocess.run(
            ["git", "-C", str(root), "for-each-ref",
             "--format=%(refname)%(objectname)"],
            capture_output=True, text=True, timeout=30).stdout
        return hashlib.sha256((head + refs).encode()).hexdigest()
    except (subprocess.SubprocessError, OSError):
        return "GIT_PROBE_FAILED"


def dir_fingerprint(root: str | Path) -> dict:
    """保护目录指纹:{tree, git_refs, files}。

    tree = sha256(排序的 相对路径\\0大小\\0mtime_ns);含 untracked;
    无文件数上限(保护对账不允许"太大就不看")。"""
    rootp = Path(os.path.expanduser(str(root)))
    lines: list[str] = []
    n = 0
    for p in sorted(rootp.rglob("*")):
        rel = p.relative_to(rootp)
        if any(part in _SKIP for part in rel.parts):
            continue
        if not p.is_file() or p.is_symlink():
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        n += 1
        lines.append(f"{rel}\0{st.st_size}\0{st.st_mtime_ns}")
    return {
        "tree": hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest(),
        "git_refs": _git_refs_digest(rootp),
        "files": n,
    }


def snapshot_protected(protected: list[str] | None = None) -> dict[str, dict]:
    """对全部存在的保护目录拍指纹(run 前调用)。"""
    out: dict[str, dict] = {}
    for d in (protected if protected is not None else protected_dirs()):
        if Path(d).is_dir():
            out[d] = dir_fingerprint(d)
    return out


def verify_protected_unchanged(before: dict[str, dict],
                               protected: list[str] | None = None) -> dict:
    """run 后对账。→ {ok, mismatches:[{dir, field, before, after}]}。

    发现 mismatch 时调用方必须:停止一切自动动作、记录 runs.jsonl
    (main_dir_integrity)、交人工判定——绝不自动"修复"。"""
    mismatches: list[dict] = []
    for d, fp in before.items():
        after = dir_fingerprint(d)
        for field in ("tree", "git_refs"):
            if after.get(field) != fp.get(field):
                mismatches.append({"dir": d, "field": field,
                                   "before": fp.get(field), "after": after.get(field)})
    return {"ok": not mismatches, "mismatches": mismatches}


# ---------------- bench 根环境卫生(T2 批 1 实证教训,2026-08-10) ----------------
# 实录:任务工程遗留的正控工作副本(_scratch_t2_positive/research_jobs.py)
# 被 gpt-5.5/gpt-5.6 各自一条 ls 挖到并精读——参考实现暴露即能力测量污染;
# 同根还躺过真实数据备份(未被读,属未爆雷)。L 模式护栏拦写不拦读,
# 唯一可靠防线 = 开跑前 bench 根白名单清场,白名单外任何条目零预算 BLOCKED。

# 2026-08-12 收紧(LESSONS #29):原白名单用**前缀** `offerclaw-`,于是 T4
# 建的事务栈 `offerclaw-transaction-stack/`(内含 T1/T2/T3 三份已验证 PASS
# 解:sdk_mcp.py / research_jobs.py / apply_assist.py)与其 ledger 备份全部
# **被放行**,而无害的 `upstream/` 反被拦。闸门拦住了无害的、放行了答案卷。
# 根因:前缀是"看起来像宿主副本"的近似,而闸门要判的是"这就是那三个宿主
# 副本"。改为**精确名单**——新增宿主副本必须显式登记,登记是一次有意识的
# 动作,而不是命名巧合。
BENCH_ROOT_DEFAULT = "~/RepoProofBench"
_BENCH_ALLOWED_NAMES = frozenset({
    "_sessions",                     # 会话区(每 run 一个子目录,跑完销毁)
    "offerclaw-t1-fastapi-mcp",      # T1 宿主副本
    "offerclaw-t2-odr",              # T2 宿主副本
    "offerclaw-t3-browser-use",      # T3 宿主副本
})
_BENCH_ALLOWED_PREFIXES = ("wheelhouse-",)   # 冻结轮仓(commit 尾号命名)


def bench_root_strays(bench_root: str | Path = BENCH_ROOT_DEFAULT) -> list[str]:
    """返回 bench 根下白名单外的条目名(排序);空列表 = 干净。

    白名单:三个**具名**宿主副本 + 会话区 `_sessions` + 冻结轮仓
    `wheelhouse-*`。追加合法前缀经 REPOPROOF_BENCH_ALLOWED(冒号分隔)——
    该逃生门只应用于一次性排障,**不要写进启动脚本**:写进去=对所有后续
    run 静默放宽,而闸门的价值全在"没人能顺手绕过"。"""
    root = Path(os.path.expanduser(str(bench_root)))
    if not root.is_dir():
        return []
    extra = tuple(p for p in os.environ.get("REPOPROOF_BENCH_ALLOWED", "").split(":") if p)
    strays = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        name = entry.name
        if name == ".DS_Store" or name in _BENCH_ALLOWED_NAMES:
            continue
        if name.startswith(_BENCH_ALLOWED_PREFIXES) or (extra and name.startswith(extra)):
            continue
        strays.append(name)
    return strays
