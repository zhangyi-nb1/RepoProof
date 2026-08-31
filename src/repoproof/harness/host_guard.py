"""主目录硬护栏 + 保护目录指纹对账(TESTPLAN-V2 §4 第 1/6 层,Phase 0 ①)。

红线:用户真实开发目录(本仓自身及其兄弟 git 仓库)绝不允许成为任何
写入目标;每次运行前后对保护目录做指纹对账,被写必当场发现。保护集合
按**结构**发现而非硬编码目录名 —— 见 `structural_protected()`。
教训来源(CASEBOOK 案例 1 系/审核实证):路径比较必须 realpath
归一化 + 大小写不敏感(APFS),软链/相对路径/`~` 变体全覆盖。

指纹范围:工作树含 untracked(排除 .git 与高噪声缓存目录,见
_SKIP)+ git HEAD/refs 摘要(护住历史与分支指针)。mismatch 语义:
立即停止一切自动动作,人工判定;用户在 run 期间自改主目录属违纪,
判定时如实区分。

**归因层(2026-08-17)**:mismatch 只说"变了",说不出"谁写的",于是
邻仓的活写手(实测:offerclaw `logs/llm_usage.jsonl` 每 7–28 秒一次)
能把一条与它毫无关系的测试拖红。`SelfWriteWindow` 给对账补上作案
时刻:本链**唯一可能写盘的时段**是会话存在期,窗外只跑只读扫描
(实测冒烟链 83 秒里,会话只存在 1.24 秒)。落在窗外的改动**不可能
是本链写的**——这是时间线的硬事实,不是启发式。
`ok` 的语义**一个字没动**(逐位零改动,台账口径不变),免罪只体现在
新增的 `self_ok` 上,且默认关闭:不传窗口 = 无归因依据 = 一律不免罪。
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

_SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__",
         ".mypy_cache", ".ruff_cache", ".pytest_cache", ".DS_Store"}

DEFAULT_PROTECTED = (
    # harness 独占的 runtime 封存区(A1 provisioning 的产物)。
    #
    # **不放在 `~/RepoProofBench/` 下**:那里的护栏是"白名单外一律算游离物"
    # (`bench_root_strays`),往白名单里加一个几百 MB 的 runtime,正是
    # LESSONS #29 判过的错法 —— 给兄弟目录开口子。所以另立一个根,并按
    # 保护目录对待:agent 读写它都发不出去。
    #
    # 为什么必须保护:runtime 里装着真上游本体。agent 若够得着,它大可自己
    # import 自己调,整条 sidecar 拓扑当场失效,而"它没来敲门"会被读成偷懒。
    "~/RepoProofRuntimes",
)


class HostGuardError(RuntimeError):
    pass


def _norm(p: str | Path) -> str:
    """**比对键**归一化:realpath + 小写(APFS 大小写不敏感)。

    只许用于比较,不许当文件系统路径访问 —— lower 后的路径在
    大小写敏感的 fs(ext4,CI Linux)上可能根本不存在;拿它去
    is_dir()/rglob() 会把保护目录**静默漏出快照**(CI 预演实测:
    macOS 上碰巧全绿,Linux 上 snapshot_protected 返回空集)。"""
    return os.path.realpath(os.path.expanduser(str(p))).lower().rstrip("/")


def _real(p: str | Path) -> str:
    """**访问路径**归一化:realpath 保留真实大小写(fs 访问用这个)。"""
    return os.path.realpath(os.path.expanduser(str(p))).rstrip("/")


def _repo_root() -> str | None:
    """本仓根目录(.git + pyproject.toml 双证认定;非 editable 安装 → None)。"""
    here = Path(__file__).resolve()
    for cand in list(here.parents)[:5]:
        if (cand / ".git").exists() and (cand / "pyproject.toml").exists():
            return _real(cand)
    return None


def structural_protected() -> list[str]:
    """**结构性**保护集合:本仓自身 + 其兄弟 git 仓库。

    为什么不再硬编码目录名(外部审查 2026-08-26):
    `~/Desktop/XIANGMU/offerclaw` 这类个人路径写进公开仓的安全模块,
    在别人机器上是**不存在的路径**(=保护集合为空,护栏静默失效),
    在作者机器上又把私人目录结构公开了。改按结构发现:同一父目录下
    另有 `.git` 的目录就是"用户的真实开发仓"。这比按名字硬编码更强
    —— 新增邻仓自动受保护,不依赖谁记得回来改常量,而"忘了改常量"
    正是静默失去保护的典型路径。

    退化是**可观测**的,不是静默的:非 editable 安装推不出仓根时返回
    空列表,`protection_report()["repo_root"]` 记 None,且单测钉死
    "开发/CI 环境下本仓自身必须在保护列表里"(见 test_host_guard)。
    """
    root = _repo_root()
    if root is None:
        return []
    out = [root]
    try:
        for child in sorted(Path(root).parent.iterdir()):
            if child.is_dir() and (child / ".git").exists():
                real = _real(child)
                if real not in out:
                    out.append(real)
    except OSError:
        pass                      # 父目录不可读 → 只保自身,不静默扩权
    return out


def protection_report() -> dict[str, object]:
    """保护集合的来源分账 —— 供排障/取证用,不参与判定。"""
    return {
        "repo_root": _repo_root(),
        "structural": structural_protected(),
        "defaults": [_real(d) for d in DEFAULT_PROTECTED],
        "env": [_real(d) for d in
                os.environ.get("REPOPROOF_PROTECTED_DIRS", "").split(":")
                if d.strip()],
    }


def protected_dirs(extra_env: bool = True) -> list[str]:
    """当前保护目录(realpath,**保留真实大小写**)。

    三个来源并集:结构性(本仓 + 兄弟 git 仓)、缺省常量
    (`~/RepoProofRuntimes`)、以及 REPOPROOF_PROTECTED_DIRS(冒号分隔)
    追加。大小写不敏感的匹配语义在 is_protected 的比对侧实现,不在
    这里丢信息。"""
    dirs = list(structural_protected())
    for d in DEFAULT_PROTECTED:
        real = _real(d)
        if real not in dirs:
            dirs.append(real)
    if extra_env:
        for d in os.environ.get("REPOPROOF_PROTECTED_DIRS", "").split(":"):
            if d.strip():
                real = _real(d)
                if real not in dirs:
                    dirs.append(real)
    return dirs


def is_protected(path: str | Path, protected: list[str] | None = None) -> bool:
    target = _norm(path)
    for p in (protected if protected is not None else protected_dirs()):
        q = p.lower().rstrip("/")     # 兼容调用方传 lower 键或真实路径
        if target == q or target.startswith(q + "/"):
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
    """保护目录指纹:{tree, git_refs, files, entries}。

    tree = sha256(排序的 相对路径\\0大小\\0mtime_ns);含 untracked;
    无文件数上限(保护对账不允许"太大就不看")。

    `entries`(相对路径 → [size, mtime_ns])是同一趟读数的逐条留存,
    **只为对账时能说出"变的是哪几条、什么时候变的"**:树哈希只会说
    "变了",而说不出变在哪就无从归因,归不了因就只能一刀切判红。"""
    rootp = Path(os.path.expanduser(str(root)))
    lines: list[str] = []
    entries: dict[str, tuple[int, int]] = {}
    if rootp.is_file() and not rootp.is_symlink():
        try:
            st = rootp.stat()
        except OSError:
            st = None
        if st is not None:
            entries["."] = (st.st_size, st.st_mtime_ns)
            lines.append(f".\0{st.st_size}\0{st.st_mtime_ns}")
        return {
            "tree": hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest(),
            "git_refs": "",
            "files": len(entries),
            "entries": entries,
        }
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
        entries[str(rel)] = (st.st_size, st.st_mtime_ns)
        lines.append(f"{rel}\0{st.st_size}\0{st.st_mtime_ns}")
    return {
        "tree": hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest(),
        "git_refs": _git_refs_digest(rootp),
        "files": len(entries),
        "entries": entries,
    }


def snapshot_protected(protected: list[str] | None = None) -> dict[str, dict]:
    """对全部存在的保护目录拍指纹(run 前调用)。"""
    out: dict[str, dict] = {}
    for d in (protected if protected is not None else protected_dirs()):
        if Path(d).exists():
            out[d] = dir_fingerprint(d)
    return out


# ------------------------------------------------------- 变动归因(谁写的)

SELF = "SELF"                                   # 归到本链名下 → 必须继续红
EXTERNAL = "EXTERNAL"                           # 已证明不是本链 → 可降级为警告

_R_OUT_OF_WINDOW = "EXTERNAL_OUT_OF_WINDOW"     # 作案时刻落在会话存在期之外
_R_LIVE_WRITER = "EXTERNAL_LIVE_WRITER"         # 拆除后该路径仍在动 = 有活写手
_R_IN_WINDOW_QUIESCENT = "SELF_IN_WINDOW_QUIESCENT"   # 窗内动过、拆除后不动了
_R_NO_TIMESTAMP = "SELF_NO_TIMESTAMP"           # 删除等拿不到作案时刻
_R_NO_WINDOW = "SELF_NO_WINDOW"                 # 调用方没给窗口 = 无归因依据
_R_NO_EVIDENCE = "SELF_NO_EVIDENCE"             # 哈希对不上却列不出改动 = 说不清

_ATTR_LIST_CAP = 20                             # 落 report 的明细条数上限


@dataclass(frozen=True)
class SelfWriteWindow:
    """本链**有可能写盘**的墙钟时段(`time.time()` 语义)。

    start = 会话建立前一刻,end = 会话拆除后一刻。这之外本链只做只读
    扫描(指纹遍历用 `stat`,git 证据用 `rev-parse`/`for-each-ref`),
    所以窗外发生的写**不可能出自本链**。

    `margin_s` 双向外扩:边界一律判给"自写"——保守方向是继续红。

    **两处如实划界,不装作没有**:
    1. mtime 只记得住"最后一次写"。外部写手在本链之后又写了同一条
       路径,本链那次就被盖住。这是 mtime 的固有上限,不是本实现的
       疏忽;换任何"事后看文件系统"的做法都一样。
    2. 上界靠"`exec` 用 `communicate()` 等到进程结束、超时 killpg 整组"
       成立。真有孙进程闭掉管道后活过拆除并延迟写盘,窗外那段就不再
       严密。此路径只给零模型零 agent 的空转冒烟用;有 agent 在场的
       正式 run 走的是原封不动的严判 `ok`,归因只作为证据附随。
    """

    start: float
    end: float
    margin_s: float = 1.0

    def contains(self, mtime: float) -> bool:
        return self.start - self.margin_s <= mtime <= self.end + self.margin_s

    def as_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "margin_s": self.margin_s}


def _diff_entries(before: dict | None, after: dict) -> list[dict]:
    """两份 entries 的逐路径差集 → [{path, kind, mtime}](按路径排序)。

    `mtime` = 变动之后该文件的 mtime(秒);删除拿不到时刻,记 None。

    `before` 缺 entries(旧格式指纹)时**不做差集**:拿不到基线就无从
    比对,硬比会把满树文件全算成"新增"、再按各自 mtime 大面积免罪。
    如实返回一条无时刻记录 → 判 SELF,继续红。"""
    if before is None:
        return [{"path": "<no-baseline-entries>", "kind": "unknown", "mtime": None}]
    changes: list[dict] = []
    for rel in sorted(set(before) | set(after)):
        b, a = before.get(rel), after.get(rel)
        if b == a:
            continue
        kind = "added" if b is None else "removed" if a is None else "modified"
        changes.append({"path": rel, "kind": kind,
                        "mtime": None if a is None else a[1] / 1e9})
    return changes


def _git_ref_witnesses(root: Path) -> list[Path]:
    """refs 变动的"作案时刻"证人:改 refs 必然落在这几个文件之一上。"""
    g = root / ".git"
    if not g.is_dir():          # `.git` 是文件(worktree/submodule 形态)→ 无证人
        return []
    out = [p for p in (g / "HEAD", g / "packed-refs") if p.is_file()]
    for sub in ("refs", "logs"):
        d = g / sub
        if d.is_dir():
            out.extend(p for p in d.rglob("*") if p.is_file() and not p.is_symlink())
    return out


def _git_refs_changes(root: Path, window: SelfWriteWindow | None) -> list[dict]:
    """refs 变动的候选作案记录。

    找不到证人就**不许免罪**(返回一条无时刻记录 → 判 SELF):归因拿不到
    证据时的默认值必须是"继续红",否则闸门就被"查不到"这三个字掏空了。"""
    witnesses = _git_ref_witnesses(root)
    if not witnesses:
        return [{"path": ".git", "kind": "git_refs", "mtime": None}]
    stamped: list[dict] = []
    for p in witnesses:
        try:
            stamped.append({"path": str(p.relative_to(root)), "kind": "git_refs",
                            "mtime": p.stat().st_mtime})
        except OSError:
            continue
    if not stamped:
        return [{"path": ".git", "kind": "git_refs", "mtime": None}]
    inside = [c for c in stamped if window is not None and window.contains(c["mtime"])]
    # 窗内有证人 → 那几个就是待查嫌疑;一个都没有 → 只留最新的一个当证据。
    return inside or [max(stamped, key=lambda c: c["mtime"])]


def _live_writer_probe(root: Path, rels: list[str], *,
                       probe_s: float, interval_s: float) -> dict:
    """拆除之后再盯这几条路径,看它们**还动不动**。

    这一步跑在会话已销毁、本链只剩只读扫描的时刻——此时还在动的,只能
    是别的进程。**只盯这几条路径本身**,不看兄弟、不看父目录:"同目录里
    有个忙文件"不构成对这一条的免罪,否则热闹目录就成了洗白通道(LESSONS
    #29 判过的同型错法:放行一个目录不等于放行它装的一切)。

    检出率取决于外部写手的周期,本探针只是窗内那 1.5% 残余的补刀;
    真正承重的是时间线那一层。测不到就是测不到,测不到即判 SELF。"""
    def state(rel: str):
        try:
            st = (root / rel).stat()
            return (st.st_size, st.st_mtime_ns)
        except OSError:
            return None

    base = {rel: state(rel) for rel in rels}
    moved: set[str] = set()
    samples = 0
    deadline = time.monotonic() + probe_s
    while time.monotonic() < deadline and len(moved) < len(rels):
        time.sleep(interval_s)
        samples += 1
        for rel in rels:
            if rel not in moved and state(rel) != base[rel]:
                moved.add(rel)
    return {"moved": moved, "samples": samples, "probe_s": probe_s}


def _attribute(root: Path, changes: list[dict], window: SelfWriteWindow | None, *,
               probe_s: float, probe_interval_s: float) -> dict:
    """逐条改动定责 → {verdict, n_self, n_external, self_changes, external_changes}。

    **免罪必须有正面证据**(窗外发生 / 拆除后仍在动);其余一律 SELF。"""
    decided: list[dict] = []
    pending: list[dict] = []
    if not changes:
        # 哈希对不上、却一条改动都列不出来 —— 说不清就不许免罪。空表在
        # Python 里恒假,若不显式挡住,"列不出改动"会被读成"没有可疑改动"
        # 而自动判 EXTERNAL:那是把闸门交给一个 bug 去开。
        decided.append({"path": "<unlistable>", "kind": "unknown", "mtime": None,
                        "verdict": SELF, "reason": _R_NO_EVIDENCE})
    for ch in changes:
        if window is None:
            decided.append({**ch, "verdict": SELF, "reason": _R_NO_WINDOW})
        elif ch["mtime"] is None:
            decided.append({**ch, "verdict": SELF, "reason": _R_NO_TIMESTAMP})
        elif not window.contains(ch["mtime"]):
            decided.append({**ch, "verdict": EXTERNAL, "reason": _R_OUT_OF_WINDOW})
        else:
            pending.append(ch)

    probe = None
    if pending and probe_s > 0:
        probe = _live_writer_probe(root, [c["path"] for c in pending],
                                   probe_s=probe_s, interval_s=probe_interval_s)
    for ch in pending:
        live = bool(probe and ch["path"] in probe["moved"])
        decided.append({**ch, "verdict": EXTERNAL if live else SELF,
                        "reason": _R_LIVE_WRITER if live else _R_IN_WINDOW_QUIESCENT})

    mine = [c for c in decided if c["verdict"] == SELF]
    theirs = [c for c in decided if c["verdict"] == EXTERNAL]
    return {
        "verdict": SELF if mine else EXTERNAL,
        "n_self": len(mine), "n_external": len(theirs),
        "self_changes": mine[:_ATTR_LIST_CAP],
        "external_changes": theirs[:_ATTR_LIST_CAP],
        "probe": None if probe is None else {"samples": probe["samples"],
                                             "probe_s": probe["probe_s"],
                                             "moved": sorted(probe["moved"])[:_ATTR_LIST_CAP]},
    }


def verify_protected_unchanged(before: dict[str, dict],
                               protected: list[str] | None = None, *,
                               self_window: SelfWriteWindow | None = None,
                               probe_s: float = 6.0,
                               probe_interval_s: float = 0.25) -> dict:
    """run 后对账。→ {ok, self_ok, attributed, mismatches}。

    - `ok`      逐位零改动。**语义与历史台账口径一字未改**,任何一条
                改动(哪怕已证明是外部写手)都让它变 False。
    - `self_ok` 归因后:没有一条改动可以归到本链名下。不传 `self_window`
                时无归因依据,`self_ok` 恒等于 `ok`——默认不免任何罪。
    - 每条 mismatch 带 `attribution`,逐条写明定责与理由,供人工复核。

    发现 mismatch 时调用方必须:停止一切自动动作、记录 runs.jsonl
    (main_dir_integrity)、交人工判定——绝不自动"修复"。**降级为警告
    是调用方的显式决定**(见 `run_host_smoke`),本函数只出具证据。"""
    mismatches: list[dict] = []
    any_self = False
    for d, fp in before.items():
        after = dir_fingerprint(d)
        for field in ("tree", "git_refs"):
            if after.get(field) == fp.get(field):
                continue
            changes = (_diff_entries(fp.get("entries"), after.get("entries") or {})
                       if field == "tree"
                       else _git_refs_changes(Path(d), self_window))
            attribution = _attribute(Path(d), changes, self_window,
                                     probe_s=probe_s, probe_interval_s=probe_interval_s)
            any_self = any_self or attribution["verdict"] == SELF
            mismatches.append({"dir": d, "field": field,
                               "before": fp.get(field), "after": after.get(field),
                               "attribution": attribution})
    return {"ok": not mismatches,
            "self_ok": not any_self,
            "attributed": self_window is not None,
            "self_window": self_window.as_dict() if self_window else None,
            "mismatches": mismatches}


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
    # 第二宿主(C 轨,2026-08-15):flask-smorest 0.47.0 的封存件 + 轮仓 + 清单。
    # 登记进来是**有意识的动作** —— 它 2026-08-15 那天当场拦下过一发,
    # 那正是这条白名单该有的表现,不是它的毛病。
    "host2-flask-smorest",
    "offerclaw-t3-browser-use",      # T3 宿主副本
    # HB-PCDELTA-1(2026-08-16):三个 post-cutoff delta 宿主(盲攻同视野
    # delivery 树 + 轮仓)。封存原件在 ~/RepoProofArchive/d5-hunt,不进 bench。
    "hb1-click-3581",
    "hb1-click-3407",
    "hb1-sqlglot-8042",
    # R1/R2(2026-08-21):构造法 v2 宿主(base 版测试留树,基线 1193)。
    # 新代际新宿主,v1 副本不动;登记同样是有意识动作。
    "hb1-sqlglot-8042-v2",
    # v2 扩批(2026-08-21,用户批准):click 两任务同法换代宿主。
    "hb1-click-3581-v2",
    "hb1-click-3407-v2",
    # LOCAL-TOOL 产品线首任务(M1,2026-08-23):host = 工具骨架副本
    # (harness 生成,无用户数据),wheelhouse = pdfplumber+pytest 闭包轮仓。
    # 登记照旧是有意识动作;答案区(controls/oracle)在任务包与仓内,不入 bench。
    "tool-pdf-table-v1",
    # M2 验收任务(2026-08-23):markdownify → html2md,同律登记。
    "tool-html2md-v1",
})
_BENCH_ALLOWED_PREFIXES = ("wheelhouse-",)   # 冻结轮仓(commit 尾号命名)

# **目录内部**也要有名单(2026-08-15,LESSONS #29 同型第二次)。
#
# 原来白名单的粒度只到顶层目录名,于是 `host2-flask-smorest/` 整个放行 ——
# 而它里面同时装着交付树 `host/`、**未挖空的原件 `repo/`(含 .git 与 554 条
# 隐藏 oracle)**、一个 `.pth` 指回原件的 venv,和一份 `plugins.py.pristine`。
# 对抗性搜捕当场用一条 `cat .pth` 把 12 个函数体逐字节取回。
#
# 这与 #29 那次(`offerclaw-transaction-stack/` 内含三份 PASS 解被整个放行)
# **完全同型**:闸门拦住了无害的,放行了答案卷。当时的结论是"改精确名单",
# 但只改了一层 —— 一层名单挡不住"合法目录里装着不该有的东西"。
_BENCH_ALLOWED_ENTRIES: dict[str, frozenset[str]] = {
    # 第二宿主:只许交付树与轮仓。原件/venv/pristine 一律归档到 bench 根之外。
    "host2-flask-smorest": frozenset({"host", "wheelhouse"}),
    # HB delta 宿主同律:host = 盲攻 delivery 逐字节,wheelhouse = 封存轮仓。
    # 答案区(answer/delta_tests/repos)永不入 bench —— G4b 钉死。
    "hb1-click-3581": frozenset({"host", "wheelhouse"}),
    "hb1-click-3407": frozenset({"host", "wheelhouse"}),
    "hb1-sqlglot-8042": frozenset({"host", "wheelhouse"}),
    "hb1-sqlglot-8042-v2": frozenset({"host", "wheelhouse"}),
    "hb1-click-3581-v2": frozenset({"host", "wheelhouse"}),
    "hb1-click-3407-v2": frozenset({"host", "wheelhouse"}),
    # LOCAL-TOOL 同律:只许骨架副本与轮仓。
    "tool-pdf-table-v1": frozenset({"host", "wheelhouse"}),
    "tool-html2md-v1": frozenset({"host", "wheelhouse"}),
}


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
            strays.extend(_entry_strays(entry))
            continue
        # LOCAL-TOOL 谱系(M4,2026-08-23):`tool-*` 按**规则准入**而非逐个
        # 登记 —— 产品常态是每个用户工具一个 bench 条目,逐个改代码不成立。
        # #29 的要害是前缀放行了**答案卷**;工具条目内容无答案(骨架 =
        # harness 模板,答案区 controls/oracle 在仓内、按设计不入 bench),
        # 且这里对前缀条目**强制**内部两项制 {host, wheelhouse}:目录里
        # 塞任何别的东西照样报 stray(#29 第二型的兜底不豁免)。
        if name.startswith("tool-") and entry.is_dir():
            allowed = frozenset({"host", "wheelhouse"})
            strays.extend(
                f"{name}/{c.name}" for c in sorted(entry.iterdir())
                if c.name != ".DS_Store" and c.name not in allowed)
            continue
        if name.startswith(_BENCH_ALLOWED_PREFIXES) or (extra and name.startswith(extra)):
            continue
        strays.append(name)
    return strays


def _entry_strays(entry: Path) -> list[str]:
    """已登记目录**内部**的白名单。放行一个目录不等于放行它装的一切。

    只对显式登记了内部名单的目录生效 —— 没登记的维持原状(整个放行),
    免得给 T1–T3 那三个宿主副本凭空加一道会误伤的闸门。
    """
    allowed = _BENCH_ALLOWED_ENTRIES.get(entry.name)
    if allowed is None or not entry.is_dir():
        return []
    return [f"{entry.name}/{p.name}" for p in sorted(entry.iterdir(), key=lambda x: x.name)
            if p.name != ".DS_Store" and p.name not in allowed]
