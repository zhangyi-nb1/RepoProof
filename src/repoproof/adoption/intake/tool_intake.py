"""LOCAL-TOOL intake(M2-a · RFC-010 [G1] 的确定性骨架)。

GitHub URL(或本地树)+ 用户能力一句话 →
    RepositoryReport(既有分析器,FACT/INFERENCE/UNKNOWN 标注)
  → AdmissionReport(decide_tool 单仓四态)
  → ToolContract **草稿**:能确定性推导的字段全部填死,填不了的进
    缺口清单(DraftGap),按 owner 分派:
      USER — 只能人给(样例真值 / 最终名称与接口确认 / reference 认可);
      LLM  — M2-d 起草层负责(statement 措辞 / 样例断言建议 / reference 草稿);
      AUTO — 后续确定性增强可补(非阻塞)。

纪律([G1]):本模块**零 LLM 零猜测** —— 推导不出的一律进缺口,不填
似是而非的值;草稿永远是 DRAFT(不产 sidecar,冻结属确认流 M2-b)。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from pydantic import BaseModel

from repoproof.adoption.admission.admission_report import AdmissionReport, decide_tool
from repoproof.adoption.analysis.repository_analyzer import (
    Finding,
    RepositoryReport,
    analyze_repository_dir,
    clone_for_analysis,
)

_OWNERS = ("USER", "LLM", "AUTO")


class DraftGap(BaseModel):
    field: str          # 草稿里的路径,如 "tool.summary" / "examples"
    owner: str          # USER | LLM | AUTO
    why: str

    def model_post_init(self, _ctx) -> None:
        if self.owner not in _OWNERS:
            raise ValueError(f"未知缺口 owner:{self.owner!r}")


class ToolIntakeReport(BaseModel):
    capability_goal: str
    repo: RepositoryReport
    admission: AdmissionReport
    draft: dict
    draft_gaps: list[DraftGap]

    def to_dict(self) -> dict:
        return self.model_dump()


# ------------------------------------------- 确定性提取(分析器未覆盖的两项)

def extract_distribution(repo_dir: Path) -> tuple[str, str]:
    """→ (distribution, evidence);推导不出返回 ("", 原因)。"""
    pyproject = repo_dir / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            return "", "pyproject.toml 存在但解析失败"
        name = (data.get("project") or {}).get("name")
        if isinstance(name, str) and name.strip():
            return name.strip(), "pyproject.toml [project].name"
    setup_cfg = repo_dir / "setup.cfg"
    if setup_cfg.is_file():
        m = re.search(r"^name\s*=\s*(\S+)", setup_cfg.read_text(encoding="utf-8"),
                      re.MULTILINE)
        if m:
            return m.group(1), "setup.cfg [metadata] name"
    # 老式 setup.py:只认**字面量**形态(name="x" 或 NAME = "x" 顶层常量再
    # name=NAME)—— 静态读取,永不执行仓库代码;动态计算的名字如实放弃。
    setup_py = repo_dir / "setup.py"
    if setup_py.is_file():
        text = setup_py.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"""\bname\s*=\s*["']([A-Za-z0-9_.-]+)["']""", text)
        if m:
            return m.group(1), 'setup.py name="…" 字面量'
        mv = re.search(r"""\bname\s*=\s*([A-Z_][A-Z0-9_]*)\b""", text)
        if mv:
            mc = re.search(rf"""^{mv.group(1)}\s*=\s*["']([A-Za-z0-9_.-]+)["']""",
                           text, re.MULTILINE)
            if mc:
                return mc.group(1), f"setup.py {mv.group(1)} 常量字面量"
        return "", "setup.py 存在但 name 非静态字面量(不执行代码,放弃推导)"
    return "", "无 pyproject [project].name / setup.cfg / setup.py name"


def extract_import_module(repo_dir: Path, distribution: str) -> tuple[str, str]:
    """→ (import_module, evidence);推导不出返回 ("", 原因)。

    顺序:src/<pkg>/__init__.py → 顶层 <pkg>/__init__.py,候选名 =
    distribution 的下划线化;都不在则扫唯一顶层包。"""
    cand = distribution.replace("-", "_").replace(".", "_")
    for base, label in ((repo_dir / "src", "src 布局"), (repo_dir, "顶层布局")):
        if cand and (base / cand / "__init__.py").is_file():
            return cand, f"{label}:{cand}/__init__.py 存在"
    for base, label in ((repo_dir / "src", "src 布局"), (repo_dir, "顶层布局")):
        if not base.is_dir():
            continue
        pkgs = [p.name for p in base.iterdir()
                if p.is_dir() and (p / "__init__.py").is_file()
                and not p.name.startswith((".", "_")) and p.name != "tests"]
        if len(pkgs) == 1:
            return pkgs[0], f"{label}:唯一顶层包 {pkgs[0]}/"
    return "", "无法定位唯一可导入包"


def _suggest_tool_name(capability_goal: str, distribution: str) -> str:
    """确定性建议(最终名归 USER):distribution 的 kebab 化。"""
    base = distribution or "tool"
    return re.sub(r"[^a-z0-9-]+", "-", base.lower()).strip("-") or "tool"


# --------------------------------------------------------------- 草稿组装

def build_draft(repo: RepositoryReport, repo_dir: Path,
                capability_goal: str) -> tuple[dict, list[DraftGap]]:
    gaps: list[DraftGap] = []

    dist, dist_ev = extract_distribution(repo_dir)
    if not dist:
        gaps.append(DraftGap(field="source_repo.distribution", owner="USER",
                             why=dist_ev))
    imp, imp_ev = extract_import_module(repo_dir, dist)
    if not imp:
        gaps.append(DraftGap(field="source_repo.import_module", owner="USER",
                             why=imp_ev))

    name = _suggest_tool_name(capability_goal, dist)
    package = name.replace("-", "_")
    commit = str(repo.commit.value) if repo.commit.provenance != "UNKNOWN" else ""
    license_id = (str(repo.license.value)
                  if repo.license.provenance != "UNKNOWN" else "")
    if not license_id or "未识别" in license_id:
        gaps.append(DraftGap(field="source_repo.license", owner="USER",
                             why="许可证未识别,人工确认兼容性"))

    draft = {
        "_draft": {
            "status": "DRAFT",
            "note": "确定性字段已填;缺口见 draft_gaps。冻结走确认流,"
                    "本文件不产 sidecar。",
            "provenance": {"distribution": dist_ev, "import_module": imp_ev},
        },
        "task_id": f"tool-{name}-v1",
        "source_repo": {
            "url": repo.repository,
            "revision": "guided",
            "resolved_commit": commit,
            "license": license_id,
            "distribution": dist,
            "import_module": imp,
        },
        "target_project": {"kind": "local_tool",
                           "path": f"fixtures/tool_skeleton_{name}",
                           "package": package, "entry_point": name},
        "task_family": "LOCAL-TOOL",
        "adoption_shape": "TOOL_ONBOARDING",
        "tool": {
            "name": name,
            "summary": "",
            "interface": {
                "usage": f"{name} <input> [--out FILE]",
                "input": {"kind": "file", "format": ""},
                "output": {"kind": "stdout", "format": ""},
                "exit_codes": {"0": "success", "1": "user_error",
                               "2": "internal_error"},
            },
        },
        "capability": {"statement": "", "output_schema": ""},
        "environment": {"os": "linux", "arch": "arm64", "python": "3.12",
                        "cpu_only": True, "network_install": True,
                        "network_test": False},
        "constraints": {"forbidden": ["gpu", "privileged_container",
                                      "oracle_write", "model_download",
                                      "network_at_test_time"],
                        "editable_zones": ["tool"],
                        "forbidden_install_extras": []},
        "budgets": {"max_agent_steps": 20, "max_wall_time_minutes": 30,
                    "max_command_minutes": 5, "max_semantic_recoveries": 3,
                    "max_same_action": 2, "max_patch_files": 12,
                    "max_patch_lines": 600, "max_input_tokens_total": 400000,
                    "max_output_tokens_total": 40000,
                    "monetary_soft_cap_usd": 5.0},
        "acceptance": {
            "capability_command": ["pytest", "-q", "/oracle/test_capability.py"],
            "regression_command": ["pytest", "-q",
                                   "public_tests/test_interface_contract.py"],
            "probe_script": "direct_tool_probe.py",
        },
    }

    gaps += [
        DraftGap(field="tool.name", owner="USER",
                 why=f"确定性建议 {name!r}(取自 distribution)——最终命名归用户"),
        DraftGap(field="tool.summary", owner="LLM",
                 why="一句话摘要,起草层从 goal+仓库事实措辞"),
        DraftGap(field="tool.interface.input.format", owner="LLM",
                 why="输入格式名,从 goal 与仓库能力候选起草,用户确认"),
        DraftGap(field="tool.interface.output.format", owner="LLM",
                 why="输出格式名,同上"),
        DraftGap(field="capability.statement", owner="LLM",
                 why="含行为定义(渲染/边界语义)的题面,起草后过 adequacy 闸再人确认"),
        DraftGap(field="capability.output_schema", owner="LLM",
                 why="输出 schema 名,随 statement 起草"),
        DraftGap(field="examples", owner="USER",
                 why="golden 样例文件与期望是验收真值,只能人提供/确认"
                     "(LLM 可建议断言形态;≥3 组、含文件样例、留 held-out)"),
        DraftGap(field="reference_impl", owner="LLM",
                 why="真调上游的参考实现草稿(弱档执法的通关正控),用户确认后入题"),
        DraftGap(field="reference_lock", owner="AUTO",
                 why="确认 reference 后由 pip 冻结闭包生成(确定性)"),
    ]
    return draft, gaps


# ------------------------------------------------------------------ 入口

def run_tool_intake(
    source: str,
    capability_goal: str,
    *,
    cache_root: Path,
    revision: str | None = None,
    local_path: Path | None = None,
) -> ToolIntakeReport:
    """source = GitHub URL(联网浅克隆)或忽略(local_path 直读,零网络)。"""
    if local_path is not None:
        repo_dir: Path | None = Path(local_path).resolve()
        repo = analyze_repository_dir(repo_dir, url=source or str(repo_dir))
    else:
        # 与 analyze_repository 同两步,但持有仓目录(草稿提取要读它)
        repo_dir, err = clone_for_analysis(source, revision, cache_root)
        if repo_dir is None:
            repo = RepositoryReport(
                repository=source, requested_revision=revision,
                is_public=Finding.unknown(f"clone 失败: {err}"),
                commit=Finding.unknown(), license=Finding.unknown(),
                python_version=Finding.unknown(),
                install_method=Finding.unknown(),
                risks=[f"无法获取仓库: {err}"])
        else:
            repo = analyze_repository_dir(
                repo_dir, url=source, requested_revision=revision,
                is_public=Finding.fact(True, "匿名浅克隆成功"))
    admission = decide_tool(repo)
    if repo_dir is None:
        # 克隆失败:admission 自会给 UNSUPPORTED/缺口;草稿无从谈起
        return ToolIntakeReport(capability_goal=capability_goal, repo=repo,
                                admission=admission, draft={},
                                draft_gaps=[DraftGap(
                                    field="*", owner="USER",
                                    why="仓库不可达,无法起草")])
    draft, gaps = build_draft(repo, repo_dir, capability_goal)
    return ToolIntakeReport(capability_goal=capability_goal, repo=repo,
                            admission=admission, draft=draft, draft_gaps=gaps)
