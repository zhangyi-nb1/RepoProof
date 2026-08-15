#!/usr/bin/env python3
"""盲攻测量驱动器 —— 给 held-out 准入判据喂**可复核的**数字。

`heldout_admission.judge` 是纯判官,它自己不量。这里负责量,并保证量出来的
数字经得起复核(判据 B1–B6 冻结在 `tests/test_blind_attack_admission.py`):

    基线:纯净树 + 轮仓离线建 venv → 跑上游套件 → 必须全绿零 skip
      → 攻击:seam 换成攻击者写的那份 → 同 venv 重跑
      → ratio = 攻击后 passed / **基线** total
      → heldout_admission.judge(BlindAttack(...)) → 判决
      → 全套记录(failed_nodes / digests / method / 判决)落
         docs/evidence/heldout_admission/<candidate>.json

形态无关:SEAM-REIMPL 彩排与 post-cutoff delta 猎取用同一套 —— 变的只是
"攻击件替换进树里的方式",量法与判法一个字不变。

用法(彩排实例):
    .venv/bin/python scripts/blind_attack_admission.py \\
        --candidate rehearsal-pagination \\
        --pristine ~/RepoProofArchive/host2/repo \\
        --wheelhouse ~/RepoProofBench/host2-flask-smorest/wheelhouse \\
        --seam-rel src/flask_smorest/pagination.py \\
        --attacked-file <攻击者写完的文件> \\
        --method-file <盲攻协议原文> \\
        [--residual-kinds behavior,boundary_guard]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from repoproof.execution.heldout_admission import BlindAttack, judge  # noqa: E402

EVIDENCE_DIR = REPO / "docs" / "evidence" / "heldout_admission"


# ------------------------------------------------------------------ 计分
def score_from_junit(data: bytes) -> dict:
    """junitxml → {total, passed, skipped, failed_nodes}。

    分数**只**出自这里 —— pytest 退出码不进任何算式(节点名打错、内部错误
    都会非零,拿它当分数是把仪器故障记成测量值)。失败节点名单随分数一起
    出来:它是残差分类的原料,不许省。
    """
    root = ET.fromstring(data.decode("utf-8", errors="replace"))
    total = skipped = 0
    failed_nodes: list[str] = []
    passed_nodes: list[str] = []
    for suite in root.iter("testsuite"):
        for case in suite.iter("testcase"):
            total += 1
            node = f"{case.get('classname', '?')}::{case.get('name', '?')}"
            if case.find("failure") is not None or case.find("error") is not None:
                failed_nodes.append(node)
            elif case.find("skipped") is not None:
                skipped += 1
            else:
                passed_nodes.append(node)
    return {"total": total, "passed": len(passed_nodes), "skipped": skipped,
            "failed_nodes": sorted(failed_nodes),
            "passed_nodes": sorted(passed_nodes)}


def measurement_problems(*, baseline: dict,
                         delta_nodes: frozenset[str] | None = None) -> list[str]:
    """基线这一跑配不配当尺子。不配 → 拒绝测量,不产出 ratio。

    两种形态:
    - 全套件形态(SEAM 彩排):基线必须全绿零 skip;
    - delta 形态(post-cutoff 猎取,`delta_nodes` = PR 新增测试):基线必须
      **恰好** delta 集全红、其余全绿 —— 这同时就是 FAIL_TO_PASS 的实测验证。
      少红 = 该 delta 在 parent 树上就能过(量不到东西);多红 = 旧套件在
      parent 树上就有病(尺子不干净)。
    """
    problems: list[str] = []
    if baseline["total"] <= 0:
        problems.append("基线一条测试都没收集到 —— 没有分母")
    if baseline["skipped"]:
        problems.append(
            f"基线有 {baseline['skipped']} 条 skipped —— oracle 卫生前提被破"
            "(host2 选型时'零 skip'是入选理由,量的时候不能自己破)")
    red = set(baseline["failed_nodes"])
    if delta_nodes is None:
        if red:
            problems.append(
                f"基线不全绿({len(red)} 红,如 {sorted(red)[:5]})—— 纯净树上"
                "就红的套件当不了尺子,任何攻击分数无从归因")
        return problems
    if not delta_nodes:
        problems.append("delta 集为空 —— 没有分母,这个候选量不到东西")
    green_deltas = sorted(set(delta_nodes) - red)
    if green_deltas:
        problems.append(
            f"delta 测试在 parent 树上就绿:{green_deltas} —— "
            "FAIL_TO_PASS 不成立,这些条目量不到新行为")
    extra_red = sorted(red - set(delta_nodes))
    if extra_red:
        problems.append(
            f"基线在 delta 之外还红了 {len(extra_red)} 条(如 {extra_red[:3]})—— "
            "旧套件在 parent 树上就有病,尺子不干净")
    return problems


def build_attack(*, baseline: dict, attacked: dict, method: str,
                 residual_kinds: frozenset[str],
                 delta_nodes: frozenset[str] | None = None) -> BlindAttack:
    """全套件形态:分母 = **基线** total —— 攻击件把收集期打崩时,攻击后
    junit 的节点数会缩水,拿它当分母等于让被测方决定分母(U3 的老病)。

    delta 形态:分母 = delta 集大小,分子 = 攻击后 delta 集里**确实转绿**的
    条数(按 passed_nodes 交集数 —— 收集期崩掉的 delta 节点既不红也不绿,
    不算分)。旧套件的绿不进分子:那是回归面,不是能力面。
    """
    if delta_nodes is None:
        return BlindAttack(total=baseline["total"], passed=attacked["passed"],
                           method=method, residual_kinds=residual_kinds)
    won = delta_nodes & set(attacked.get("passed_nodes", ()))
    return BlindAttack(total=len(delta_nodes), passed=len(won),
                       method=method, residual_kinds=residual_kinds)


def build_record(*, candidate: str, baseline: dict, attacked: dict, method: str,
                 residual_kinds: frozenset[str], digests: dict,
                 delta_nodes: frozenset[str] | None = None) -> dict:
    if not method.strip():
        raise ValueError("method 为空 —— 分数将无从复核,拒绝出记录")
    attack = build_attack(baseline=baseline, attacked=attacked, method=method,
                          residual_kinds=residual_kinds, delta_nodes=delta_nodes)
    verdict = judge(attack)
    regression_broken = (sorted(set(attacked["failed_nodes"]) - delta_nodes)
                        if delta_nodes else [])
    return {
        "_what": "一发盲攻的测量记录 —— held-out 准入判据的输入与判决",
        "candidate": candidate,
        "mode": "delta" if delta_nodes else "full-suite",
        "baseline": {"total": baseline["total"], "passed": baseline["passed"],
                     "skipped": baseline["skipped"]},
        "delta_nodes": sorted(delta_nodes) if delta_nodes else [],
        "attacked_passed": attack.passed,
        "ratio": attack.ratio,
        "failed_nodes": attacked["failed_nodes"],
        # 攻击件砸了旧套件 → 单列,不掺进 ratio(掺进去的话,一个把回归面
        # 打红的烂攻击会显得"恰好没打满",把判死线搅浑)
        "regression_broken": regression_broken,
        "residual_kinds": sorted(residual_kinds),
        "method": method,
        "digests": digests,
        "verdict": {"ok": verdict.ok, "reasons": list(verdict.reasons)},
    }


# ------------------------------------------------------------------ 执行
def offline_env(base: dict | None = None) -> dict:
    """离线是跑出来的,不是声称的:任何漏网联网当场撞死端口。"""
    env = dict(base if base is not None else {})
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        env[k] = "http://127.0.0.1:9"
    env["PIP_NO_INDEX"] = "1"
    return env


def _sha256_file(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def _digest_tree(root: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(root.rglob("*")):
        if f.is_file():
            h.update(f.relative_to(root).as_posix().encode())
            h.update(f.read_bytes())
    return "sha256:" + h.hexdigest()


def _run(argv: list[str], *, cwd: Path, env: dict, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                          text=True, timeout=timeout)


def _pytest_junit(venv: Path, tree: Path, env: dict) -> bytes:
    xml = tree / "_rp_admission_junit.xml"
    xml.unlink(missing_ok=True)
    _run([str(venv / "bin" / "python"), "-m", "pytest", "-q",
          "-p", "no:cacheprovider", "--junitxml", str(xml)],
         cwd=tree, env=env)
    data = xml.read_bytes() if xml.exists() else b""
    xml.unlink(missing_ok=True)
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--pristine", required=True, help="纯净树(含上游自带测试)")
    ap.add_argument("--wheelhouse", required=True)
    ap.add_argument("--seam-rel", required=True, help="被攻击文件在树内的相对路径")
    ap.add_argument("--attacked-file", required=True, help="攻击者写完的那份文件")
    ap.add_argument("--method-file", required=True, help="盲攻协议原文(纯文本)")
    ap.add_argument("--extras", default="",
                    help="被测包自己的 extras 名(如 tests)—— 测试侧依赖用上游"
                         "自己的声明装,不猜(彩排实测:漏装 PyYAML → 基线拒测)")
    ap.add_argument("--residual-kinds", default="",
                    help="残差分类标签,逗号分隔;分类之前先跑一遍拿 failed_nodes")
    ap.add_argument("--out-dir", default=str(EVIDENCE_DIR))
    a = ap.parse_args()

    pristine = Path(a.pristine).expanduser()
    attacked_file = Path(a.attacked_file).expanduser()
    method = Path(a.method_file).expanduser().read_text(encoding="utf-8")
    kinds = frozenset(k.strip() for k in a.residual_kinds.split(",") if k.strip())
    env = offline_env(dict(__import__("os").environ))

    with tempfile.TemporaryDirectory(prefix="rp_admission_") as td:
        tree = Path(td) / "tree"
        shutil.copytree(pristine, tree,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
        venv = Path(td) / "venv"
        _run([sys.executable, "-m", "venv", str(venv)], cwd=Path(td), env=env)
        target = f"{tree}[{a.extras}]" if a.extras else str(tree)
        r = _run([str(venv / "bin" / "pip"), "install", "-q", "--no-index",
                  "--find-links", str(Path(a.wheelhouse).expanduser()),
                  "-e", target, "pytest"], cwd=Path(td), env=env)
        if r.returncode != 0:
            print("离线建环境失败(轮仓不全?):\n" + (r.stdout + r.stderr)[-600:],
                  file=sys.stderr)
            return 2

        baseline = score_from_junit(_pytest_junit(venv, tree, env))
        problems = measurement_problems(baseline=baseline)
        if problems:
            print("拒绝测量 —— 基线不配当尺子:", file=sys.stderr)
            for p in problems:
                print("  -", p, file=sys.stderr)
            return 2
        print(f"基线:{baseline['passed']}/{baseline['total']} 全绿零 skip ✓")

        digests = {"pristine_tree": _digest_tree(tree),
                   "attacked_file": _sha256_file(attacked_file)}
        shutil.copyfile(attacked_file, tree / a.seam_rel)
        attacked = score_from_junit(_pytest_junit(venv, tree, env))

    record = build_record(candidate=a.candidate, baseline=baseline,
                          attacked=attacked, method=method,
                          residual_kinds=kinds, digests=digests)
    out_dir = Path(a.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{a.candidate}.json"
    dest.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")

    v = record["verdict"]
    print(f"盲攻:{record['attacked_passed']}/{baseline['total']} "
          f"= {record['ratio']:.1%};失败 {len(record['failed_nodes'])} 条")
    print("判决:" + ("**准入**" if v["ok"] else "**判死**"))
    for reason in v["reasons"]:
        print("  -", reason)
    print(f"记录:{dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
