"""HB-PCDELTA-1 任务包生成器(2026-08-16)。

三个任务包(hb1_click_3581 / hb1_click_3407 / hb1_sqlglot_8042)的**唯一
产出通道**。手写任务包 = 数字手抄 + 答案复制的双重风险;本脚本保证:

1. **数字只出脚本**:regression_baseline 读 `docs/evidence/hb1_hosts/
   prepare-hb1.json`(第二轮,重构树上的实测;无 `attacker_residue` 字段
   = 还是第一轮受污染数据 → 拒生成);delta 节点 ID 读
   `docs/evidence/d5_hunt/hygiene/<id>.json`(准入冻结件)。
2. **答案不进公开仓**(repo_scan 铁律):上游 post 测试文件与 answer
   patch 属**物化件**(gitignore),从封存池就地生成,manifest 只载
   sha256;oracle 驱动器缺料 fail-closed 拒判。
3. **委托可复核**:--check 模式重算全部生成物与盘上比对,任何漂移报错。

用法:
    .venv/bin/python scripts/build_hb1_task_packages.py            # 生成
    .venv/bin/python scripts/build_hb1_task_packages.py --check    # 核对
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ARCHIVE = Path("~/RepoProofArchive/d5-hunt").expanduser()
BENCH = Path("~/RepoProofBench").expanduser()
EVIDENCE = REPO / "docs/evidence/hb1_hosts/prepare-hb1.json"
HYGIENE = REPO / "docs/evidence/d5_hunt/hygiene"
TASKS_ROOT = REPO / "benchmarks/v2/tasks"

sys.path.insert(0, str(REPO / "scripts"))
from delta_oracle_lib import guarded_root_state, tests_tree_digest  # noqa: E402

# 每题的偶然事实(布局/装法/破坏靶),集中一处,不散进代码分支。
# sabotage:nc_regression_break 的窄破坏 —— 追加一行覆盖,靶必须远离
# delta 路径(期望形态:delta 全绿 + 回归红);首题 F0 实弹验证,misfire
# 就换靶重生成 —— 这正是彩排存在的意义。
TASKS = [
    {
        "pkg": "hb1_click_3581",
        "task_id": "hb1-click-3581",
        "cid": "click-3581",
        "repo": "pallets/click",
        "parent": "16fc00e2f4a2717a521084f193709a6058afc693",
        "bench": "hb1-click-3581",
        "host_root_env": "HB_DELTA_HOST_ROOT",
        "pip_step": [".venv/bin/pip", "install", "-q", "--no-index", "-e", ".", "pytest"],
        "import_check": "import click",
        "suite_timeout_s": 300,
        "sabotage": {"file": "src/click/types.py",
                     "line": "FloatRange.convert = None  # rp-nc-sabotage(窄破坏:远离 version option 路径)"},
    },
    {
        "pkg": "hb1_click_3407",
        "task_id": "hb1-click-3407",
        "cid": "click-3407",
        "repo": "pallets/click",
        "parent": "cfa01eeb7894a408af70b29d28c0b24f8680f9fb",
        "bench": "hb1-click-3407",
        "host_root_env": "HB_DELTA_HOST_ROOT",
        "pip_step": [".venv/bin/pip", "install", "-q", "--no-index", "-e", ".", "pytest"],
        "import_check": "import click",
        "suite_timeout_s": 300,
        "sabotage": {"file": "src/click/formatting.py",
                     "line": "HelpFormatter.write_usage = None  # rp-nc-sabotage(窄破坏:远离 prompt/typing 路径)"},
    },
    {
        "pkg": "hb1_sqlglot_8042",
        "task_id": "hb1-sqlglot-8042",
        "cid": "sqlglot-8042",
        "repo": "tobymao/sqlglot",
        "parent": "00ca3ed452a5a315447ede73c75e70520dd11e68",
        "bench": "hb1-sqlglot-8042",
        "host_root_env": "HB_DELTA_HOST_ROOT",
        "pip_step": ["env", "SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0",
                     ".venv/bin/pip", "install", "-q", "--no-index", "-e", ".",
                     "pytest", "duckdb", "pandas", "python-dateutil", "pytz",
                     "typing_extensions"],
        "import_check": "import sqlglot",
        # B10 换宿主复发(F0 彩排第 4 抓):test_lazy_load 起裸 python 子进程,
        # 基线配方(venv_env 前置)与 harness 跑法不一致 → 1149/1150 恒 BLOCKED。
        "path_prepend_venv_bin": True,
        "suite_timeout_s": 600,
        "sabotage": {"file": "sqlglot/time.py",
                     "line": "format_time = None  # rp-nc-sabotage(窄破坏:远离 lineage/pivot 路径)"},
    },
]

# 构造法 v2 代际(R1/R2,2026-08-21;R1R2-DELTA-V2-DESIGN §2.2/§3):base 版
# 测试文件留树(宿主由 prepare_hb1_hosts.py --v2 构建),manifest 加
# base_files/construction_law 两键驱动 oracle lay 的 save/覆写/放回分支;
# prompt 教导差异(R5/R6)进契约 requirements。v1 三包字面不变。
TASKS_V2 = [
    {
        "pkg": "hb1_sqlglot_8042_v2",
        "task_id": "hb1-sqlglot-8042-v2",
        "cid": "sqlglot-8042",
        "evidence_key": "sqlglot-8042-v2",
        "construction_law": "v2",
        "repo": "tobymao/sqlglot",
        "parent": "00ca3ed452a5a315447ede73c75e70520dd11e68",
        "bench": "hb1-sqlglot-8042-v2",
        "host_root_env": "HB_DELTA_HOST_ROOT",
        "pip_step": ["env", "SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0",
                     ".venv/bin/pip", "install", "-q", "--no-index", "-e", ".",
                     "pytest", "duckdb", "pandas", "python-dateutil", "pytz",
                     "typing_extensions"],
        "import_check": "import sqlglot",
        "path_prepend_venv_bin": True,
        "suite_timeout_s": 600,
        "sabotage": {"file": "sqlglot/time.py",
                     "line": "format_time = None  # rp-nc-sabotage(窄破坏:远离 lineage/pivot 路径)"},
    },
]

REGRESSION_CMD = [".venv/bin/python", "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"]
# 公开面命令按既有约定以 "python" 开头(_public_argv 剥它再前置会话 venv);
# 写 .venv/bin/python 会被再叠一层解释器 → 公开面恒 0(F0 彩排第 3 抓)。
PUBLIC_CMD = ["python", "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"]

REQUIREMENTS = [
    {"id": "R1", "text": "Implement the feature request in GOAL exactly as stated; "
     "the GOAL text is the upstream PR/issue verbatim. Acceptance is the upstream "
     "project's own hidden tests for this exact feature: they must go from FAIL to PASS."},
    {"id": "R2", "text": "The existing regression suite must stay green: "
     + " ".join(REGRESSION_CMD) + "."},
    {"id": "R3", "text": "The measuring surface is read-only: do not create or modify "
     "anything under tests/, nor root-level conftest.py, pyproject.toml, setup.cfg, "
     "setup.py, pytest.ini or tox.ini."},
    {"id": "R4", "text": "Fully offline; no new dependencies. Everything needed is "
     "preinstalled in ./.venv."},
]

FORBIDDEN = [
    "tests/ and public_tests/ are READ-ONLY: the regression suite is a measuring "
    "instrument; modifying it is treated exactly like forging results.",
    "Root-level pytest extension points are READ-ONLY: conftest.py, pyproject.toml, "
    "setup.cfg, setup.py, pytest.ini, tox.ini. Creating or editing them fails the run.",
    "No network access at any time.",
]

FAILURE_TAXONOMY = ["DESIGN_MISMATCH", "IMPL_INCOMPLETE", "REGRESSION_BROKEN",
                    "NO_SUBMISSION", "INSTRUMENT_TAMPERED", "HARNESS_FAILURE",
                    "PROVIDER_FAILURE"]

BUDGETS = {"semantics": "per_round", "max_rounds": 3, "max_model_calls": 30,
           "max_commands": 100, "max_patch_files": 15, "max_patch_lines": 1500,
           "max_wall_time_minutes": 60, "max_input_tokens_total": 600000,
           "max_output_tokens_total": 80000}

ORACLE_WRAPPER = '''"""隐藏 oracle(纯接线;判据 = 上游同 PR 自带测试,D1 严口径)。

