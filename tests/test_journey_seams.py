"""旅程**接缝**的交接契约(harness 加固,2026-08-28)。

来由:这一轮用户实测挖出的缺陷,**没有一个**住在某一站内部 —— 全住在
站与站之间的接缝里,而测试是按站分仓的,于是一条都没拦住:

| 缺陷 | 接缝 | 症状 |
|---|---|---|
| #52 | confirm → build   | 备轮漏装上游,三轮修复后才以 DEPENDENCY_ERROR 浮出 |
| #55 | 彩排 → 真发       | 冻结消耗草稿,而 UI 没有下半程入口 |
| #56 | 起任务 → 判定     | 漏声明预期产物,成功的构建被报成失败 |
| #57 | 合同验收 ↔ 抽查   | 两把尺子,通过合同的工具被抽查判死 |

所以补的不是"再来一条 E2E"(它慢、脆,且照样只覆盖自己走过的那条路),
而是**把每条接缝的交接契约逐条钉死**:上一站必须交给下一站什么,下一站
凭什么相信它。每条钉都零模型、零网络、可秒级重跑。

`SEAMS` 是这张接缝表本身。新增一站就要新增一条接缝并配钉 —— 末尾的
元测试会核对"表里每条都真有钉",防止清单与现实各说各话(与 GAPS
"声明即须履行"同律)。
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

# (上一站, 下一站, 交接的是什么, 钉在哪个测试函数)
SEAMS = [
    ("confirm", "build", "controls 里必须有含上游 pin 的依赖锁",
     "test_seam_confirm_hands_build_an_upstream_pin"),
    ("build", "session", "wheelhouse 必须真含上游本体",
     "test_seam_build_hands_session_the_upstream_wheel"),
    ("rehearsal", "real", "彩排过的任务必须能被续跑清单认出",
     "test_seam_rehearsal_hands_real_a_resumable_task"),
    ("real", "verdict", "起任务必须声明预期产物,否则成功会被判成失败",
     "test_seam_real_hands_verdict_an_artifact_expectation"),
    ("contract", "audit", "抽查与合同验收必须同一把尺子",
     "test_seam_contract_hands_audit_the_same_yardstick"),
    ("audit", "mcp", "只有 ACTIVE 才能生成 MCP",
     "test_seam_audit_hands_mcp_only_active_tools"),
]


# ---------------------------------------------------------- confirm → build

def test_seam_confirm_hands_build_an_upstream_pin(tmp_path: Path):
    """交接物:`controls/<task>/reference/requirements.lock.txt` 含上游 pin。

    缺了它,备轮就只装 pytest 那套,会话里 `import <上游>` 必炸 —— 而且
    要等三轮修复耗尽才以 DEPENDENCY_ERROR 的形式浮出来(#52 实录)。
    草稿束没写时必须由**钉版树声明版本**派生,不能静默留空。
    """
    from repoproof.adoption.intake.draft_readiness import resolved_dependency_lock

    commit = "e6392ba6eeba81b02e666eb3ed02ef2e006344c0"
    up = tmp_path / "upstream-cache" / f"upstream-{commit[:12]}"
    up.mkdir(parents=True)
    (up / "pyproject.toml").write_text(
        '[project]\nname = "webcolors"\nversion = "25.10.0"\n', encoding="utf-8")

    draft_dir = tmp_path / "draft"
    draft_dir.mkdir()
    draft = {
        "source_repo": {
            "distribution": "webcolors",
            "resolved_commit": commit,
        },
        "tool": {},
    }
    lock = resolved_dependency_lock(
        draft,
        draft_dir,
        project_root=tmp_path,
    )
    assert "webcolors==25.10.0" in lock

    # confirm 必须把 Core 已解析并校验的同一份锁交给装配器；不能再有
    # 第二套派生规则，否则 UI readiness 与冻结结果会产生双重事实源。
    from repoproof.adoption.intake import tool_confirm

    src = inspect.getsource(tool_confirm.confirm_tool_draft)
    assert "reference_lock=resolved_dependency_lock(" in src


# ----------------------------------------------------------- build → session

def test_seam_build_hands_session_the_upstream_wheel(tmp_path: Path):
    """交接物:wheelhouse 里真有上游轮子 —— 而且**事后核账**,不假设。

    pip 说成功不等于上游躺在那儿(名字规范化、sdist/wheel 差异都能让它
    落空)。不量一次就等于假设。
    """
    from repoproof.runner import tool_pipeline

    src = inspect.getsource(tool_pipeline.tool_build)
    assert "resolve_upstream_pins" in src, "备轮必须用会派生+会拒发的那个入口"
    assert "wheelhouse 里没有上游" in src, "备轮后必须核账上游是否真在"

    # 派生不出版本时当场拒发,而不是建一个注定装不上上游的 wheelhouse
    bare = tmp_path / "upstream-cache" / "upstream-000000000000"
    bare.mkdir(parents=True)
    (bare / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndynamic = ["version"]\n', encoding="utf-8")
    with pytest.raises(tool_pipeline.PipelineError, match="备轮缺上游"):
        tool_pipeline.resolve_upstream_pins(
            tmp_path, "tool-x-v1", distribution="x", upstream_dir=bare)


# ------------------------------------------------------------ 彩排 → 真发

def test_seam_rehearsal_hands_real_a_resumable_task(tmp_path: Path):
    """交接物:彩排过、未导出的任务必须出现在续跑清单里。

    冻结**消耗**草稿(题面已冻结,不该再改 —— 这一步是对的),所以下半程
    只能凭 task_id 续跑。没有这个清单,用户彩排一过就无路可走,只能重建
    草稿再冻一版(#55 实录:用户手上因此攒了 v1..v5)。
    """
    from repoproof.runner.tool_pipeline import rehearsed_tasks

    (tmp_path / "contracts").mkdir()
    for tid in ("tool-demo-v1", "tool-done-v1"):
        (tmp_path / "contracts" / f"{tid}.yaml").write_text("kind: x\n", encoding="utf-8")
    ledger = tmp_path / "benchmarks" / "v2"
    ledger.mkdir(parents=True)
    (ledger / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"task_id": "tool-demo-v1", "run_id": "r1",
         "model": "fake-scripted:positive", "verdict": "PASS_ADAPTED"},
        {"task_id": "tool-done-v1", "run_id": "r2",
         "model": "fake-scripted:positive", "verdict": "PASS_ADAPTED"},
        {"task_id": "tool-done-v1", "run_id": "r3",
         "model": "gpt-5.6-terra", "verdict": "PASS_ADAPTED"},
    ]) + "\n", encoding="utf-8")

    got = rehearsed_tasks(tmp_path)
    assert [r["task_id"] for r in got] == ["tool-demo-v1"]   # 已真发的不再列


# ------------------------------------------------------------ 真发 → 判定

def test_seam_real_hands_verdict_an_artifact_expectation():
    """交接物:起任务时必须声明**预期产物**。

    判定器是有意的 fail-closed(证明不了产出就不算成功)。调用方漏给,
    就会出现"退出码 0、PASS_ADAPTED、工具已装进 ~/tools,界面却写失败"
    (#56 实录)。所以续跑入口必须声明产物,且入口处当场拒绝 None。
    """
    from repoproof.ui.services import product_jobs

    src = inspect.getsource(product_jobs.start_tool_build_real)
    assert "expected_artifact=expected" in src, "续跑没有声明预期产物"
    assert "tool.json" in src, "预期产物应为导出的工具清单"

    spawn = inspect.getsource(product_jobs._start_product_job)
    assert "expected_artifact is None" in spawn, "漏给产物约定必须在入口就拒"


# ---------------------------------------------------------- 合同验收 ↔ 抽查

def test_seam_contract_hands_audit_the_same_yardstick():
    """交接物:**同一把尺子**。

    合同验收测试与 fresh-input 抽查判的是同一件事(实际输出是否等于期望),
    用两份实现迟早分家:#57 实录里,一个通过了全部能力测试的工具被抽查
    按裸字节判死并自动撤回。
    """
    from repoproof.adoption.assembly import example_compiler
    from repoproof.runner import tool_release
    from repoproof.verification.output_match import canonical_source, compare_output

    assert "from repoproof.verification.output_match import compare_output" in \
        inspect.getsource(tool_release), "抽查没走唯一判据源"
    assert "canonical_source" in inspect.getsource(example_compiler), \
        "生成的验收测试没内联唯一判据源"

    # 噪声要容、语义必红 —— 两侧同一函数,故一处验证即两处成立
    assert compare_output('{"a":1}\n', '{"a":1}', root_type="object")[0]
    assert not compare_output('{"a":1}', '{"a":2}', root_type="object")[0]
    assert "def compare_output" in canonical_source()


# -------------------------------------------------------------- 抽查 → MCP

def test_seam_audit_hands_mcp_only_active_tools():
    """交接物:运营状态。MCP 只暴露 fresh-input 抽查后的 ACTIVE 工具。

    这条接缝是"能不能被 AI 自动调用"的最后一道闸 —— 它必须读**状态账**,
    而不是读"历史验证通过"。历史成绩不代表今天可用。
    """
    from repoproof.runner import tool_mcp

    src = inspect.getsource(tool_mcp)
    assert "operational_status(" in src, "MCP 必须查当前运营状态"
    assert "!= ACTIVE" in src and "MCP 只暴露" in src


# ------------------------------------------------------ 接缝表自身必须诚实

def test_every_declared_seam_has_a_pin():
    """**制度钉**:接缝表里每条都要有真的钉子。

    清单与现实各说各话,是这个项目反复吃过的亏(GAPS 那次:声明 owner=AUTO
    却无人履行)。新增一站就要新增一条接缝并配钉,这里当场核对。
    """
    here = {name for name, obj in globals().items()
            if name.startswith("test_") and callable(obj)}
    for src_stage, dst_stage, what, pin in SEAMS:
        assert pin in here, f"接缝 {src_stage}→{dst_stage}({what})没有钉:{pin}"
    assert len(SEAMS) == len({(s, d) for s, d, _w, _p in SEAMS}), "接缝表有重复"


def test_no_second_yardstick_grows_back():
    """**扫描钉**:全仓不许再出现"自造的输出比对"。

    接缝钉防的是回归;这一条防的是**新长出来的第二把尺子** —— #57 的
    病根不是某一行写错,而是"同一件事各写各的"这个习惯。谁再写一处
    `stdout == expected`,这里当场红,并被引到唯一判据源。
    """
    import re

    src_root = Path(__file__).resolve().parents[1] / "src" / "repoproof"
    suspicious = re.compile(r"(stdout\s*[!=]=\s*\w*expected|expected\s*[!=]=\s*\w*stdout)")
    offenders = []
    for path in src_root.rglob("*.py"):
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if suspicious.search(line) and "compare_output" not in line:
                offenders.append(f"{path.relative_to(src_root)}:{lineno}")
    assert not offenders, (
        f"这些地方自己比对输出,没走唯一判据源 verification.output_match:"
        f"{offenders}")
