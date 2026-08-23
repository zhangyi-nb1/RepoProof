"""LOCAL-TOOL 单命令旅程编排(M3-a · RFC-010 §六 M3/方向文档 §7)。

两段式(单命令 ≠ 零交互 —— §7 的形态是"少量关键确认"):

    repoproof tool add   → intake + LLM 起草 → draft 束 + 人的待办清单
                           (人:放样例真值 / 审 statement 与 reference /
                            定工具名 —— 全部 [G1] 人闸职责)
    repoproof tool build → confirm(D+装配+T 闸冻结) → 钉版上游确保 →
                           conformance 选取+物化预检 → wheelhouse 备轮 →
                           fake 彩排(必须 PASS 才许烧真预算) → 真模型 →
                           export + 注册表登记

编排只做**顺序与门**,每步的判定权仍在各自组件(闸门语义零改动);
任何一步失败即停、如实返回该步的结论 —— 编排不吞错、不重试真发。
"""

from __future__ import annotations

import datetime
import json
import shutil
import subprocess
from pathlib import Path

import yaml

from repoproof.adoption.intake.tool_confirm import confirm_tool_draft
from repoproof.adoption.intake.upstream_conformance import select_upstream_tests
from repoproof.runner.tool_export import export_verified_tool
from repoproof.runner.tool_host_bridge import ToolBridgeError, materialize_tool_task
from repoproof.runner.tool_registry import register_tool


class PipelineError(RuntimeError):
    pass


