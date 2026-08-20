"""regression_broken 节点分类学(R3 台账细分,2026-08-21)。

背景(GPT 两批 + E1 复盘,2026-08-21 盘面取证):五发 GPT FAIL 的
final_regression 全部 1150/1150 绿,判死它们的 h2 节点**全部住在出题时
被整文件剥离的测试文件里** —— "回归被砸"这一个桶里其实混着性质完全
不同的几类节点。本脚本把每个 regression_broken 节点分进如下桶:

- ``VISIBLE_TREE``:不属于任何铺入(post)文件 —— 模型可见、可运行的
  回归面上的真砸(final_regression 也应当红);
- ``STRIPPED_OLD_INTACT``:剥离文件内、base 与 post 逐字同的旧测试 ——
  真旧行为回归,但模型无法运行验证(对齐缺口的主体);
- ``STRIPPED_OLD_MODIFIED``:剥离文件内、base 有但 PR 改过的旧测试 ——
  **伪回归警报**:post 版期望的是新行为,保住旧行为反而判死,语义上是
  隐蔽 delta,单列示警(卫生电池若干净不应出现);
- ``STRIPPED_NEW``:剥离文件内、base 没有的 PR 新增测试 —— 非 delta
  ⇒ 按 oracle_hygiene 的枚举律(delta = parent 上恰红的新增集)推定
  green-on-parent:测的是 base 时代就正常的行为;
- ``DELTA_NODE_IN_REGRESSION``:delta 节点出现在回归桶(不应发生,
  仪器警报);
- ``EXTRACTION_FAILED``:post 文件里都找不到该函数 —— fail-closed
  单列,不猜。

**判决零改动**:h2 仍按 regression_broken != [] 判死;本脚本只是台账
侧的读数细分,供解释与后续 R1(base 版留树)决策使用。数字只出脚本:
批报/预注册引用的分类数字都应来自 --json 输出。

用法(证据生成见 docs/evidence/regression_broken_taxonomy/):
    .venv/bin/python scripts/classify_regression_broken.py \
        --task-dir benchmarks/v2/tasks/hb1_sqlglot_8042 \
        --pool-candidate ~/RepoProofArchive/d5-hunt/candidates/sqlglot-8042 \
        --ledger benchmarks/v2/runs.jsonl \
        --batch DQ-GPT-SHIM-1 --batch GPT-H0-E1TOTAL-1 \
        --json out.json

封存池只读:本脚本对 --pool-candidate 只做读取(base 版原文提取),
零写入;证据文件只落节点名与桶别,**不携带任何测试内容**(post 测试
原文属于答案面,不入公开仓)。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- 纯函数核

VISIBLE_TREE = "VISIBLE_TREE"
STRIPPED_OLD_INTACT = "STRIPPED_OLD_INTACT"
STRIPPED_OLD_MODIFIED = "STRIPPED_OLD_MODIFIED"
STRIPPED_NEW = "STRIPPED_NEW"
DELTA_NODE_IN_REGRESSION = "DELTA_NODE_IN_REGRESSION"
EXTRACTION_FAILED = "EXTRACTION_FAILED"


def module_prefix(path: str) -> str:
    """'tests/test_lineage.py' → 'tests.test_lineage'(junit classname 前缀)。"""
    p = path[:-3] if path.endswith(".py") else path
    return p.replace("/", ".")


def node_in_file(node: str, path: str) -> bool:
    """节点归属:classname 等于文件模块名,或以其为前缀再嵌一层类名。"""
    mod = node.split("::")[0]
    prefix = module_prefix(path)
    return mod == prefix or mod.startswith(prefix + ".")


def node_func_name(node: str) -> str:
    """'…::test_a[case-1]' → 'test_a'(剥参数化后缀)。"""
    name = node.split("::")[-1]
    return name.split("[", 1)[0]


def extract_test_source(text: str, name: str) -> str | None:
    """按名字抠出 'def name(...)' 块(含贴身装饰器),到下一个同级或更浅的
    def/class/@ 为止。同名多处取首个(本语料内测试名唯一);抠不到返回
    None —— 调用方 fail-closed。比较用途:尾随空白剥净。
    """
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        stripped = ln.lstrip()
        if not stripped.startswith(f"def {name}("):
            continue
        indent = len(ln) - len(stripped)
        start = i
        while start > 0:  # 贴身装饰器属于函数(PR 改装饰器也算改测试)
            prev = lines[start - 1]
            ps = prev.lstrip()
            if ps.startswith("@") and (len(prev) - len(ps)) == indent:
                start -= 1
            else:
                break
        end = len(lines)
        for j in range(i + 1, len(lines)):
            s2 = lines[j].lstrip()
            if not s2:
                continue
            ind2 = len(lines[j]) - len(s2)
            if ind2 < indent or (ind2 == indent
                                 and s2.startswith(("def ", "class ", "@"))):
                end = j
                break
        return "\n".join(lines[start:end]).rstrip() + "\n"
    return None


def classify_node(node: str, *, delta_nodes: set[str], post_files: list[str],
                  post_text: dict[str, str], base_text: dict[str, str]) -> str:
    """单节点分桶。post_text/base_text:path → 文件原文(base 缺文件时
    以空串占位 —— 整文件都是 PR 新增的情形,函数自然抠不到 → STRIPPED_NEW)。
    """
    if node in delta_nodes:
        return DELTA_NODE_IN_REGRESSION
    homes = [p for p in post_files if node_in_file(node, p)]
    if not homes:
        return VISIBLE_TREE
    path = homes[0]
    name = node_func_name(node)
    post_fn = extract_test_source(post_text.get(path, ""), name)
    if post_fn is None:
        return EXTRACTION_FAILED
    base_fn = extract_test_source(base_text.get(path, ""), name)
    if base_fn is None:
        return STRIPPED_NEW
    return STRIPPED_OLD_INTACT if base_fn == post_fn else STRIPPED_OLD_MODIFIED


_MORE_ITEMS = re.compile(r"Left contains (\d+|one) more items?")


def parse_regression_broken(log_text: str) -> dict:
    """从 oracle_stdout.log 抠 h2 断言消息里的节点列表。

    返回 {nodes, truncated, total_claimed, problem}。语义:
    - h2 未失败(无失败小节)→ nodes=[];
    - 断言消息是 regression_broken[:10] —— 若 'Left contains N more items'
      的 N 与解析条数不符,说明全列表超 10 被截断 → truncated=True,
      调用方不得宣称覆盖完整(fail-closed 提示重跑 oracle 取全列表);
    - 小节在而列表解析不出 → problem 单列,不猜。
    """
    out: dict = {"nodes": [], "truncated": False,
                 "total_claimed": None, "problem": None}
    sec = re.search(r"_+ test_h2_no_regression_broken _+\n(.*?)(?=\n=+ |\n_+ \w+ _+\n|\Z)",
                    log_text, re.S)
    if sec is None:
        if re.search(r"FAILED \S*test_h2_no_regression_broken", log_text):
            out["problem"] = "H2_FAILED_BUT_SECTION_NOT_FOUND"
        return out
    block = sec.group(1)
    buf: list[str] = []
    depth = 0
    started = False
    for ln in block.splitlines():
        if not started:
            idx = ln.find("AssertionError: [")
            if idx < 0:
                continue
            seg = ln[idx + len("AssertionError: "):]
            started = True
        else:
            seg = ln
            if seg.startswith("E"):
                seg = seg[1:].strip()
        buf.append(seg)
        depth += seg.count("[") - seg.count("]")
        if depth == 0:
            break
    if not started or depth != 0:
        out["problem"] = "ASSERT_LIST_UNPARSED"
        return out
    try:
        nodes = ast.literal_eval(" ".join(buf))
    except (ValueError, SyntaxError):
        out["problem"] = "ASSERT_LIST_UNPARSED"
        return out
    if not isinstance(nodes, list):
        out["problem"] = "ASSERT_LIST_UNPARSED"
        return out
    out["nodes"] = [str(n) for n in nodes]
    m = _MORE_ITEMS.search(block)
    if m:
        total = 1 if m.group(1) == "one" else int(m.group(1))
        out["total_claimed"] = total
        out["truncated"] = total != len(out["nodes"])
    return out


# ---------------------------------------------------------------- IO 装配


def load_texts(task_dir: Path, pool_candidate: Path) -> tuple[dict, dict, dict]:
    """manifest + post 原文(任务包物化件)+ base 原文(封存池 parent_tree,
    只读)。base 缺文件 → 空串占位(见 classify_node)。"""
    manifest = json.loads(
        (task_dir / "oracle" / "delta_manifest.json").read_text(encoding="utf-8"))
    post_text: dict[str, str] = {}
    base_text: dict[str, str] = {}
    for item in manifest["post_files"]:
        rel = item["path"]
        post = task_dir / "oracle" / "post_tests" / rel
        post_text[rel] = post.read_text(encoding="utf-8") if post.is_file() else ""
        base = pool_candidate / "parent_tree" / rel
        base_text[rel] = base.read_text(encoding="utf-8") if base.is_file() else ""
    return manifest, post_text, base_text


def classify_run_bundle(bundle: Path, *, manifest: dict,
                        post_text: dict, base_text: dict) -> dict:
    log = bundle / "oracle_stdout.log"
    if not log.is_file():
        return {"problem": "ORACLE_LOG_MISSING", "nodes": [],
                "truncated": False, "taxonomy": {}}
    parsed = parse_regression_broken(log.read_text(encoding="utf-8", errors="replace"))
    taxonomy = {
        n: classify_node(
            n, delta_nodes=set(manifest["delta_nodes"]),
            post_files=[i["path"] for i in manifest["post_files"]],
            post_text=post_text, base_text=base_text)
        for n in parsed["nodes"]
    }
    return {**parsed, "taxonomy": taxonomy}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--task-dir", required=True, type=Path)
    ap.add_argument("--pool-candidate", required=True, type=Path)
    ap.add_argument("--ledger", type=Path,
                    default=Path("benchmarks/v2/runs.jsonl"))
    ap.add_argument("--batch", action="append", default=[],
                    help="按台账批名选发次(可多次);不给则须 --run-bundle")
    ap.add_argument("--run-bundle", action="append", default=[], type=Path,
                    help="直接给 bundle 目录(可多次)")
    ap.add_argument("--json", type=Path, help="结果落盘路径(不给则打印)")
    a = ap.parse_args(argv)

    task_dir = a.task_dir.expanduser()
    manifest, post_text, base_text = load_texts(task_dir, a.pool_candidate.expanduser())

    targets: list[dict] = []          # {run_id, batch, model, verdict, bundle}
    for b in a.run_bundle:
        targets.append({"run_id": b.name, "batch": None, "model": None,
                        "verdict": None, "bundle": b.expanduser()})
    if a.batch:
        for line in a.ledger.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("batch") in a.batch:
                targets.append({
                    "run_id": row["run_id"], "batch": row["batch"],
                    "model": row.get("model"), "verdict": row.get("verdict"),
                    "bundle": Path(row["bundle_path"]).expanduser()})

    runs = []
    counts: dict[str, int] = {}
    node_hist: dict[str, dict] = {}
    for t in targets:
        r = classify_run_bundle(t["bundle"], manifest=manifest,
                                post_text=post_text, base_text=base_text)
        runs.append({k: t[k] for k in ("run_id", "batch", "model", "verdict")}
                    | {k: r[k] for k in ("nodes", "truncated", "problem", "taxonomy")})
        for n, bucket in r["taxonomy"].items():
            counts[bucket] = counts.get(bucket, 0) + 1
            h = node_hist.setdefault(n, {"bucket": bucket, "runs": 0})
            h["runs"] += 1

    out = {
        "_what": ("regression_broken 节点分类学(R3;判决零改动,纯台账细分)。"
                  "桶语义见 scripts/classify_regression_broken.py docstring。"),
        "task_id": manifest.get("task_id") or task_dir.name,
        "delta_nodes": manifest["delta_nodes"],
        "post_files": [i["path"] for i in manifest["post_files"]],
        "runs": runs,
        "summary": {"bucket_counts": counts, "node_histogram": node_hist,
                    "runs_total": len(runs),
                    "runs_with_broken": sum(1 for r in runs if r["nodes"])},
    }
    text = json.dumps(out, ensure_ascii=False, indent=1, sort_keys=False)
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(text + "\n", encoding="utf-8")
        print(f"[classify_regression_broken] {len(runs)} 发 → {a.json}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
