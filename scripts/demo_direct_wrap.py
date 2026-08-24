"""固定演示 1(Gate 4):DIRECT_WRAP 全链 —— 零模型拿 PASS_DIRECT。

自包含、零网络、零真实模型、零主仓污染:一切产物落在
`/tmp/rp_direct_demo/`(独立 project root,台账/工具/任务包都在里面,
不触碰主仓 runs.jsonl 与 ~/tools)。重复运行前自动清场。

演示旅程(与指导 §11 的叙事一一对应):
  1. 合成一个真实形状的上游仓(minilib:一个单参数 Python callable);
  2. intake 静态分析 → 真 analyzer 产证据化 Capability Plan
     (SUPPORTED + DIRECT_WRAP,带 file:line 证据);
  3. 人工确认三项(脚本代确认并打印确认项);
  4. tool build 按计划路由:受信模板落进骨架,零 Agent、零模型,
     一发走完 held-out / provenance / import-hook / clean replay 全链;
  5. 结论 PASS_DIRECT,工具导出;打印生成的 impl.py 供检查。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import sysconfig  # noqa: E402

import yaml  # noqa: E402

DEMO = Path("/tmp/rp_direct_demo")

_MINILIB = '''MAGIC = "MINI\\n"


class FormatError(ValueError):
    pass


def rows_to_markdown(text):
    """Convert MINI text to a markdown row table."""
    if not text.startswith(MAGIC):
        raise FormatError("missing MINI header")
    rows = [l for l in text[len(MAGIC):].splitlines() if l.strip()]
    return "\\n".join(f"| {r} |" for r in rows)
'''

_REFERENCE = '''"""reference:真调 pinned minilib(出题人材料,绝不交付)。"""
from pathlib import Path

import minilib


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        text = input_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise UserInputError(str(e)) from e
    try:
        return minilib.rows_to_markdown(text)
    except minilib.FormatError as e:
        raise UserInputError(str(e)) from e
'''


def step(n: int, title: str) -> None:
    print(f"\n=== 第 {n} 步:{title} " + "=" * max(4, 46 - len(title) * 2))


def main() -> int:
    from repoproof.adoption.admission.support_policy import evaluate_tool_policy
    from repoproof.adoption.analysis.repository_analyzer import (
        analyze_repository_dir,
    )
    from repoproof.adoption.intake.tool_confirm import write_draft_bundle
    from repoproof.adoption.intake.tool_intake import run_tool_intake
    from repoproof.adoption.planning.capability_plan import (
        build_capability_plan,
        confirm_plan,
    )
    from repoproof.harness import host_guard
    from repoproof.runner.tool_pipeline import tool_build

    host_guard.DEFAULT_PROTECTED = ()      # 演示进程内:不打主仓指纹
    if DEMO.exists():
        shutil.rmtree(DEMO)
    DEMO.mkdir(parents=True)
    project = DEMO / "proj"

    step(1, "合成上游仓(单参数 Python callable)")
    up = DEMO / "upstream"
    (up / "minilib").mkdir(parents=True)
    (up / "minilib" / "__init__.py").write_text(_MINILIB, encoding="utf-8")
    (up / "pyproject.toml").write_text(
        '[project]\nname = "minilib"\nversion = "0.1.0"\n'
        'license = {text = "MIT"}\nrequires-python = ">=3.10"\n'
        "dependencies = []\n"
        '[build-system]\nrequires = ["setuptools"]\n'
        'build-backend = "setuptools.build_meta"\n', encoding="utf-8")
    (up / "LICENSE").write_text("MIT License", encoding="utf-8")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=d@d", "-c", "user.name=d",
                  "commit", "-qm", "pin"]):
        subprocess.run(["git", "-C", str(up), *args], check=True,
                       capture_output=True)
    head = subprocess.run(["git", "-C", str(up), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    pinned = project / "upstream-cache" / f"upstream-{head[:12]}"
    pinned.parent.mkdir(parents=True)
    shutil.copytree(up, pinned)
    print(f"  上游 @ {head[:12]}(git 钉版)→ {pinned}")

    step(2, "证据化能力分析 → Capability Plan(零模型)")
    report = analyze_repository_dir(pinned)
    policy = evaluate_tool_policy(report)
    plan = build_capability_plan(pinned, report, policy,
                                 goal="把 MINI 文本转成 Markdown 行表")
    print(f"  support_status       = {plan.support_status}")
    print(f"  implementation_route = {plan.implementation_route}")
    print(f"  reason_codes         = {plan.reason_codes}")
    for s in plan.detected_surfaces:
        print(f"  surface: [{s.confidence}] {s.locator}{s.signature}"
              f"  证据={s.evidence}")
    assert plan.implementation_route == "DIRECT_WRAP", "演示前提:直连路线"

    step(3, "人工确认(计划未确认前不可冻结、不可触发模型)")
    for c in plan.human_confirmations:
        print(f"  ✔ 确认:{c}")
    confirm_plan(plan, acks=list(plan.human_confirmations))
    print(f"  plan_sha256 = {plan.plan_sha256[:16]}…(已封印,改动即拒执行)")

    step(4, "准备 draft 束(样例真值)并按计划路由构建")
    rep = run_tool_intake("file://minilib", "MINI 文本转 Markdown",
                          cache_root=DEMO / "cache", local_path=pinned)
    dest = write_draft_bundle(rep, DEMO / "draft")
    doc = yaml.safe_load((dest / "draft.yaml").read_text(encoding="utf-8"))
    doc["source_repo"]["url"] = "file://minilib"
    doc["source_repo"]["resolved_commit"] = head
    doc["tool"]["summary"] = "MINI→Markdown 行表"
    doc["tool"]["interface"]["input"]["format"] = "TXT"
    doc["tool"]["interface"]["output"]["format"] = "markdown-table"
    doc["tool"]["interface"]["output"]["contract"] = {
        "media_type": "text/markdown", "root_type": "text", "required": {}}
    doc["capability"]["statement"] = "MINI 文本转 Markdown 行表;坏输入 UserInputError。"
    doc["capability"]["output_schema"] = "MdRows"
    (dest / "draft.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    for n, txt in (("a", "MINI\nalpha"), ("b", "MINI\nbeta"),
                   ("c", "MINI\ngamma")):
        (dest / "examples" / f"{n}.txt").write_text(txt, encoding="utf-8")
    (dest / "examples.yaml").write_text(yaml.safe_dump({"examples": [
        {"input": "--help", "expected": "contains:usage"},
        {"input_file": "a.txt", "expected": "contains:| alpha |"},
        {"input_file": "b.txt", "expected": "contains:| beta |"},
        {"input_file": "c.txt", "expected": "contains:| gamma |"},
    ]}, allow_unicode=True), encoding="utf-8")
    (dest / "reference_impl.py").write_text(_REFERENCE, encoding="utf-8")
    (dest / "plan.yaml").write_text(
        yaml.safe_dump(plan.model_dump(), allow_unicode=True,
                       sort_keys=False), encoding="utf-8")

    repo_py = sys.executable
    site = sysconfig.get_paths()["purelib"]
    shim = (
        "import os, pathlib\n"
        "host = pathlib.Path(os.getcwd())\n"
        "b = host/'.venv'/'bin'; b.mkdir(parents=True, exist_ok=True)\n"
        "p = b/'python'\n"
        "p.write_text('#!/bin/bash\\n'\n"
        f"    'export PYTHONPATH=\"'+str(host/'src')+':{pinned}:{site}:'"
        "+'${PYTHONPATH:-}\"\\n'\n"
        f"    'exec \"{repo_py}\" \"$@\"\\n')\n"
        "p.chmod(0o755)\nprint('demo shim ready')\n")

    out = tool_build(dest, project, bench_root=DEMO / "bench",
                     dest_root=DEMO / "tools", run_real=True,
                     setup_commands=[[repo_py, "-c", shim]],
                     wheelhouse_cmd=["true"])

    step(5, "结论")
    route = out["stages"].get("route", {})
    direct = out["stages"].get("direct", {})
    print(f"  执行路线     = {route.get('route')}(agent_invoked="
          f"{route.get('agent_invoked')})")
    print(f"  内部结论     = {direct.get('verdict')}")
    print(f"  历史结论     = {out.get('historical_verdict') or out['verdict']}")
    print(f"  产品终止码   = {direct.get('product_stop_code')}")
    print(f"  运行证据     = {direct.get('run_id')}")
    print(f"  导出位置     = {out.get('exported')}")
    if out.get("exported"):
        impl = Path(out["exported"]) / "src" / "minilib_tool" / "impl.py"
        print("\n----- 受信模板生成的 impl.py(真调 pinned 上游)-----")
        print(impl.read_text(encoding="utf-8"))
        print("尝试一下这个工具:")
        print(f"  printf 'MINI\\n你好\\n世界\\n' > {DEMO}/in.txt")
        print(f"  {out['exported']}/bin/minilib-tool {DEMO}/in.txt")
        print("(该 bin 壳需先 build.sh;演示会话里的验证已在隔离 venv 完成)")
    return 0 if direct.get("verdict") == "PASS_DIRECT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