def ensure_pinned_upstream(url: str, commit: str, project_root: Path) -> Path:
    """确保 upstream-cache/upstream-<commit12> 存在且 HEAD 严格等于 pinned。

    优先升格 analysis 浅克隆(HEAD 已对);否则完整 clone + detach。"""
    project_root = Path(project_root)
    dest = project_root / "upstream-cache" / f"upstream-{commit[:12]}"

    def _head(p: Path) -> str:
        r = subprocess.run(["git", "-C", str(p), "rev-parse", "HEAD"],
                           capture_output=True, text=True)
        return r.stdout.strip()

    if dest.is_dir():
        if _head(dest) != commit:
            raise PipelineError(f"钉版树 HEAD 与契约不符:{dest}")
        return dest
    analysis = project_root / "upstream-cache" / "analysis"
    if analysis.is_dir():
        for cand in analysis.iterdir():
            if cand.is_dir() and _head(cand) == commit:
                shutil.copytree(cand, dest)
                return dest
    r = subprocess.run(["git", "clone", "--quiet", url, str(dest)],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise PipelineError(f"clone 失败:{r.stderr[-300:]}")
    r = subprocess.run(["git", "-C", str(dest), "checkout", "-q", "--detach", commit],
                       capture_output=True, text=True)
    if r.returncode != 0 or _head(dest) != commit:
        raise PipelineError(f"checkout {commit[:12]} 失败:{r.stderr[-200:]}")
    return dest


def _reference_pins(project_root: Path, task_id: str) -> list[str]:
    lock = (Path(project_root) / "controls" / task_id / "reference"
            / "requirements.lock.txt")
    if not lock.is_file():
        return []
    return [ln.strip() for ln in lock.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def _build_preflight_venv(task_dir: Path, pins: list[str]) -> Path:
    """conformance 预检解释器:一次性 venv,装 reference 锁定集(联网)。"""
    venv = task_dir / "_preflight_venv"
    subprocess.run(["python3", "-m", "venv", str(venv)], check=True,
                   capture_output=True)
    py = venv / "bin" / "python"
    subprocess.run([str(py), "-m", "pip", "install", "--disable-pip-version-check",
                    "-q", "pytest", *pins], check=True, capture_output=True,
                   timeout=600)
    return py


def tool_build(
    draft_dir: Path,
    project_root: Path,
    *,
    bench_root: Path,
    dest_root: Path,
    run_real: bool = True,
    conformance_keywords: list[str] | None = None,
    batch: str = "EXPLORATORY_UNPREREGISTERED",
    setup_commands: list[list[str]] | None = None,   # 测试注入(E2E shim)
    wheelhouse_cmd: list[str] | None = None,          # 测试注入(跳过备轮)
) -> dict:
    """→ {task_id, stages: {...}, verdict, exported};任一门不过即返回
    (stages 记录到哪一步、为何停)。"""
    from repoproof.runner.host_guided import run_host_guided_cli

    project_root = Path(project_root)
    stages: dict = {}

    # 1) 人闸后的确认:D 闸 → 装配 → T 闸 → 冻结
    info = confirm_tool_draft(Path(draft_dir), project_root)
    task_id = info["task_id"]
    stages["confirm"] = {"task_id": task_id, "public": info["public"],
                         "held": info["held"]}

    draft = yaml.safe_load((Path(draft_dir) / "draft.yaml")
                           .read_text(encoding="utf-8"))
    sr = draft["source_repo"]

    # 2) 钉版上游 + conformance 选取(确定性)
    up = ensure_pinned_upstream(sr["url"], sr["resolved_commit"], project_root)
    kws = conformance_keywords or [sr["distribution"],
                                   (draft["tool"]["interface"]["input"]
                                    .get("format", "")).lower()]
    selected = select_upstream_tests(up, [k for k in kws if k])
    stages["conformance_selected"] = selected

    # 3) 物化(含预检:reference 锁定集建一次性解释器)
    pins = _reference_pins(project_root, task_id)
    task_dir = Path(project_root) / "tool_tasks" / task_id
    if task_dir.exists() or (Path(bench_root) / task_id).exists():
        raise PipelineError(
            f"物化目标已存在:{task_id}(改题面请先重出 draft → 新版本号)")
    conf_py = None
    if selected and pins:
        tmp_task = Path(project_root) / "tool_tasks"
        tmp_task.mkdir(exist_ok=True)
        conf_py = _build_preflight_venv(tmp_task / f"_{task_id}_pf", pins)
    try:
        contract = materialize_tool_task(
            project_root, Path(project_root) / "contracts" / f"{task_id}.yaml",
            out_root=Path(project_root) / "tool_tasks",
            host_copy_root=Path(bench_root),
            setup_commands=setup_commands,
            upstream_conformance=selected, conformance_python=conf_py)
    except ToolBridgeError as e:
        stages["materialize"] = {"ok": False, "error": str(e)}
        return {"task_id": task_id, "stages": stages, "verdict": "BLOCKED",
                "exported": None}
    finally:
        if conf_py is not None:
            shutil.rmtree(conf_py.parents[1], ignore_errors=True)
    stages["materialize"] = {"ok": True, "contract": str(contract)}

    # 3b) draft 束归档进任务区(真值留痕;移出 H9-a 扫描面 —— 束里的
    # 样例/期望与 oracle 逐字节同,留在 /tmp 真发必被残留闸拒,按设计)。
    # 时机在 materialize 成功之后:任何更早失败,束留原位供人改后重跑。
    archive = project_root / "tool_tasks" / "_drafts" / task_id
    if archive.exists():
        raise PipelineError(f"draft 归档位已存在:{archive}")
    archive.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(draft_dir), str(archive))
    stages["draft_archived"] = str(archive)

    # 4) wheelhouse 备轮(reference 锁定集 + 测量工具链)
    wheelhouse = Path(bench_root) / task_id / "wheelhouse"
    r = subprocess.run(
        wheelhouse_cmd or
        ["python3", "-m", "pip", "download", "--disable-pip-version-check", "-q",
         *pins, "pytest", "setuptools", "wheel", "-d", str(wheelhouse)],
        capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise PipelineError(f"wheelhouse 备轮失败:{r.stderr[-300:]}")
    stages["wheelhouse"] = {"wheels": len(list(wheelhouse.glob('*.whl')))}

    # 5) fake 彩排门:不 PASS 不许烧真预算
    fake = run_host_guided_cli(contract, project_root, fake="positive",
                               batch=batch)
    fk = (fake.get("report") or {})
    stages["rehearsal"] = {"verdict": fk.get("verdict"),
                           "run_id": fk.get("run_id"),
                           "gate_reasons": fk.get("gate_reasons")}
    if fk.get("verdict") != "PASS_ADAPTED":
        return {"task_id": task_id, "stages": stages,
                "verdict": f"REHEARSAL_{fk.get('verdict')}", "exported": None}

    if not run_real:
        return {"task_id": task_id, "stages": stages,
                "verdict": "REHEARSAL_PASS_ONLY", "exported": None}

    # 6) 真模型单发(provider 从 env;未配置由 preflight 如实拦)
    real = run_host_guided_cli(contract, project_root, fake=None, batch=batch)
    if real.get("blocked"):
        stages["real"] = real
        return {"task_id": task_id, "stages": stages,
                "verdict": "REAL_BLOCKED", "exported": None}
    rp = real.get("report") or {}
    stages["real"] = {"verdict": rp.get("verdict"),
                      "verdict_public": rp.get("verdict_public"),
                      "run_id": rp.get("run_id"),
                      "gate_reasons": rp.get("gate_reasons")}
    if rp.get("verdict") not in ("PASS_ADAPTED", "PASS_DIRECT"):
        return {"task_id": task_id, "stages": stages,
                "verdict": rp.get("verdict"), "exported": None}

    # 7) export + 注册
    dest = export_verified_tool(
        Path(project_root) / "runs" / rp["run_id"],
        host_contract_path=contract,
        tool_contract_path=Path(project_root) / "contracts" / f"{task_id}.yaml",
        dest_root=Path(dest_root))
    register_tool(Path(dest_root), dest, run_id=rp["run_id"],
                  exported_at=datetime.datetime.now(datetime.UTC)
                  .strftime("%Y-%m-%dT%H:%M:%SZ"))
    stages["export"] = {"dest": str(dest)}
    return {"task_id": task_id, "stages": stages,
            "verdict": rp.get("verdict_public") or rp.get("verdict"),
            "exported": str(dest)}