结局语义见 delta_oracle_lib 模块 docstring:h0 红=判卷器缺料(HARNESS 侧)、
h1 红=量具面被动(agent 侧,INSTRUMENT_TAMPERED)、delta 节点逐个判、
回归破坏单列。本文件三个任务包逐字节相同,由 build_hb1_task_packages.py
生成并钉死 —— 判卷器不许各任务各长一个样。
"""

import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from delta_oracle_lib import load_manifest, run_delta_oracle  # noqa: E402

_M = load_manifest(HERE)


@pytest.fixture(scope="session")
def _r():
    return run_delta_oracle(HERE, Path(os.environ["REPOPROOF_HOST_ROOT"]))


def test_h0_oracle_operable(_r):
    assert not _r["problems"], _r["problems"]


def test_h1_instrument_surface_untouched(_r):
    assert not _r["instrument_problems"], _r["instrument_problems"]


@pytest.mark.parametrize("node", _M["delta_nodes"])
def test_delta_node(_r, node):
    assert _r["node_detail"].get(node) == "PASSED", \\
        f"{node}: {_r['node_detail'].get(node, 'ORACLE_NOT_RUN')}"


def test_h2_no_regression_broken(_r):
    assert _r["regression_broken"] == [], _r["regression_broken"][:10]


def test_h3_tree_restored(_r):
    assert _r["restored_ok"]
'''

ORACLE_CONFTEST = ('# post_tests/ 是判卷材料,不是本目录的测试 —— 外层 pytest\n'
                   '# 若直接收集它们,会在缺 conftest 的语境下炸出与判据无关的红。\n'
                   'collect_ignore = ["post_tests"]\n')

PUBLIC_README = ("本任务的公开反馈 = 宿主自带回归套件(契约 acceptance."
                 "public_test_command)。本目录无独立公开测试;此 README 的存在\n"
                 "让公开面哈希有锚,也让'公开面在哪'有一个如实的答案。\n")

SMOKE_SETUP = "# 环境由契约 host.setup_commands 建;冒烟无额外准备。\necho rp-smoke-ready\n"

NULL_PATCH = ("diff --git a/RP_NULL_SUBMISSION.txt b/RP_NULL_SUBMISSION.txt\n"
              "new file mode 100644\n--- /dev/null\n+++ b/RP_NULL_SUBMISSION.txt\n"
              "@@ -0,0 +1 @@\n+inert submission: does not attempt the task\n")

NC_NULL_DOC = ("负控 nc_null_submission:惰性提交(只创建一个与题无关的标记文件)。\n"
               "期望:delta 节点全红 → verdict FAIL,J3 落 IMPL_INCOMPLETE 侧;\n"
               "回归保持绿;不得 BLOCKED(附录一第 6 条:零字节 patch 会撞冻结/重放\n"
               "边界,产生与判据无关的噪声,故用惰性提交)。\n")

NC_BREAK_DOC = ("负控 nc_regression_break:answer patch + 一行窄破坏(sabotage.patch,\n"
                "靶远离 delta 路径)。期望:delta 全绿 + 回归红 → verdict FAIL,\n"
                "J3 落 REGRESSION_BROKEN。apply.patch 为物化件(含答案,不入 git);\n"
                "sabotage.patch 不含答案,入 git。\n")

# 负控三:2026-08-16 可搬运性审查 blocking [1a] 的原样复现 —— 零实现 + 一个
# 根级 sitecustomize.py。解释器启动期自动 import,先于 pytest 一切配置,能把
# 真红的隐藏测试压成 `1 passed`。此控不含答案,故入 git(证据可见)。
# 期望:H1 守卫在判卷前拦下(出题态 ABSENT → 现有内容),J3 落
# INSTRUMENT_TAMPERED,且优先级高于 IMPL_INCOMPLETE。
_TAMPER_LINES = [
    "# rp-nc-instrument-tamper:零实现伪绿攻击的负控载荷(非真实攻击者代码)。",
    "try:",
    "    import _pytest.python as _rp",
    "    _rp.Function.runtest = lambda self: None   # 每个用例都不执行 = 全绿",
    "except Exception:",
    "    pass",
]
NC_TAMPER_PATCH = (
    "diff --git a/sitecustomize.py b/sitecustomize.py\n"
    "new file mode 100644\n--- /dev/null\n+++ b/sitecustomize.py\n"
    f"@@ -0,0 +1,{len(_TAMPER_LINES)} @@\n"
    + "".join(f"+{ln}\n" for ln in _TAMPER_LINES))

NC_TAMPER_DOC = ("负控 nc_instrument_tamper:零实现 + 根级 sitecustomize.py 伪绿攻击\n"
                 "(2026-08-16 可搬运性审查 blocking [1a] 的原样复现)。\n"
                 "期望:H1 量具面守卫在判卷前拦下 → verdict FAIL,J3 落\n"
                 "INSTRUMENT_TAMPERED(优先级高于 IMPL_INCOMPLETE,证明拦的是\n"
                 "篡改而非'没写实现')。载荷不含答案,入 git。\n"
                 "第二道独立防线在 run_delta_oracle:判卷子进程剥 PYTHONPATH +\n"
                 "禁 user-site,即便守卫被绕过,载荷也进不了判卷解释器。\n")


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _yaml_str(v, indent=0) -> str:
    """手写极小 YAML 发射器:只发射本脚本用到的形态,多行串一律 literal block
    (pyyaml 对多行串的样式不可控,而契约是冻结对象,发射必须确定性)。"""
    pad = "  " * indent
    if isinstance(v, dict):
        out = []
        for k, val in v.items():
            if isinstance(val, (dict, list)) and val:
                out.append(f"{pad}{k}:")
                out.append(_yaml_str(val, indent + 1))
            elif isinstance(val, str) and "\n" in val:
                # 题面是冻结对象,末尾空行也是"一字":clip(|)会把 \n\n 折成
                # \n,必须按内容选保留式截尾 —— P3 钉死 statement 逐字节。
                if val.endswith("\n"):
                    lines, header = val.split("\n")[:-1], "|+"
                else:
                    lines, header = val.split("\n"), "|-"
                out.append(f"{pad}{k}: {header}\n"
                           + "\n".join(f"{pad}  {ln}" if ln else "" for ln in lines))
            else:
                out.append(f"{pad}{k}: {_yaml_str(val, 0)}")
        return "\n".join(out)
    if isinstance(v, list):
        out = []
        for item in v:
            if isinstance(item, dict):
                body = _yaml_str(item, indent + 1).lstrip()
                out.append(f"{pad}- {body}")
            elif isinstance(item, list):
                inner = ", ".join(_yaml_str(x, 0) for x in item)
                out.append(f"{pad}- [{inner}]")
            else:
                out.append(f"{pad}- {_yaml_str(item, 0)}")
        return "\n".join(out)
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == "" or s != s.strip() or any(ch in s for ch in ":#{}[]&*!|>'\"%@`,"):
        return json.dumps(s, ensure_ascii=False)
    return s


def _filter_answer_patch(full_patch: str) -> str:
    """answer/full.patch 去掉 tests/** 的段(测试 hunk 是隐藏判据,且交付树
    上那些文件已剥,施加必失败)。按 'diff --git ' 分段,整段取舍。"""
    segments, keep = [], []
    cur: list[str] = []
    for line in full_patch.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if cur:
                segments.append(cur)
            cur = [line]
        else:
            cur.append(line)
    if cur:
        segments.append(cur)
    for seg in segments:
        # b/ 路径在首行:diff --git a/<p> b/<p>
        target = seg[0].split(" b/", 1)[1].strip()
        if not target.startswith("tests/"):
            keep.append("".join(seg))
    return "".join(keep)


def _sabotage_patch(host: Path, spec: dict) -> str:
    """在靶文件末尾追加一行覆盖 —— difflib 生成带正确上下文的 unified diff。"""
    rel = spec["file"]
    old = (host / rel).read_text(encoding="utf-8")
    new = old + ("" if old.endswith("\n") else "\n") + spec["line"] + "\n"
    diff = difflib.unified_diff(old.splitlines(keepends=True),
                                new.splitlines(keepends=True),
                                fromfile=f"a/{rel}", tofile=f"b/{rel}")
    return f"diff --git a/{rel} b/{rel}\n" + "".join(diff)


def _load_round2_evidence() -> dict:
    ev = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    for cid in ("click-3581", "click-3407", "sqlglot-8042"):
        rec = ev["hosts"][cid] if "hosts" in ev else ev[cid]
        if "attacker_residue" not in rec:
            raise SystemExit(
                f"证据缺第二轮标记(attacker_residue):{cid} —— "
                "prepare-hb1.json 还是第一轮受污染数据,先跑重构部署再生成任务包")
    return ev


def _rec_of(ev: dict, cid: str) -> dict:
    return ev["hosts"][cid] if "hosts" in ev else ev[cid]


def build_task(t: dict, ev: dict) -> dict:
    """生成一个任务包;返回 {写入相对路径: 期望 sha256} 供 --check。"""
    pkg = TASKS_ROOT / t["pkg"]
    cand = ARCHIVE / "candidates" / t["cid"]
    host = BENCH / t["bench"] / "host"
    law = t.get("construction_law", "v1")
    rec = _rec_of(ev, t.get("evidence_key", t["cid"]))
    hygiene = json.loads((HYGIENE / f"{t['cid']}.json").read_text(encoding="utf-8"))
    baseline = rec["baseline"]
    written: dict[str, str] = {}

    def emit(rel: str, content: bytes) -> None:
        p = pkg / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        written[rel] = _sha_bytes(content)

    # ---- 题面副本(公开上游文本,入 git;契约 statement 与之逐字节同源)
    statement = (cand / "statement.md").read_text(encoding="utf-8")
    emit("statement.md", statement.encode())

    # ---- 教导面(R2,只对 v2 加两条;statement 保持上游原文一字不动):
    # R5 = 隐藏节点**名单**宣示 —— 节点名早已入公开 manifest,内容仍是答案;
    # R6 = 回归网宣示 + 隐藏面保守性(multiple_pivoted 类 12/12 全砸的唯一
    # 合法杠杆,R3 分类学 bbd5169)。
    reqs = list(REQUIREMENTS)
    if law == "v2":
        nodes = ", ".join(hygiene["delta_nodes"])
        reqs = reqs + [
            {"id": "R5", "text": "The hidden acceptance nodes for this exact "
             "feature are (names public, contents hidden): " + nodes + ". "
             "Your implementation must make these exact behaviors work."},
            {"id": "R6", "text": "The visible tests/ tree is the project's own "
             "suite as it stood just before this feature landed (including the "
             "base version of the test file the hidden nodes extend). Run the "
             "full suite before submitting. The hidden grading suite ALSO "
             "contains additional tests of PRE-EXISTING behavior beyond the "
             "visible suite: keep every change semantically conservative, and "
             "verify the behavior you touch with your own throwaway probes "
             "(outside tests/) instead of relying only on the visible suite."},
        ]

    # ---- 契约
    contract = {
        "task_id": t["task_id"],
        "task_version": "v2" if law == "v2" else "v1",
        "kind": "host_integrated",
        "prompt_profile": "hb-delta-v2" if law == "v2" else "hb-delta-v1",
        "host": {
            "repo": t["repo"],
            "commit": t["parent"],
            "copy_path": f"~/RepoProofBench/{t['bench']}/host",
            "regression_command": REGRESSION_CMD,
            "regression_baseline":
                f"{baseline['passed']} passed, {baseline['skipped']} skipped, 0 failed",
            "setup_commands": [["python3", "-m", "venv", ".venv"], t["pip_step"]],
            "health_checks": [{"command": [".venv/bin/python", "-c", t["import_check"]]}],
            "host_root_env": t["host_root_env"],
            "wheelhouse_path": f"~/RepoProofBench/{t['bench']}/wheelhouse",
            "require_wheelhouse_manifest": False,
            "pii_scan_profile": "public-oss-tree",
            # 审查 blocking [1a]:不给判卷进程注 PYTHONPATH=<宿主根>,否则根下
            # sitecustomize.py 会在判卷解释器起点被自动 import(H1 守卫本身也
            # 在那个被污染的解释器里跑)。delta oracle 自带 sys.path.insert。
            "oracle_env_sanitized": True,
            # 只在 True 时发射:click 两包契约字节保持不变(其 F0 电池已验)
            **({"path_prepend_venv_bin": True}
               if t.get("path_prepend_venv_bin") else {}),
        },
        "capability": {"statement": statement, "requirements": reqs},
        "constraints": {"forbidden": FORBIDDEN},
        "budgets": BUDGETS,
        "acceptance": {
            "public_test_command": PUBLIC_CMD,
            # 死字段(harness 写死 pytest oracle_snap),照旧声明以保形状一致
            "hidden_oracle_command": ["python", "-m", "pytest", "<ORACLE_ABS>",
                                      "-q", "-p", "no:cacheprovider"],
        },
        "task_shape": {"form": "postcutoff-delta",
                       "delta_nodes": len(hygiene["delta_nodes"]),
                       "single_module": True},
        "failure_taxonomy_expected": FAILURE_TAXONOMY,
        "task_family": "HB-PCDELTA",
        "adoption_shape": "UPSTREAM_FEATURE_DELTA",
    }
    emit("contract.yaml", (_yaml_str(contract) + "\n").encode())

    # ---- oracle:驱动器副本 + 包装 + conftest + manifest(全部入 git)
    lib = (REPO / "scripts/delta_oracle_lib.py").read_bytes()
    emit("oracle/delta_oracle_lib.py", lib)
    emit("oracle/test_hidden_delta.py", ORACLE_WRAPPER.encode())
    emit("oracle/conftest.py", ORACLE_CONFTEST.encode())

    post_dir = cand / "delta_tests" / "post"
    post_files = sorted(p for p in post_dir.rglob("*") if p.is_file())
    manifest = {
        "candidate": t["cid"],
        "task_id": t["task_id"],
        "delta_nodes": hygiene["delta_nodes"],
        "post_files": [{"path": str(p.relative_to(post_dir)),
                        "sha256": _sha_bytes(p.read_bytes())} for p in post_files],
        "tests_tree_sha256": tests_tree_digest(host),
        "guarded_root_files": guarded_root_state(host),
        # 守卫子树 = 判卷收集子树,单一来源(审查 blocking [1b]):裸 pytest 收
        # 整棵树时,任何新建目录的 conftest.py 都能注册全局插件 —— sqlglot 无
        # testpaths,正是这么被攻破的。三宿主上游测试均在 tests/。
        "tests_subdir": "tests",
        "suite_timeout_s": t["suite_timeout_s"],
        "generated_by": "scripts/build_hb1_task_packages.py",
        "note": ("post_tests/ 与 controls/*/apply.patch 是物化件(答案承载,"
                 "不入 git);缺料 fail-closed 拒判"),
    }
    if law == "v2":
        # base_files 驱动 oracle lay 的 save/覆写/放回分支;sha 取自宿主
        # (构造交叉验证已证宿主 = parent 版)。base 内容是公开的 parent
        # 树文件,sha 入 git 零答案暴露。空清单 = 宿主没按 v2 法建,炸。
        arch_tf = json.loads((cand / "manifest.json")
                             .read_text(encoding="utf-8"))["test_files"]
        base_files = [{"path": tf,
                       "sha256": _sha_bytes((host / tf).read_bytes())}
                      for tf in arch_tf if (host / tf).is_file()]
        if not base_files:
            raise SystemExit(
                f"{t['pkg']}: 构造法 v2 但宿主里没有任何 base 测试文件 —— "
                "先 prepare_hb1_hosts.py --hosts --v2 重建宿主")
        manifest["construction_law"] = "v2"
        manifest["base_files"] = base_files
    emit("oracle/delta_manifest.json",
         (json.dumps(manifest, ensure_ascii=False, indent=1) + "\n").encode())

    # ---- 物化件:post 测试原文(答案承载,gitignore)
    for p in post_files:
        emit(f"oracle/post_tests/{p.relative_to(post_dir)}", p.read_bytes())

    # ---- 公开面锚
    emit("public_tests/README.md", PUBLIC_README.encode())

    # ---- 控制组
    emit("controls/positive/smoke_setup.txt", SMOKE_SETUP.encode())
    positive = _filter_answer_patch((cand / "answer/full.patch").read_text(encoding="utf-8"))
    emit("controls/positive/apply.patch", positive.encode())        # 物化件
    emit("controls/nc_null_submission/README.md", NC_NULL_DOC.encode())
    emit("controls/nc_null_submission/apply.patch", NULL_PATCH.encode())
    sab = _sabotage_patch(host, t["sabotage"])
    emit("controls/nc_regression_break/README.md", NC_BREAK_DOC.encode())
    emit("controls/nc_regression_break/sabotage.patch", sab.encode())
    emit("controls/nc_regression_break/apply.patch", (positive + sab).encode())  # 物化件
    emit("controls/nc_instrument_tamper/README.md", NC_TAMPER_DOC.encode())
    emit("controls/nc_instrument_tamper/apply.patch", NC_TAMPER_PATCH.encode())
    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="重算生成物并与盘上比对,漂移报错(不写盘)")
    args = ap.parse_args()
    ev = _load_round2_evidence()
    drift: list[str] = []
    for t in TASKS + TASKS_V2:
        if args.check:
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                global TASKS_ROOT
                real_root = TASKS_ROOT
                TASKS_ROOT = Path(td)
                try:
                    expect = build_task(t, ev)
                finally:
                    TASKS_ROOT = real_root
            for rel, sha in expect.items():
                f = TASKS_ROOT / t["pkg"] / rel
                if not f.is_file():
                    drift.append(f"{t['pkg']}/{rel}: MISSING")
                elif _sha_bytes(f.read_bytes()) != sha:
                    drift.append(f"{t['pkg']}/{rel}: DRIFT")
        else:
            written = build_task(t, ev)
            print(f"{t['pkg']}: {len(written)} 件已生成")
    if args.check:
        if drift:
            print("DRIFT:\n" + "\n".join(drift))
            return 1
        print("CHECK OK: 三个任务包与生成器输出逐字节一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
