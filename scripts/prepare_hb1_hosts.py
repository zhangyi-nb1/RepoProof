#!/usr/bin/env python3
"""HB-PCDELTA-1 三宿主部署 —— V 树重构 + 交叉验证 + 回归基线 + 校准泄漏自证。

预注册:benchmarks/v2/preregistrations/HB-batch1-postcutoff-delta-prereg-20260816.md
封存池:~/RepoProofArchive/d5-hunt(**绝对只读** —— 本脚本对它零写操作,
`_guard_write` 在每个写目标上执法,不靠自觉)。

## 第二轮(2026-08-16 裁决)—— 为什么 host 源不再是 attacks/<id>/delivery

第一轮按说明把 `attacks/<id>/delivery` 当纯净交付树部署,泄漏扫描当场撞出:
**delivery 是攻击者的终态树**(parent 剥离后 + 攻击者自己的实现;3581 的
decorators.py 里躺着一份完整的 `custom_version_option`)。照此发次,受测模型
等于站在盲攻者的答卷上起跑(8042 尤甚:盲攻已拿回 4/5)。裁决(判据方向
用户定,执行在此):

- **V 树重构**:路径集 = delivery ∩ parent_tree(攻击者新建的文件自然剔除),
  内容**一律取 parent_tree 版本**(攻击者改过的文件回到 parent 态);
- **交叉验证一**:V 的路径集必须**恰好等于** parent − .github/** −
  manifest.test_files(8042 另减 CHANGELOG.md);两条推导不一致 →
  **停下报差异,不部署**(纯函数 construction_check,tripwire 语义);
- **裁决二(同日,tripwire 实测触发后)**:两条推导**双双剔除
  `__pycache__/**` 与 `*.pyc`,V 一律不含字节码**。tripwire 首跑差异
  26/40/299 条、百分之百字节码,其中被剥测试文件的 parent 侧 .pyc
  (test_basic / test_types / test_prompt / test_lineage)全躺在期望推导里
  —— 那是指向隐藏 oracle 的结构性箭头且可反编译;攻击者实际视野本就无
  字节码,会话快照 DEFAULT_EXCLUDES 也早排除 __pycache__,裁决与既有
  纪律同向。tripwire 的设计正确性由这次触发自证;
- **交叉验证二**:delivery 与 V 的全部差异(改动/新增)= 攻击者自笔,
  逐条留痕进证据 `attacker_residue`;
- **泄漏扫描加自校准**(round2 同法):parent 已有的指纹先剔除 —— 它们
  不是泄漏,是 diff 上下文里的既有行/子串重合;校准后对部署树必须零命中;
- **基线重测**:第一轮数字作废(发生过攻击件在场的测量),证据覆盖重生成。

三条自证纪律(与 prepare_host2.py 同一脉)不变:

1. **动作之后必须有机器结论。**"我复制了"是动作,"两条推导恰好相等 +
   逐文件 sha256 相等"才是结论。
2. **数字只出脚本。** 证据 json 由 main() 生成,手写的数字活不过下一次 main()。
3. **扫描器先证明自己有牙。** 种进去的答案必须报中,干净树必须零报 ——
   且校准剔掉了什么,逐条留名,免得"零命中"是把牙拔光换来的。

量法复用,不复制:树摘要 / junit 计分 / 离线环境 / venv PATH 全部 import
`blind_attack_admission` 的原件 —— 复制一份会在原件改动后静默漂移(M58a)。

子命令(可组合;--all = 依次 --hosts → --measure → --leak-scan):
    --hosts      重构 V → 交叉验证一/二 → 通过才部署(旧 host 删换,
                 wheelhouse 不动);已与 V 逐字节相同则 verify-only(幂等)。
    --measure    bench host 复制进 mkdtemp(不污染原件),封存配方离线建
                 venv 跑回归基线;判据 = 纯函数 judge_baseline(failed 必须 0)。
    --leak-scan  答案 full.patch 非测试新增行做指纹 → parent 预扫自校准 →
                 扫 bench host 全树;附种植/干净双向自证。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import blind_attack_admission as _baa  # noqa: E402

# 复用原件(import,不复制代码)—— 测试钉死这四个名字的 __module__。
digest_tree = _baa._digest_tree
score_from_junit = _baa.score_from_junit
offline_env = _baa.offline_env
venv_env = _baa.venv_env

ARCHIVE = Path("~/RepoProofArchive/d5-hunt").expanduser()      # 绝对只读
BENCH_ROOT = Path("~/RepoProofBench").expanduser()
EVIDENCE = REPO / "docs" / "evidence" / "hb1_hosts" / "prepare-hb1.json"
PREREG = ("benchmarks/v2/preregistrations/"
          "HB-batch1-postcutoff-delta-prereg-20260816.md")

CANDIDATES = ("click-3581", "click-3407", "sqlglot-8042")

# 构造法 v2 代际(R1,2026-08-21;R1R2-DELTA-V2-DESIGN §2.2):base 版测试
# 留树。vid = 证据键(check_host_digest.py 直接用它查),bench 独立目录,
# v1 宿主/证据全程不动;封存源仍是真 cid。
V2_TASKS = (
    {"vid": "sqlglot-8042-v2", "cid": "sqlglot-8042",
     "bench": "hb1-sqlglot-8042-v2", "law": "v2"},
    # v2 扩批(2026-08-21,用户批准建议 1):click 两任务同法换代。
    {"vid": "click-3581-v2", "cid": "click-3581",
     "bench": "hb1-click-3581-v2", "law": "v2"},
    {"vid": "click-3407-v2", "cid": "click-3407",
     "bench": "hb1-click-3407-v2", "law": "v2"},
)

ROUND = 2
ROUND_REASON = (
    "第二轮:attacks/<id>/delivery 实测为攻击者终态树(第一轮泄漏扫描撞出,"
    "含攻击者自己的实现),host 源按 2026-08-16 裁决改为重构视野树 V"
    "(路径 = delivery∩parent,内容一律 parent 版本);第一轮基线数字作废")
BYTECODE_RULING = (
    "裁决二(2026-08-16,tripwire 首跑触发后):两条推导双双剔除 "
    "__pycache__/** 与 *.pyc,V 一律不含字节码 —— 被剥测试文件的 parent 侧 "
    ".pyc 是指向隐藏 oracle 的结构性箭头且可反编译,攻击者实际视野本就无"
    "字节码;会话快照 DEFAULT_EXCLUDES 早已排除 __pycache__,与既有纪律同向")

# 裁决明写的每题额外剔除(V 期望集推导用)。
EXPECTED_EXTRA_DROP = {"sqlglot-8042": frozenset({"CHANGELOG.md"})}

# 封存配方(准入量具同款,blind_attack_admission 实测出的名单):
# sqlglot 无 .git 树需 scm 假版本(harness 旋钮不动树);测试面额外依赖
# 缺了会把收集期打崩(缺 duckdb/pandas → pytest 中断收集)。
MEASURE_EXTRAS = {
    "sqlglot-8042": {
        "env": {"SETUPTOOLS_SCM_PRETEND_VERSION": "0.0.0"},
        "packages": ["duckdb", "pandas", "python-dateutil", "pytz",
                     "typing_extensions"],
    },
}

# bench 目录白名单(host_guard 纪律):hb1-* 里只许这两个名字。
BENCH_ALLOWED = frozenset({"host", "wheelhouse"})
PLANTED_NAME = "_rp_selfcheck_planted.txt"
_LIST_CAP = 100      # 字节核对差异清单入档上限;交叉验证与 residue **不设上限**


# ------------------------------------------------------------------ 纯函数
def judge_baseline(score: dict) -> dict:
    """基线配不配当回归尺子 —— 纯判官,与 IO 分离。

    failed 必须为 0:发次里模型的公开反馈就是这套回归,交付前它自己就红,
    红点会被误归因给模型。skip **不拦**(v2 卫生判据,用户裁决 b):平台
    常量 skip 如实入档,数字以实测为准,这里不写死预期值。
    """
    problems: list[str] = []
    if score.get("total", 0) <= 0:
        problems.append("一条测试都没收集到 —— 没有分母,这不是基线是空转")
    failed = list(score.get("failed_nodes", ()))
    if failed:
        problems.append(
            f"基线有 {len(failed)} 条红(如 {failed[:5]})—— "
            "交付树自己就红,发次里的红点将无从归因")
    return {"status": "READY" if not problems else "NOT_READY",
            "problems": problems}


def extract_fingerprints(patch_text: str, test_files) -> list[dict]:
    """答案指纹:full.patch 里**非测试文件**的新增行 —— 纯函数。

    测试文件的新增行是 delta 试件内容,归封存布局管(delta_tests 从不进
    交付面);这里猎的是**实现侧**答案。行判据:'+' 开头(剥掉 '+++ '
    文件头行)、剥 '+' 后 strip、长度 >20、去重、re.escape。文件归属按
    '+++ b/<path>' 追踪;测试文件按 manifest.json 的 test_files 判定。
    """
    tf = set(test_files)
    out: list[dict] = []
    seen: set[str] = set()
    current: str | None = None
    for ln in patch_text.splitlines():
        if ln.startswith("+++ "):                     # 文件头,不是新增行
            target = ln[4:].split("\t")[0].strip()
            if target.startswith("b/"):
                target = target[2:]
            current = None if target == "/dev/null" else target
            continue
        if not ln.startswith("+") or current is None or current in tf:
            continue
        s = ln[1:].strip()
        if len(s) > 20 and s not in seen:
            seen.add(s)
            out.append({"name": f"{current}:{s[:40]}", "raw": s,
                        "pattern": re.escape(s)})
    return out


def calibrate_fingerprints(fps: list[dict], parent_blob: str
                           ) -> tuple[list[dict], list[dict]]:
    """自校准(round2 同法)—— 纯函数。返回 (有效指纹, 剔除指纹)。

    parent 已有的指纹不是泄漏:攻击者/模型合法可见整棵 parent,diff 的
    新增行与既有行撞车(含子串重合,如 `columns: list[str] = []` 撞进
    `pre_pivot_columns: ...`)只会把真信号淹掉。剔掉的逐条留名 ——
    "零命中"必须能对账是校准换来的还是真干净。
    """
    kept: list[dict] = []
    dropped: list[dict] = []
    for f in fps:
        (dropped if re.search(f["pattern"], parent_blob) else kept).append(f)
    return kept, dropped


def is_bytecode(path: str) -> bool:
    """`__pycache__/**` 与 `*.pyc` —— V 一律不含字节码(裁决二)。

    被剥测试文件的 parent 侧 .pyc 是指向隐藏 oracle 的结构性箭头
    (`.py` 被剥而 `.pyc` 在场 = 点名 delta 试件所在文件)且可反编译出前态;
    交付给攻击者的视野实测本就无字节码。
    """
    return path.endswith(".pyc") or "__pycache__" in path.split("/")


def construction_check(delivery_paths, parent_paths, test_files,
                       extra_drop=frozenset(), law="v1") -> dict:
    """V 树构造的交叉验证一 —— 纯函数,tripwire 语义。

    两条独立推导(**双双剔除字节码**,裁决二)必须**恰好相等**:
      law="v1"(缺省,字面不变):
        推导 A(定义):V = delivery 路径集 ∩ parent 路径集 − 字节码;
        推导 B(期望):parent − .github/** − manifest.test_files −
                       extra_drop − 字节码。
      law="v2"(R1,2026-08-21;R1R2-DELTA-V2-DESIGN §2.2):base 版测试
      文件**留树** —— 封存 delivery 本就无测试文件,故推导 A 并回
      (test_files ∩ parent),推导 B 不再减 test_files;内容仍一律取
      parent 版,extra_drop(CHANGELOG 等 PR 叙述泄漏轴)照旧剥。
    不等 = 树里有未建模的差异(第一轮撞出攻击者终态、第二轮首跑撞出
    26/40/299 条 pycache 不对称,tripwire 两次都在干活),调用方必须
    停下报差异、不部署 —— 这里只判,不裁。V 的路径集随判决一起返回:
    部署方必须用**同一份**集合建树,不许自己再推一遍。
    """
    if law not in ("v1", "v2"):
        raise ValueError(f"未知构造法:{law!r}")
    parent_set = set(parent_paths)
    v = {p for p in set(delivery_paths) & parent_set
         if not is_bytecode(p)}
    expected = {p for p in parent_set
                if p != ".github" and not p.startswith(".github/")
                and not is_bytecode(p)}
    if law == "v2":
        v |= {p for p in test_files
              if p in parent_set and not is_bytecode(p)}
        expected -= set(extra_drop)
    else:
        expected -= set(test_files) | set(extra_drop)
    return {"ok": v == expected,
            "law": law,
            "v_count": len(v),
            "expected_count": len(expected),
            "v_paths": sorted(v),
            "missing_from_v": sorted(expected - v),   # 期望里有、推导 A 里没有
            "unexpected_in_v": sorted(v - expected)}  # V 里有、期望推导不认


def attacker_residue(delivery_map: dict[str, str],
                     parent_map: dict[str, str]) -> dict:
    """交叉验证二:delivery 相对 V(= parent 态)的全部差异 —— 纯函数。

    它们是攻击者自笔,逐条留痕:added = 攻击者新建(不进 V),
    modified = 攻击者改过(V 里回到 parent 版本)。
    """
    added = sorted(set(delivery_map) - set(parent_map))
    modified = sorted(p for p in set(delivery_map) & set(parent_map)
                      if delivery_map[p] != parent_map[p])
    return {"added": added, "modified": modified}


def file_diff(expected: dict[str, str], actual: dict[str, str]) -> dict:
    """逐文件核对判定 —— 纯函数。expected = 应然态,actual = bench 副本。

    三类差异分开列(缺 / 多 / 内容不符),任一非空即不 ok —— "digest 相等"
    只是总闸,出事时必须能指出**哪个文件**,否则结论没法行动。
    """
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    mismatch = sorted(r for r in set(expected) & set(actual)
                      if expected[r] != actual[r])
    return {"ok": not (missing or extra or mismatch),
            "missing": missing, "extra": extra, "mismatch": mismatch}


# ------------------------------------------------------------------ IO 辅助
def _guard_write(p: Path) -> Path:
    """封存池零写操作 —— 靠执法不靠自觉。所有写目标先过这道闸。"""
    rp = p.expanduser().resolve()
    if rp == ARCHIVE.resolve() or rp.is_relative_to(ARCHIVE.resolve()):
        raise RuntimeError(f"拒绝写封存池路径:{p}")
    return p


def _file_map(root: Path) -> dict[str, str]:
    return {f.relative_to(root).as_posix():
            "sha256:" + hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(root.rglob("*")) if f.is_file()}


def _tree_blob(root: Path) -> str:
    parts: list[str] = []
    for f in sorted(root.rglob("*")):
        if f.is_file():
            try:
                parts.append(f.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
    return "\n".join(parts)


def _manifest(cid: str) -> dict:
    return json.loads((ARCHIVE / "candidates" / cid / "manifest.json")
                      .read_text(encoding="utf-8"))


def _cap(lst: list) -> list | dict:
    if len(lst) <= _LIST_CAP:
        return lst
    return {"count": len(lst), "first": lst[:_LIST_CAP], "truncated": True}


def _run(argv: list[str], *, cwd: Path, env: dict,
         timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                          text=True, timeout=timeout)


# ------------------------------------------------------------------ --hosts
def stage_hosts(cid: str, *, bench_name: str | None = None,
                law: str = "v1") -> dict:
    parent = ARCHIVE / "candidates" / cid / "parent_tree"
    delivery = ARCHIVE / "attacks" / cid / "delivery"
    repo_short = _manifest(cid)["repo"].split("/")[-1]
    src_wheel = ARCHIVE / "wheelhouse" / repo_short
    for src in (parent, delivery, src_wheel):
        if not src.is_dir():
            raise RuntimeError(f"封存源不在:{src}")
    bench = BENCH_ROOT / (bench_name or f"hb1-{cid}")
    host = bench / "host"

    parent_map, delivery_map = _file_map(parent), _file_map(delivery)
    check = construction_check(delivery_map, parent_map,
                               _manifest(cid)["test_files"],
                               EXPECTED_EXTRA_DROP.get(cid, frozenset()),
                               law=law)
    # 部署用的路径集 = 判决返回的那一份(单一事实源);证据里不重复存
    # 全列表 —— host_digest + file_count + 逐字节核对已足以复算。
    v_paths = check.pop("v_paths")
    residue = attacker_residue(delivery_map, parent_map)

    # wheelhouse 不动(裁决):缺才补,在则只核对。
    _guard_write(bench / "wheelhouse")
    if not (bench / "wheelhouse").exists():
        bench.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_wheel, bench / "wheelhouse")
        wheel_mode = "copied"
    else:
        wheel_mode = "verify-only"
    wheel_diff = file_diff(_file_map(src_wheel), _file_map(bench / "wheelhouse"))

    result: dict = {
        "source_parent_tree": str(parent),
        "source_delivery": str(delivery),
        "source_wheelhouse": str(src_wheel),
        "bench_dir": str(bench),
        "construction_check": check,          # 交叉验证一,差异不设上限
        "attacker_residue": residue,          # 交叉验证二,逐条留痕
        "wheelhouse_mode": wheel_mode,
        "wheelhouse_digest": digest_tree(bench / "wheelhouse"),
        "wheelhouse_file_count": len(_file_map(bench / "wheelhouse")),
    }

    if not check["ok"]:
        # tripwire:两条推导不一致 → 停下报差异,不部署;旧 host 原样不动
        # (裁决只授权"删换成 V",V 构造不成立时删旧不是我的裁量)。
        result.update({
            "deployed": False,
            "host_digest": None,
            "file_count": None,
            "verify": {"wheelhouse": {k: _cap(v) if isinstance(v, list) else v
                                      for k, v in wheel_diff.items()}},
            "verify_ok": False,
        })
        miss, unexp = check["missing_from_v"], check["unexpected_in_v"]
        print(f"[hosts] {cid}: 构造自证一 **不一致 ✗** —— "
              f"V(delivery∩parent)= {check['v_count']} 条 vs 期望推导 = "
              f"{check['expected_count']} 条;期望有而 V 无 {len(miss)} 条,"
              f"V 有而期望无 {len(unexp)} 条。**不部署,旧宿主未动。**")
        for p in miss[:8]:
            print(f"    - 期望有而 V 无: {p}")
        if len(miss) > 8:
            print(f"    - …(其余 {len(miss) - 8} 条见证据 json)")
        for p in unexp[:8]:
            print(f"    - V 有而期望无: {p}")
        return result

    # 交叉验证通过 → 部署 V:路径 = 判决那份集合,内容一律取 parent 版本。
    v_map = {p: parent_map[p] for p in v_paths}
    _guard_write(host)
    if host.exists() and _file_map(host) == v_map:
        host_mode = "verify-only"             # 已经就是 V,幂等
    else:
        if host.exists():
            shutil.rmtree(host)               # 裁决:删掉旧 host 换成 V
        for rel in sorted(v_map):
            dest = host / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(parent / rel, dest)
        host_mode = "redeployed"
    host_diff = file_diff(v_map, _file_map(host))

    entries = sorted(p.name for p in bench.iterdir())
    guard_ok = set(entries) <= BENCH_ALLOWED
    verify_ok = (check["ok"] and host_diff["ok"] and wheel_diff["ok"]
                 and guard_ok)
    result.update({
        "deployed": True,
        "host_mode": host_mode,
        "host_digest": digest_tree(host),
        "file_count": len(v_map),
        "verify": {label: {k: _cap(v) if isinstance(v, list) else v
                           for k, v in d.items()}
                   for label, d in (("host_vs_V", host_diff),
                                    ("wheelhouse", wheel_diff))},
        "bench_dir_entries": entries,
        "verify_ok": verify_ok,
    })
    print(f"[hosts] {cid}: 构造自证一 恰好相等 ✓({check['v_count']} 条);"
          f"攻击者残迹 改 {len(residue['modified'])} / 新 "
          f"{len(residue['added'])} 已留痕;host {host_mode},逐字节 "
          f"{'对得上 ✓' if verify_ok else '**不符 ✗**'}")
    if not verify_ok:
        for label, d in (("host_vs_V", host_diff), ("wheelhouse", wheel_diff)):
            for kind in ("missing", "extra", "mismatch"):
                for rel in d[kind][:10]:
                    print(f"    - {label} {kind}: {rel}")
        if not guard_ok:
            print(f"    - bench 目录白名单破戒:{entries}")
    return result


# --------------------------------------------------------------- --measure
def stage_measure(cid: str, *, bench_name: str | None = None) -> dict:
    bench = BENCH_ROOT / (bench_name or f"hb1-{cid}")
    host, wheel = bench / "host", bench / "wheelhouse"
    if not host.is_dir() or not wheel.is_dir():
        raise RuntimeError(f"{cid} 的 bench 宿主不在 —— 先跑 --hosts")

    extra = MEASURE_EXTRAS.get(cid, {})
    env = offline_env(dict(os.environ))       # 离线是跑出来的,不是声称的
    env.update(extra.get("env", {}))
    recipe = {
        "venv_python": sys.executable,
        "pip": ["install", "-q", "--no-index", "--find-links", str(wheel),
                "-e", "<tree>", "pytest", *extra.get("packages", [])],
        "env_extra": sorted(extra.get("env", {})),
        "pytest": ["-q", "-p", "no:cacheprovider", "--junitxml",
                   "<tmp>/junit.xml"],
    }

    def _not_ready(problem: str) -> dict:
        print(f"[measure] {cid}: NOT_READY —— {problem.splitlines()[0]}")
        return {"passed": None, "failed": None, "skipped": None,
                "failed_nodes": [], "skip_nodes": [], "recipe": recipe,
                "status": "NOT_READY", "problems": [problem]}

    with tempfile.TemporaryDirectory(prefix="rp_hb1_measure_") as td:
        tmp = Path(td)
        tree = tmp / "tree"                   # 副本进 mkdtemp,不污染 bench 原件
        shutil.copytree(host, tree)
        venv = tmp / ".venv"
        r = _run([sys.executable, "-m", "venv", str(venv)],
                 cwd=tmp, env=env, timeout=600)
        if r.returncode != 0:
            return _not_ready("venv 建不起来:" + (r.stdout + r.stderr)[-400:])
        r = _run([str(venv / "bin" / "pip"), "install", "-q", "--no-index",
                  "--find-links", str(wheel), "-e", str(tree), "pytest",
                  *extra.get("packages", [])], cwd=tmp, env=env, timeout=900)
        if r.returncode != 0:
            return _not_ready("离线建环境失败(轮仓不全?):"
                              + (r.stdout + r.stderr)[-400:])
        junit = tmp / "junit.xml"
        _run([str(venv / "bin" / "python"), "-m", "pytest", "-q",
              "-p", "no:cacheprovider", "--junitxml", str(junit)],
             cwd=tree, env=venv_env(venv, env), timeout=1800)
        data = junit.read_bytes() if junit.exists() else b""

    if not data:
        return _not_ready("junitxml 没产出 —— pytest 连收集期都没走到")
    score = score_from_junit(data)            # 分数只出 junit,不读退出码
    verdict = judge_baseline(score)
    baseline = {
        "total": score["total"],
        "passed": score["passed"],
        "failed": len(score["failed_nodes"]),
        "skipped": score["skipped"],
        "failed_nodes": score["failed_nodes"],
        "skip_nodes": score["skipped_nodes"],     # 全列表,如实入档
        "recipe": recipe,
        "status": verdict["status"],
        "problems": verdict["problems"],
    }
    print(f"[measure] {cid}: 总 {score['total']} / 绿 {score['passed']} / "
          f"红 {len(score['failed_nodes'])} / skip {score['skipped']} → "
          f"{verdict['status']}")
    for p in verdict["problems"]:
        print("    -", p)
    return baseline


# -------------------------------------------------------------- --leak-scan
def _scan_tree(root: Path, fps: list[dict]) -> list[dict]:
    """在树里找答案指纹。合并成一条大 alternation 先粗筛(sqlglot 的
    fixtures 是 MB 级文本,逐指纹逐文件搜是平方账),命中再回头定位是哪条。
    每文件最多记一条(与 prepare_host2.leak_scan 同口径)。"""
    combined = re.compile("|".join(f"(?:{f['pattern']})" for f in fps))
    hits: list[dict] = []
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        try:
            body = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not combined.search(body):
            continue
        for fp in fps:
            if re.search(fp["pattern"], body):
                hits.append({"file": f.relative_to(root).as_posix(),
                             "fingerprint": fp["name"]})
                break
    return hits


def stage_leak(cid: str, *, bench_name: str | None = None) -> dict:
    host = BENCH_ROOT / (bench_name or f"hb1-{cid}") / "host"
    if not host.is_dir():
        raise RuntimeError(f"{cid} 的 bench host 不在 —— 先跑 --hosts")
    patch_text = (ARCHIVE / "candidates" / cid / "answer" / "full.patch"
                  ).read_text(encoding="utf-8", errors="replace")
    fps_total = extract_fingerprints(patch_text, _manifest(cid)["test_files"])
    parent_blob = _tree_blob(ARCHIVE / "candidates" / cid / "parent_tree")
    effective, dropped = calibrate_fingerprints(fps_total, parent_blob)

    base = {"fingerprints_total": len(fps_total),
            "calibrated_out": len(dropped),
            "calibrated_out_names": [f["name"] for f in dropped],
            "effective": len(effective)}
    if not effective:
        print(f"[leak] {cid}: 校准后指纹为空 —— 扫描没有牙,不算绿")
        return {**base, "hits": [], "planted_detected": False,
                "clean_zero": False, "selfcheck_ok": False}

    hits = _scan_tree(host, effective)

    # 自证(种植侧)在 mkdtemp 副本上做,bench 原件零写 —— prepare_host2
    # 是种进 HOST 再删,这里 host_guard 白名单更严,干脆不碰。
    with tempfile.TemporaryDirectory(prefix="rp_hb1_leak_") as td:
        twin = Path(td) / "tree"
        shutil.copytree(host, twin)
        (twin / PLANTED_NAME).write_text(
            "\n".join(fp["raw"] for fp in effective[:5]) + "\n",
            encoding="utf-8")
        planted_detected = any(h["file"] == PLANTED_NAME
                               for h in _scan_tree(twin, effective))

    clean_zero = hits == []
    result = {
        **base,
        "hits": hits,
        "planted_detected": planted_detected,   # 种进去必须报中(灵敏度)
        "clean_zero": clean_zero,               # 干净树必须零报(特异度)
        "selfcheck_ok": planted_detected and clean_zero,
    }
    print(f"[leak] {cid}: 指纹 {len(fps_total)} 条,校准剔 {len(dropped)},"
          f"有效 {len(effective)},命中 {len(hits)};"
          f"种植自证 {'报中 ✓' if planted_detected else '**没报 ✗**'},"
          f"干净树 {'零报 ✓' if clean_zero else '**有报 ✗**'}")
    for h in hits[:10]:
        print(f"    - {h['file']}  ({h['fingerprint']})")
    return result


# ------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hosts", action="store_true",
                    help="重构 V + 交叉验证,通过才部署(幂等)")
    ap.add_argument("--measure", action="store_true",
                    help="mkdtemp 副本上离线建 venv 跑回归基线")
    ap.add_argument("--leak-scan", dest="leak_scan", action="store_true",
                    help="校准后答案指纹扫 bench host + 双向自证")
    ap.add_argument("--all", dest="run_all", action="store_true",
                    help="依次 --hosts → --measure → --leak-scan")
    ap.add_argument("--v2", action="store_true",
                    help="只处理 V2_TASKS(构造法 v2 代际);v1 三宿主不动")
    ap.add_argument("--only", action="append", default=None, metavar="KEY",
                    help="只处理指定目标键(v2 用 vid、v1 用 cid;可重复)——"
                         "已锁定的既有宿主不必陪跑重建")
    a = ap.parse_args()

    stages = [name for flag, name in ((a.hosts or a.run_all, "hosts"),
                                      (a.measure or a.run_all, "measure"),
                                      (a.leak_scan or a.run_all, "leak"))
              if flag]
    if not stages:
        ap.error("选一个:--hosts / --measure / --leak-scan / --all")
    if not ARCHIVE.is_dir():
        print(f"封存池不在:{ARCHIVE}", file=sys.stderr)
        return 2

    # 证据单文件、分次累积,但**跨轮覆盖重生成**:第一轮的数字是攻击件
    # 在场时量的,一条不留(round 字段不符即整文件重来)。
    evidence: dict = {}
    if EVIDENCE.exists():
        old = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        if old.get("round") == ROUND:
            evidence = old
    evidence.update({
        "_what": "HB-PCDELTA-1 三 bench 宿主的部署层自证 —— V 树重构交叉验证 "
                 "+ 攻击者残迹留痕 + 回归基线 + 校准泄漏扫描(双向自证)",
        "round": ROUND,
        "round_reason": ROUND_REASON,
        "bytecode_ruling": BYTECODE_RULING,
        "generated_by": "scripts/prepare_hb1_hosts.py",
        "prereg": PREREG,
        "archive": str(ARCHIVE),
        "bench_root": str(BENCH_ROOT),
        "python": sys.version.split()[0],
        "argv": sys.argv,
    })
    evidence.setdefault("invocations", []).append(
        {"argv": sys.argv, "stages": stages, "round": ROUND,
         "utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})

    hosts_sec = evidence.setdefault("hosts", {})
    this_run_ok = True
    targets = ([{"key": t["vid"], "cid": t["cid"], "bench": t["bench"],
                 "law": t["law"]} for t in V2_TASKS]
               if a.v2 else
               [{"key": c, "cid": c, "bench": f"hb1-{c}", "law": "v1"}
                for c in CANDIDATES])
    if a.only:
        unknown = set(a.only) - {t["key"] for t in targets}
        if unknown:
            ap.error(f"--only 含未知目标键:{sorted(unknown)}")
        targets = [t for t in targets if t["key"] in a.only]
    for stage in stages:                       # 阶段为外层:对每个 id 各做一遍
        for t in targets:
            entry = hosts_sec.setdefault(t["key"], {})
            if t["law"] != "v1":               # v2 记录自带谱系,防跨代误读
                entry["candidate_cid"] = t["cid"]
                entry["construction_law"] = t["law"]
            if stage == "hosts":
                res = stage_hosts(t["cid"], bench_name=t["bench"],
                                  law=t["law"])
                entry.update(res)
                this_run_ok &= res["verify_ok"]
            elif stage == "measure":
                res = stage_measure(t["cid"], bench_name=t["bench"])
                entry["baseline"] = res
                this_run_ok &= res["status"] == "READY"
            else:
                res = stage_leak(t["cid"], bench_name=t["bench"])
                entry["leak"] = res
                this_run_ok &= res["selfcheck_ok"] and not res["hits"]

    # 总闸:三宿主三小节全在且全绿才 ok —— 缺一节就还不算就绪。
    def _entry_ok(e: dict) -> bool:
        return (e.get("verify_ok") is True
                and e.get("deployed") is True
                and e.get("baseline", {}).get("status") == "READY"
                and e.get("leak", {}).get("selfcheck_ok") is True
                and e.get("leak", {}).get("hits") == [])

    evidence["ok"] = all(_entry_ok(hosts_sec.get(c, {})) for c in CANDIDATES)

    _guard_write(EVIDENCE)
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2)
                        + "\n", encoding="utf-8")
    print(f"证据:{EVIDENCE}(第 {ROUND} 轮;本次阶段 {stages} "
          f"{'全绿' if this_run_ok else '**有红**'};三宿主总闸 ok="
          f"{evidence['ok']})")
    return 0 if this_run_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
