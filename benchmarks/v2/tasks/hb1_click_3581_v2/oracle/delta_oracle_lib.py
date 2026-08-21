"""post-cutoff delta 隐藏 oracle 的驱动引擎(HB-PCDELTA-1,2026-08-16)。

**这是纯接线**:判据内容 = 上游同 PR 自带的测试原文(D1 严口径,一个字
不改);本文件只负责把它们铺进被判的树、跑一遍、按冻结节点集读结果、
再把树还原。设计约束:

1. **stdlib-only,自包含**。oracle 在会话 venv(click/sqlglot 的 venv)里
   跑,repoproof 不在那里 —— 所以本文件被逐字节复制进每个任务包的
   oracle/ 目录,`tests/test_hb_task_packages.py` 钉死三份副本与本源相等
   (副本漂移 = 判卷器不一致,必须炸在测试里而不是发次里)。
2. **答案不入公开仓**:上游 post 测试文件由 `prepare_hb1_hosts.py
   --materialize` 从封存池物化(gitignore),manifest 只载 sha256。缺料/
   错料一律 fail-closed 拒判(H0 红,归 HARNESS_FAILURE)—— "没料却绿"
   正是量具第 4 次被 fail-closed 救的那类病。
3. **量具面守卫**(H1):tests/ 子树 + 根 conftest.py + pytest 配置文件
   (pyproject.toml/setup.cfg/setup.py/pytest.ini/tox.ini)+ 解释器启动面
   (sitecustomize.py/usercustomize.py)在 oracle 起跑时必须与出题时逐字节
   一致。守的不只是"改测试":一个根 conftest.py 的
   pytest_runtest_makereport 猴补丁能让全套件假绿 —— delta 内容藏得住,
   pytest 的扩展点藏不住;sitecustomize 更早,在解释器起点就能改写读数。
   这些路径在契约 forbidden 里**先教**(#33),此处才有资格杀。判卷子进程
   同时做 env 净化 + 收集面限定(见 run_delta_oracle 内注释),使加载面
   与守卫面重合。
4. **判后还原**:oracle 之后还要跑回归(_run_regression 在 oracle 之后),
   铺进去的 delta 文件必须撤干净,还原以 digest 复核,不以"我删了"为准。
   构造法 v2(R1,2026-08-21):manifest 带 base_files 的路径按
   save→覆写→放回 lay 前字节;无该键的 v1 manifest 语义字面不变
   (LAY_TARGET_OCCUPIED 只对 v1 生效)。单一 master、manifest 驱动分支,
   三份副本钉不破。

结局语义(供 hb_batch_criteria 与人读):
  - test_h0_* 红  → 判卷器缺料,HARNESS_FAILURE,不计模型;其中 SUITE_TIMEOUT
    在 hb_batch_criteria 单列归因(agent 代码能拖慢套件,不许洗进 harness
    连败计数去撞停批线 1);
  - test_h1_* 红  → 量具面被动过,attribution=agent(TESTS_MODIFIED /
    GUARDED_FILE_MODIFIED / LAY_TARGET_OCCUPIED);
  - test_delta_node[...] 红 → 该 delta 节点未转绿(缺席=fail-closed 红);
  - test_no_regression_broken 红 → delta 之外有红(在铺入 post 测试的
    全套件口径下),对应 J3 的 REGRESSION_BROKEN 一侧。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

# 根级量具面:存在与否、内容为何,都以出题时刻为准(ABSENT 也是一种钉死)。
# sitecustomize/usercustomize(2026-08-16 可搬运性审查 blocking [1a]):解释器
# 启动期自动 import,先于 pytest 一切配置 —— 根下放一个就能在判卷进程里改写
# 任意读数。守卫按存在性钉死(三宿主出题态均 ABSENT);注入通道另在 env 净化
# 处关死(判卷进程不带 PYTHONPATH,`-m` 的 cwd 注入晚于 site 处理,够不着)。
GUARDED_ROOT_FILES = (
    "conftest.py", "pyproject.toml", "setup.cfg", "setup.py",
    "pytest.ini", "tox.ini", "sitecustomize.py", "usercustomize.py",
)
ABSENT = "ABSENT"
_SKIP_DIRS = {"__pycache__", ".pytest_cache"}


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def tests_tree_digest(host: Path, subdir: str = "tests") -> str:
    """tests/ 子树摘要:排序 relpath + 逐文件 sha256,跳过字节码缓存。"""
    root = host / subdir
    lines: list[str] = []
    if root.is_dir():
        for f in sorted(root.rglob("*")):
            if not f.is_file() or f.suffix == ".pyc":
                continue
            if any(part in _SKIP_DIRS for part in f.relative_to(root).parts):
                continue
            lines.append(f"{f.relative_to(root).as_posix()}\0{_sha256(f)}")
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def guarded_root_state(host: Path) -> dict[str, str]:
    return {name: (_sha256(host / name) if (host / name).is_file() else ABSENT)
            for name in GUARDED_ROOT_FILES}


def load_manifest(oracle_dir: Path) -> dict:
    return json.loads((oracle_dir / "delta_manifest.json").read_text(encoding="utf-8"))


def materialization_problems(oracle_dir: Path, manifest: dict) -> list[str]:
    """H0 前半:封存料齐不齐、对不对。缺一个字节都拒判。"""
    problems: list[str] = []
    for item in manifest["post_files"]:
        f = oracle_dir / "post_tests" / item["path"]
        if not f.is_file():
            problems.append(f"MATERIALIZATION_MISSING:{item['path']}"
                            "(跑 scripts/prepare_hb1_hosts.py --materialize)")
        elif _sha256(f) != item["sha256"]:
            problems.append(f"MATERIALIZATION_DIGEST_MISMATCH:{item['path']}")
    return problems


def instrument_problems(host: Path, manifest: dict) -> list[str]:
    """H1:量具面守卫。tests/ 子树 + 根级 pytest 扩展点逐字节比对出题态。

    守的子树 = 判卷收集的子树(同取 manifest["tests_subdir"])—— 两者必须是
    同一个值,否则"守 A 收 B"就是审查 [1b] 那个洞的一般形。
    """
    problems: list[str] = []
    now = tests_tree_digest(host, manifest.get("tests_subdir", "tests"))
    if now != manifest["tests_tree_sha256"]:
        problems.append("TESTS_TREE_MODIFIED:tests/ 与出题态不一致")
    want = manifest["guarded_root_files"]
    got = guarded_root_state(host)
    for name, expect in want.items():
        if got.get(name, ABSENT) != expect:
            problems.append(f"GUARDED_FILE_MODIFIED:{name}"
                            f"(出题态 {expect[:12]},现 {got.get(name, ABSENT)[:12]})")
    return problems


def _parse_junit(xml_path: Path) -> dict:
    """与 blind_attack_admission.score_from_junit 同构:节点 = classname::name,
    有 failure/error 记红、有 skipped 记 skip,退出码不进算式。"""
    root = ET.fromstring(xml_path.read_text(encoding="utf-8"))
    passed, failed, skipped = set(), set(), set()
    for case in root.iter("testcase"):
        node = f"{case.get('classname')}::{case.get('name')}"
        if case.find("failure") is not None or case.find("error") is not None:
            failed.add(node)
        elif case.find("skipped") is not None:
            skipped.add(node)
        else:
            passed.add(node)
    return {"passed": passed, "failed": failed, "skipped": skipped}


def run_delta_oracle(oracle_dir: Path, host: Path) -> dict:
    """一次判卷:守卫 → 铺 post 测试 → 子进程 pytest → 按冻结节点集读 → 还原。

    返回字典;所有判断都出自这里的机器读数,pytest 包装层只做断言转述。
    """
    oracle_dir, host = Path(oracle_dir), Path(host)
    manifest = load_manifest(oracle_dir)
    out: dict = {
        "problems": materialization_problems(oracle_dir, manifest),
        "instrument_problems": instrument_problems(host, manifest),
        "delta_nodes": list(manifest["delta_nodes"]),
        "passed_nodes": set(), "failed_nodes": set(), "skipped_nodes": set(),
        "regression_broken": [], "node_detail": {},
        "restored_ok": True,
    }
    if out["problems"]:
        return out                      # 缺料拒判(fail-closed),树未被动过

    tests_subdir = manifest.get("tests_subdir", "tests")
    pre_digest = tests_tree_digest(host, tests_subdir)
    base_paths = {b["path"] for b in manifest.get("base_files", ())}
    laid: list[Path] = []
    saved: dict[Path, bytes] = {}       # v2:lay 前字节,判后原样放回
    try:
        for item in manifest["post_files"]:
            src = oracle_dir / "post_tests" / item["path"]
            dst = host / item["path"]
            if item["path"] in base_paths:
                # 构造法 v2(R1,2026-08-21):base 版测试文件留树,落点在场
                # 是应然 —— save 当前字节(不管是不是 base:agent 若改过,
                # H1 的 tests_tree 摘要已红,这里照判照还原,归因不倒挂),
                # 判后放回的是 **lay 前态**而非 base,pre/post digest 复核
                # 语义因此不变。落点缺席 = agent 删了量具面文件,记 h1 后
                # 照铺(判卷不因删除而失明),finally 撤走恢复缺席态。
                if dst.is_file():
                    saved[dst] = dst.read_bytes()
                elif dst.exists():
                    out["instrument_problems"].append(
                        f"LAY_TARGET_OCCUPIED:{item['path']}(非常规文件占位)")
                    return out
                else:
                    out["instrument_problems"].append(
                        f"BASE_FILE_MISSING:{item['path']}")
            elif dst.exists():
                # v1:出题剥离过的路径上不该有文件;有 = agent 写了同名文件。
                # 挂 instrument 桶(h1):这是 agent 动了量具面,不是判卷器
                # 故障 —— 挂 problems(h0)会让归因倒挂成 HARNESS_FAILURE
                # (审查 should-fix:h0 优先级高于 h1)。不覆盖 agent 的
                # 文件,直接拒铺拒跑。
                out["instrument_problems"].append(
                    f"LAY_TARGET_OCCUPIED:{item['path']}")
                return out
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            laid.append(dst)

        with tempfile.TemporaryDirectory() as td:
            xml = Path(td) / "junit.xml"
            env = dict(**__import__("os").environ)
            venv_bin = str(Path(sys.executable).parent)
            env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"   # B10:裸 python 子进程
            # env 净化(审查 blocking [1a] 的注入通道):外层 _run_oracle 注的
            # PYTHONPATH=<host> 若被继承,宿主根就在 site 处理时刻上了 sys.path,
            # 根下 sitecustomize.py 会被自动 import —— 判卷读数在解释器起点就
            # 可被改写。判卷子进程一律裸跑:剥 PYTHONPATH/PYTHONSTARTUP,禁
            # user-site(usercustomize 同型通道)。宿主包经 .venv 安装或 cwd
            # 可达,均不依赖 PYTHONPATH。
            for k in ("PYTHONPATH", "PYTHONSTARTUP"):
                env.pop(k, None)
            env["PYTHONNOUSERSITE"] = "1"
            # 收集面限定(审查 blocking [1b]):裸 `pytest` 收整棵树,任何新建
            # 目录里的 conftest.py 都会被加载,pytest_configure 注册的全局插件
            # 不受目录过滤约束(sqlglot 无 testpaths,click 恰好被 testpaths
            # 救了)。限定到冻结的 tests 子树:根 conftest 与 tests/ 内 conftest
            # 都在 H1 守卫下,收集限定后加载面 = 守卫面,一寸不多。
            try:
                subprocess.run(
                    [sys.executable, "-m", "pytest", tests_subdir, "-q",
                     "-p", "no:cacheprovider", "--junitxml", str(xml)],
                    cwd=host, env=env, capture_output=True,
                    timeout=int(manifest.get("suite_timeout_s", 600)), check=False)
            except subprocess.TimeoutExpired:
                out["problems"].append("SUITE_TIMEOUT:判卷套件超时,拒判")
                return out
            if not xml.is_file():
                out["problems"].append("JUNIT_MISSING:套件没产出 junitxml,拒判"
                                       "(收集期崩溃另见 stderr)")
                return out
            parsed = _parse_junit(xml)

        out["passed_nodes"] = parsed["passed"]
        out["failed_nodes"] = parsed["failed"]
        out["skipped_nodes"] = parsed["skipped"]
        delta = set(manifest["delta_nodes"])
        for node in manifest["delta_nodes"]:
            if node in parsed["passed"]:
                out["node_detail"][node] = "PASSED"
            elif node in parsed["failed"]:
                out["node_detail"][node] = "FAILED"
            elif node in parsed["skipped"]:
                out["node_detail"][node] = "SKIPPED(delta 节点无条件判卷,skip=红)"
            else:
                out["node_detail"][node] = ("NODE_MISSING(junitxml 里两头不见 —— "
                                            "fail-closed 判红,常见于收集中断)")
        out["regression_broken"] = sorted(parsed["failed"] - delta)
        return out
    finally:
        for f in laid:
            if f in saved:
                f.write_bytes(saved[f])         # v2:放回 lay 前字节
            else:
                f.unlink(missing_ok=True)
        for f in laid:                          # 清铺入文件产生的空目录与缓存
            d = f.parent
            pyc = d / "__pycache__"
            if pyc.is_dir():
                import shutil as _sh
                _sh.rmtree(pyc, ignore_errors=True)
            try:
                if d != host and not any(d.iterdir()):
                    d.rmdir()
            except OSError:
                pass
        post = tests_tree_digest(host, tests_subdir)
        if post != pre_digest:
            out["restored_ok"] = False          # 还原失败必须可见:回归在后面跑
