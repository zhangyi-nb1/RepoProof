"""CapabilityPlanV1 · RFC-013 Gate 1 关闭条件的钉死。

五类零模型 fixture(合成本地仓,走真 analyzer → 真 policy → 真路由):
  1 API 直包仓 → SUPPORTED + DIRECT_WRAP(单 HIGH callable,file:line 证据)
  2 CLI 信号仓 → AGENT_ADAPT + CLI_SIGNAL_ONLY(CLI 是信号不是路线)
  3 歧义仓     → AGENT_ADAPT + AMBIGUOUS_SURFACE(多 HIGH 不猜单选)
  4 GPU+secret → UNSUPPORTED(零模型调用,reason 双码)
  5 service    → EXPERIMENTAL(M7 未关,不入产线)
另:重复生成逐字节一致;LLM 建议升级状态被整体忽略;确认闸与执行闸。
全程零模型零网络 —— 这正是 Gate 1 的可信边界本身。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repoproof.adoption.admission.support_policy import evaluate_tool_policy
from repoproof.adoption.analysis.repository_analyzer import analyze_repository_dir
from repoproof.adoption.planning.capability_plan import (
    PlanError,
    apply_llm_advice,
    assert_may_execute,
    assert_plan_matches_source,
    build_capability_plan,
    confirm_plan,
)

_MIT = "MIT License\n\nCopyright (c) 2026 Fixture\n\nPermission is hereby granted..."


def _git_pin(root: Path) -> None:
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t",
                  "commit", "-qm", "pin"]):
        subprocess.run(["git", "-C", str(root), *args], check=True,
                       capture_output=True)


def _repo(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    root = tmp_path / name
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    _git_pin(root)
    return root


def _plan(root: Path, goal: str):
    report = analyze_repository_dir(root)
    policy = evaluate_tool_policy(report)
    return build_capability_plan(root, report, policy, goal=goal), report


_PYPROJECT = (
    '[project]\nname = "{name}"\nversion = "1.0.0"\n'
    'license = {{text = "MIT"}}\nrequires-python = ">=3.10"\n{extra}')


def _direct_repo(tmp_path: Path) -> Path:
    return _repo(tmp_path, "direct", {
        "pyproject.toml": _PYPROJECT.format(name="slugkit", extra=""),
        "LICENSE": _MIT,
        "README.md": "# slugkit\nConvert text files to slugs.\n",
        "src/slugkit/__init__.py": (
            '__all__ = ["convert"]\n\n\n'
            "def convert(input_path: str) -> str:\n"
            '    """Convert one input file to a slug string."""\n'
            "    return str(input_path)\n"),
    })


# ------------------------------------------------------------ 五类 fixture

def test_fixture1_api_repo_routes_direct_wrap(tmp_path):
    root = _direct_repo(tmp_path)
    plan, _ = _plan(root, "把文本文件转成 slug")
    assert plan.support_status == "SUPPORTED", plan.reason_codes
    assert plan.implementation_route == "DIRECT_WRAP"
    assert "SINGLE_CALLABLE_MAPPED" in plan.reason_codes
    picked = [s for s in plan.detected_surfaces
              if s.kind == "python_callable" and s.confidence == "HIGH"]
    assert len(picked) == 1
    s = picked[0]
    assert s.locator == "slugkit:convert"
    assert s.signature.startswith("(input_path: str)")
    assert s.evidence and ":" in s.evidence[0]        # file:line 证据必须在
    assert s.exclusion_reason == ""                   # 被选中者无排除理由
    assert plan.confirmed is False and plan.plan_sha256


def test_fixture2_cli_signal_routes_agent_adapt(tmp_path):
    root = _repo(tmp_path, "cliish", {
        "pyproject.toml": _PYPROJECT.format(
            name="cliish",
            extra='\n[project.scripts]\ncliish = "cliish.cli:main"\n'),
        "LICENSE": _MIT,
        "src/cliish/__init__.py": '__all__ = ["run", "helper"]\n',
        "src/cliish/core.py": (
            "def run(path, mode):\n    return path\n\n\n"
            "def helper(a, b):\n    return a\n"),
    })
    plan, _ = _plan(root, "运行转换")
    assert plan.support_status == "SUPPORTED"
    assert plan.implementation_route == "AGENT_ADAPT"
    assert "CLI_SIGNAL_ONLY" in plan.reason_codes
    cli = [s for s in plan.detected_surfaces if s.kind == "cli_entry"]
    assert cli and all(s.exclusion_reason for s in cli)   # CLI 必须带排除理由


def test_fixture3_ambiguous_repo_flags_and_adapts(tmp_path):
    root = _repo(tmp_path, "ambig", {
        "pyproject.toml": _PYPROJECT.format(name="ambig", extra=""),
        "LICENSE": _MIT,
        "src/ambig/__init__.py": (
            '__all__ = ["encode", "decode"]\n\n\n'
            "def encode(path: str) -> str:\n    return path\n\n\n"
            "def decode(path: str) -> str:\n    return path\n"),
    })
    plan, _ = _plan(root, "转换文件")
    assert plan.support_status == "SUPPORTED"
    assert plan.implementation_route == "AGENT_ADAPT"     # 多 HIGH 不猜单选
    assert "AMBIGUOUS_SURFACE" in plan.reason_codes


def test_fixture4_gpu_secret_repo_is_unsupported(tmp_path):
    root = _repo(tmp_path, "gpuish", {
        "pyproject.toml": _PYPROJECT.format(name="gpuish", extra=""),
        "LICENSE": _MIT,
        "requirements.txt": "torch==2.4.0\n",
        "src/gpuish/__init__.py": (
            'import os\n\n__all__ = ["infer"]\n\n'
            'TOKEN = os.environ["GPUISH_API_KEY"]\n\n\n'
            "def infer(path: str) -> str:\n    return path\n"),
    })
    plan, _ = _plan(root, "推理")
    assert plan.support_status == "UNSUPPORTED"
    assert plan.implementation_route == "NONE"
    assert "GPU_REQUIRED" in plan.reason_codes
    assert "SECRET_REQUIRED" in plan.reason_codes


def test_fixture5_service_repo_is_experimental(tmp_path):
    root = _repo(tmp_path, "svc", {
        "pyproject.toml": _PYPROJECT.format(name="svc", extra=""),
        "LICENSE": _MIT,
        "requirements.txt": "flask==3.0.0\n",
        "src/svc/__init__.py": "__all__ = []\n",
        "src/svc/app.py": (
            "from flask import Flask\n\napp = Flask(__name__)\n"),
    })
    plan, _ = _plan(root, "起个服务")
    assert plan.support_status == "EXPERIMENTAL"
    assert plan.implementation_route == "NONE"
    assert plan.reason_codes == ["SERVICE_SHAPE"]
    assert any(s.kind == "http_service" for s in plan.detected_surfaces)


# ------------------------------------------------ 确定性 · 守卫 · 闸

def test_repeat_analysis_is_byte_identical(tmp_path):
    root = _direct_repo(tmp_path)
    p1, _ = _plan(root, "把文本文件转成 slug")
    p2, _ = _plan(root, "把文本文件转成 slug")
    assert p1.model_dump_json() == p2.model_dump_json()
    assert p1.plan_sha256 == p2.plan_sha256
    # surfaces 有序(遍历顺序无关的保证形)
    keys = [(s.kind, s.locator) for s in p1.detected_surfaces]
    assert keys == sorted(keys)


def test_llm_advice_cannot_upgrade_status(tmp_path):
    root = _repo(tmp_path, "needsreview", {
        "pyproject.toml": _PYPROJECT.format(name="nr", extra=""),
        "LICENSE": _MIT,
        "src/nr/__init__.py": "__all__ = []\n",
    })
    plan, _ = _plan(root, "做点什么")
    assert plan.support_status == "REVIEW_REQUIRED"
    before = plan.plan_sha256
    out = apply_llm_advice(plan, {
        "support_status": "SUPPORTED",
        "implementation_route": "DIRECT_WRAP"})
    assert out.support_status == "REVIEW_REQUIRED"        # 状态纹丝不动
    assert out.implementation_route == "NONE"
    assert any("已整体忽略" in r for r in out.risks)       # 而且留了案底
    assert out.plan_sha256 != before                      # risks 变了,指纹如实变


def test_llm_advice_legal_reorder_only(tmp_path):
    root = _direct_repo(tmp_path)
    plan, _ = _plan(root, "把文本文件转成 slug")
    status0, route0 = plan.support_status, plan.implementation_route
    out = apply_llm_advice(plan, {"surface_preference": ["slugkit:convert"],
                                  "goal_summary": "slug 转换器"})
    assert (out.support_status, out.implementation_route) == (status0, route0)
    assert "[LLM 摘要草稿]" in out.capability_goal


def test_confirm_gate_and_execute_gate(tmp_path):
    root = _direct_repo(tmp_path)
    plan, _ = _plan(root, "把文本文件转成 slug")
    with pytest.raises(PlanError, match="未确认项"):
        confirm_plan(plan, acks=["callable locator"])
    with pytest.raises(PlanError, match="禁止执行"):
        assert_may_execute(plan)
    confirm_plan(plan, acks=list(plan.human_confirmations))
    assert plan.confirmed is True
    assert_may_execute(plan)                              # 确认后放行
    plan.capability_goal += "被人动了手脚"
    with pytest.raises(PlanError, match="被改动过"):
        assert_may_execute(plan)


def test_forged_unsupported_plan_cannot_execute(tmp_path):
    """外部审计实证的绕过路径必须死:UNSUPPORTED 计划手工置
    confirmed=true、补确认清单、**重算 SHA 自洽封口** —— 旧闸(只查
    confirmed+sha)会放行;现闸重查全部语义前提,必须拒。"""
    root = _repo(tmp_path, "gpuish2", {
        "pyproject.toml": _PYPROJECT.format(name="gpuish2", extra=""),
        "LICENSE": _MIT,
        "requirements.txt": "torch==2.4.0\n",
        "src/gpuish2/__init__.py": (
            'import os\n\n__all__ = ["infer"]\n\n'
            'TOKEN = os.environ["GPUISH_API_KEY"]\n\n\n'
            "def infer(path: str) -> str:\n    return path\n"),
    })
    plan, _ = _plan(root, "推理")
    assert plan.support_status == "UNSUPPORTED"
    plan.confirmed = True                       # 伪造确认
    plan.human_confirmations = ["callable locator"]
    plan.plan_sha256 = plan.compute_sha256()    # 重封 SHA,内容自洽
    with pytest.raises(PlanError, match="非 SUPPORTED"):
        assert_may_execute(plan)
    plan.implementation_route = "DIRECT_WRAP"   # 连路线一起伪造也不行
    plan.plan_sha256 = plan.compute_sha256()
    with pytest.raises(PlanError, match="非 SUPPORTED"):
        assert_may_execute(plan)


def test_forged_empty_confirmations_cannot_execute(tmp_path):
    """confirmed=true 但确认清单为空 = 从未有过可确认的东西 → 拒。"""
    root = _direct_repo(tmp_path)
    plan, _ = _plan(root, "把文本文件转成 slug")
    confirm_plan(plan, acks=list(plan.human_confirmations))
    plan.human_confirmations = []
    plan.plan_sha256 = plan.compute_sha256()
    with pytest.raises(PlanError, match="human_confirmations 为空"):
        assert_may_execute(plan)


def test_plan_source_binding_rejects_wrong_upstream(tmp_path):
    """plan 与 draft 上游身份绑定:别的仓/别的版本的计划冒充即拒;
    URL 归一化(尾斜杠 / .git / 大小写)不算不一致。"""
    root = _direct_repo(tmp_path)
    plan, _ = _plan(root, "把文本文件转成 slug")
    url, commit = plan.source["url"], plan.source["commit"]
    assert_plan_matches_source(plan, url=url, commit=commit)          # 同源放行
    assert_plan_matches_source(plan, url=(url.rstrip("/") + "/").upper(),
                               commit=commit)                          # 归一化等价
    with pytest.raises(PlanError, match="commit"):
        assert_plan_matches_source(plan, url=url, commit="0" * 40)
    with pytest.raises(PlanError, match="不一致"):
        assert_plan_matches_source(plan, url="https://example.com/other-repo",
                                   commit=commit)


def test_non_supported_plan_cannot_be_confirmed(tmp_path):
    root = _repo(tmp_path, "svc2", {
        "pyproject.toml": _PYPROJECT.format(name="svc2", extra=""),
        "LICENSE": _MIT,
        "requirements.txt": "fastapi==0.115.0\n",
        "src/svc2/__init__.py": "__all__ = []\n",
    })
    plan, _ = _plan(root, "服务")
    with pytest.raises(PlanError, match="不可确认执行"):
        confirm_plan(plan, acks=list(plan.human_confirmations))
