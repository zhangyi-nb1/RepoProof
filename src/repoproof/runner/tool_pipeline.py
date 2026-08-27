"""LOCAL-TOOL 单命令旅程编排(M3-a · RFC-010 §六 M3/方向文档 §7)。

两段式(单命令 ≠ 零交互 —— §7 的形态是"少量关键确认"):

    repoproof tool add   → intake + LLM 起草 → draft 束 + 人的待办清单
                           (人:放样例真值 / 审 statement 与 reference /
                            定工具名 —— 全部 [G1] 人闸职责)
    repoproof tool build → confirm(D+装配+T 闸冻结) → 钉版上游确保 →
                           conformance 选取+物化预检 → wheelhouse 备轮 →
                           fake 彩排(必须 PASS 才许烧真预算) → 真模型 →
                           export + 注册表登记(运营态 REVIEW_REQUIRED)

编排只做**顺序与门**,每步的判定权仍在各自组件(闸门语义零改动);
任何一步失败即停、如实返回该步的结论 —— 编排不吞错、不重试真发。
"""

from __future__ import annotations

import datetime
import re
import shutil
import subprocess
from pathlib import Path

import yaml

from repoproof.adoption.assembly.tool_assembler import next_tool_task_id
from repoproof.adoption.intake.tool_confirm import (
    check_draft_complete,
    confirm_tool_draft,
)
from repoproof.adoption.intake.upstream_conformance import select_upstream_tests
from repoproof.runner.tool_export import (
    ToolExportError,
    install_verified_tool,
    preflight_tool_install,
)
from repoproof.runner.tool_host_bridge import ToolBridgeError, materialize_tool_task
from repoproof.runner.tool_release import (
    ReleaseLedgerError,
    is_historical_tool_ready,
    operational_status,
)


class PipelineError(RuntimeError):
    pass


def tool_build_completed(result: dict, *, rehearsal_only: bool) -> bool:
    """Return whether a CLI build reached its declared completion boundary."""

    if rehearsal_only:
        return result.get("verdict") == "REHEARSAL_PASS_ONLY"
    return bool(
        result.get("exported")
        and is_historical_tool_ready(result.get("historical_verdict"))
    )


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


def _upstream_version(upstream_dir: Path) -> str:
    """从**钉版上游树自己**读声明版本(pyproject / setup.cfg / PKG-INFO)。

    用树里的版本而不是 PyPI 上的最新版:pin 的语义是"就这一版",
    去解析最新版等于把钉版偷偷放开。
    """
    py = Path(upstream_dir) / "pyproject.toml"
    if py.is_file():
        try:
            import tomllib
            data = tomllib.loads(py.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        v = ((data.get("project") or {}).get("version")
             or (((data.get("tool") or {}).get("poetry") or {}).get("version")))
        if isinstance(v, str) and v.strip():
            return v.strip()
    cfg = Path(upstream_dir) / "setup.cfg"
    if cfg.is_file():
        m = re.search(r"^\s*version\s*=\s*(\S+)\s*$",
                      cfg.read_text(encoding="utf-8", errors="replace"), re.MULTILINE)
        if m:
            return m.group(1).strip()
    for info in sorted(Path(upstream_dir).glob("*.egg-info/PKG-INFO")):
        m = re.search(r"^Version:\s*(\S+)\s*$",
                      info.read_text(encoding="utf-8", errors="replace"), re.MULTILINE)
        if m:
            return m.group(1).strip()
    return ""


def _norm_dist_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", (name or "").strip()).lower()


def resolve_upstream_pins(project_root: Path, task_id: str, *,
                          distribution: str, upstream_dir: Path) -> list[str]:
    """备轮用的 pin 集合 —— **必须含上游本体**,否则当场拒发。

    2026-08-28 实测(webcolors,三发白跑):`reference.lock.txt` 在人务清单
    里写着"(可选)",而它一旦缺席,`_reference_pins` **静默返回空** ——
    wheelhouse 只装 pytest 那套,会话里根本没有上游,于是每条能力测试都
    炸 `ModuleNotFoundError`,再被包装成 `DEPENDENCY_ERROR` +
    `REGRESSION_FAILURE`,在**三轮修复之后**才浮出来,离病因十万八千里。
    "可选"是假的:不写就必崩。

    两件事:①锁文件缺上游时,从**钉版上游树自己**声明的版本派生
    `dist==version`(陷阱消灭);②派生不出来就抛错,绝不建一个注定装不上
    上游的 wheelhouse(静默降级 → 当场拒发)。
    """
    pins = _reference_pins(project_root, task_id)
    want = _norm_dist_name(distribution)
    if not want:
        return pins
    if any(_norm_dist_name(re.split(r"[=<>!~\[]", p, maxsplit=1)[0]) == want for p in pins):
        return pins
    version = _upstream_version(upstream_dir)
    if not version:
        raise PipelineError(
            f"备轮缺上游 {distribution!r}:controls/{task_id}/reference/"
            "requirements.lock.txt 没有它,钉版树里也读不出声明版本。"
            f"请在 draft 束的 reference.lock.txt 写上 `{distribution}==<版本>`"
            " —— 没有它,会话里 import 不到上游,所有能力测试都会以 "
            "ModuleNotFoundError 失败。")
    return [*pins, f"{distribution}=={version}"]


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
    agent_backend: str = "mini-swe",
    conformance_keywords: list[str] | None = None,
    batch: str = "EXPLORATORY_UNPREREGISTERED",
    setup_commands: list[list[str]] | None = None,   # 测试注入(E2E shim)
    wheelhouse_cmd: list[str] | None = None,          # 测试注入(跳过备轮)
) -> dict:
    """→ {task_id, stages, verdict, historical_verdict,
    operational_status, exported};任一门不过即返回(stages 记录到
    哪一步、为何停)。兼容字段 ``verdict`` 仍表示历史验证结论。
    """
    from repoproof.runner.host_guided import run_host_guided_cli

    if agent_backend not in {"codex-cli", "mini-swe"}:
        raise PipelineError(
            f"Product Mode 不支持 agent backend={agent_backend!r};"
            "可选 codex-cli / mini-swe"
        )

    project_root = Path(project_root)
    draft_dir = Path(draft_dir)
    stages: dict = {}

    draft_path = draft_dir / "draft.yaml"
    draft = (
        yaml.safe_load(draft_path.read_text(encoding="utf-8"))
        if draft_path.is_file()
        else None
    )
    predicted_task_id: str | None = None
    if run_real and isinstance(draft, dict):
        # D checks are read-only.  Once they pass, reject an impossible or
        # unsafe install before confirm freezes a new task version, and long
        # before either rehearsal or real-model budget is spent.
        if not check_draft_complete(draft, draft_dir):
            try:
                predicted_task_id = next_tool_task_id(
                    project_root, draft["tool"]["name"]
                )
                current = preflight_tool_install(
                    Path(dest_root), draft["tool"]["name"], predicted_task_id
                )
            except (ToolExportError, ReleaseLedgerError, OSError, ValueError) as exc:
                stages["install_preflight"] = {"ok": False, "error": str(exc)}
                raise PipelineError(f"工具安装预检失败:{exc}") from exc
            stages["install_preflight"] = {
                "ok": True,
                "mode": "upgrade" if current is not None else "first_install",
                "previous_task_id": current.get("task_id") if current else None,
            }

    # 0b) 执行路由(RFC-013):draft 束带已确认 plan.yaml → 按计划路线;
    # 无 plan = 向后兼容缺省 AGENT_ADAPT。DIRECT_WRAP 在此处即执法
    # assert_may_execute(未确认/被改动的计划连装配都不许进)。
    route = "AGENT_ADAPT"
    adapter_src: str | None = None
    plan_obj = None
    plan_path = draft_dir / "plan.yaml"
    if plan_path.is_file():
        from repoproof.adoption.delivery.direct_adapter import (
            compile_direct_adapter,
            derive_adapter_spec,
        )
        from repoproof.adoption.planning.capability_plan import (
            CapabilityPlanV1,
            assert_may_execute,
            assert_plan_matches_source,
        )

        plan_obj = CapabilityPlanV1.model_validate(
            yaml.safe_load(plan_path.read_text(encoding="utf-8")))
        assert_may_execute(plan_obj)
        # plan 与 draft 上游身份绑定:拿别的仓/别的版本的计划冒充即拒
        # (外部审计 P0 实证的补丁之二)。
        if isinstance(draft, dict):
            _sr = draft.get("source_repo") or {}
            assert_plan_matches_source(
                plan_obj, url=str(_sr.get("url") or ""),
                commit=str(_sr.get("resolved_commit") or ""))
        route = plan_obj.implementation_route
        if route == "DIRECT_WRAP":
            spec = derive_adapter_spec(plan_obj)
            adapter_src = compile_direct_adapter(spec)
            stages["route"] = {"route": route, "locator": spec.locator,
                               "agent_invoked": False,
                               "plan_sha256": plan_obj.plan_sha256}
        else:
            stages["route"] = {"route": route, "agent_invoked": True,
                               "plan_sha256": plan_obj.plan_sha256}

    # 1) 人闸后的确认:D 闸 → 装配 → T 闸 → 冻结
    try:
        info = confirm_tool_draft(draft_dir, project_root)
    except ValueError as exc:
        raise PipelineError(f"任务版本谱系或草稿装配无效:{exc}") from exc
    task_id = info["task_id"]
    if predicted_task_id is not None and task_id != predicted_task_id:
        raise PipelineError(
            f"安装预检 task_id={predicted_task_id} 与冻结结果 {task_id} 分叉"
        )
    stages["confirm"] = {"task_id": task_id, "public": info["public"],
                         "held": info["held"]}

    if not isinstance(draft, dict):
        draft = yaml.safe_load(draft_path.read_text(encoding="utf-8"))
    sr = draft["source_repo"]

    # 2) 钉版上游 + conformance 选取(确定性)
    up = ensure_pinned_upstream(sr["url"], sr["resolved_commit"], project_root)
    kws = conformance_keywords or [sr["distribution"],
                                   (draft["tool"]["interface"]["input"]
                                    .get("format", "")).lower()]
    selected = select_upstream_tests(up, [k for k in kws if k])
    stages["conformance_selected"] = selected

    # 2b) DIRECT_WRAP:受信模板 adapter + 确定 lock **在装配骨架里落位**
    # (materialize 之前 —— 任务包/bench 副本由骨架拷出)。S0 即完整交付,
    # agent 零 diff,completion gate 的既有 PASS_DIRECT 语义自然成立。
    pins = resolve_upstream_pins(project_root, task_id,
                                 distribution=sr["distribution"], upstream_dir=up)
    if route == "DIRECT_WRAP":
        skel = (Path(project_root) / "fixtures"
                / f"tool_skeleton_{draft['tool']['name']}")
        pkg = str(draft["tool"]["name"]).replace("-", "_")
        impl_p = skel / "src" / pkg / "impl.py"
        if not impl_p.is_file():
            raise PipelineError(f"DIRECT_WRAP 找不到骨架能力位:{impl_p}")
        if adapter_src is None:    # route=DIRECT_WRAP 时路由段必已编译;防失配
            raise PipelineError("DIRECT_WRAP 路由却没有已编译的适配器源 —— 路由段状态失配")
        impl_p.write_text(adapter_src, encoding="utf-8")
        (skel / "requirements.lock.txt").write_text(
            ("\n".join(pins) + "\n") if pins
            else "# DIRECT_WRAP:上游经会话环境提供,无第三方 pins\n",
            encoding="utf-8")
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
    # 事后核账只在**真备轮**时成立:`wheelhouse_cmd` 是测试注入口(E2E 用
    # `true` 跳过下载、改由 PYTHONPATH shim 提供上游),那种情况下这里没有
    # 东西可核 —— 核一个没发生的动作只会得出假结论。生产侧无人传此参数。
    downloaded = ([f.name for f in wheelhouse.iterdir() if f.is_file()]
                  if wheelhouse_cmd is None else [])
    want = _norm_dist_name(sr["distribution"]) if wheelhouse_cmd is None else ""
    if want and not any(_norm_dist_name(n.split("-")[0]) == want for n in downloaded):
        # 事后核账:pip 说成功不等于上游真躺在那儿。不量一次就等于假设。
        raise PipelineError(
            f"备轮完成但 wheelhouse 里没有上游 {sr['distribution']!r}:"
            f"{sorted(downloaded)[:8]} —— 会话将 import 不到上游,拒绝继续。")
    stages["wheelhouse"] = {"wheels": len(list(wheelhouse.glob('*.whl'))),
                            "upstream_present": True}

    # 5/6) 路由执行器(Gate 3):两条路线共享前段(confirm/pin/物化/备轮)
    # 与后段(投影/export/注册);中段按 Capability Plan 分道。
    if route == "DIRECT_WRAP":
        # 确定性快路径:骨架已含受信模板交付,零 Agent、零真发 ——
        # 一发 fake="direct"(零动作提交)走完整验证链;零 diff + 全门过
        # = PASS_DIRECT(completion gate 既有语义,零改动)。
        d = run_host_guided_cli(contract, project_root, fake="direct",
                                batch=batch)
        if d.get("blocked"):
            stages["direct"] = d
            return {"task_id": task_id, "stages": stages,
                    "verdict": "DIRECT_BLOCKED", "exported": None}
        rp = d.get("report") or {}
        stages["direct"] = {"verdict": rp.get("verdict"),
                            "run_id": rp.get("run_id"),
                            "gate_reasons": rp.get("gate_reasons"),
                            "agent_invoked": False, "route": route}
        # DIRECT_WRAP 失败不得自动切 AGENT_ADAPT(RFC-013 §4):换路线
        # 必须重新生成并确认计划。
    else:
        # 5) fake 彩排门:不 PASS 不许烧真预算
        fake = run_host_guided_cli(contract, project_root, fake="positive",
                                   batch=batch)
        fk = (fake.get("report") or {})
        stages["rehearsal"] = {"verdict": fk.get("verdict"),
                               "run_id": fk.get("run_id"),
                               "gate_reasons": fk.get("gate_reasons")}
        if fk.get("verdict") != "PASS_ADAPTED":
            return {"task_id": task_id, "stages": stages,
                    "verdict": f"REHEARSAL_{fk.get('verdict')}",
                    "exported": None}

        if not run_real:
            return {"task_id": task_id, "stages": stages,
                    "verdict": "REHEARSAL_PASS_ONLY", "exported": None}

        # 6) 真模型单发(provider 从 env;未配置由 preflight 如实拦)
        real = run_host_guided_cli(
            contract,
            project_root,
            fake=None,
            batch=batch,
            backend=agent_backend,
        )
        if real.get("blocked"):
            stages["real"] = real
            return {"task_id": task_id, "stages": stages,
                    "verdict": "REAL_BLOCKED", "exported": None}
        rp = real.get("report") or {}
        stages["agent_backend"] = {
            "id": agent_backend,
            "product_mode_only": agent_backend == "codex-cli",
            "benchmark_eligible": False,
        }
    # Gate 2:修复循环事实的产品投影(纯读取侧派生,历史/新 run 同函,
    # 不回写 report 与任何台账)。两条路线共用。
    from repoproof.adoption.repair.failure_assessment import (
        assess_report,
        derive_repair_metrics,
    )

    proj_key = "direct" if route == "DIRECT_WRAP" else "real"
    metrics = derive_repair_metrics(rp)
    stages[proj_key] = {**stages.get(proj_key, {}),
                        "verdict": rp.get("verdict"),
                        "verdict_public": rp.get("verdict_public"),
                        "run_id": rp.get("run_id"),
                        "gate_reasons": rp.get("gate_reasons"),
                        "repair_metrics": metrics,
                        "product_stop_code": metrics["product_stop_code"]}
    expected = ("PASS_DIRECT",) if route == "DIRECT_WRAP" \
        else ("PASS_ADAPTED", "PASS_DIRECT")
    if rp.get("verdict") not in expected:
        stages[proj_key]["failure_assessment"] = assess_report(rp).model_dump()
        return {"task_id": task_id, "stages": stages,
                "verdict": rp.get("verdict"), "exported": None}

    # 7) export + 注册
    historical_verdict = rp.get("verdict_public") or rp.get("verdict")
    try:
        dest = install_verified_tool(
            Path(project_root) / "runs" / rp["run_id"],
            host_contract_path=contract,
            tool_contract_path=Path(project_root) / "contracts" / f"{task_id}.yaml",
            dest_root=Path(dest_root),
            exported_at=datetime.datetime.now(datetime.UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        )
    except (ToolExportError, ReleaseLedgerError, OSError, ValueError) as exc:
        stages["export"] = {"ok": False, "error": str(exc)}
        raise PipelineError(f"工具安装结算失败:{exc}") from exc
    release_status = operational_status(
        Path(dest_root), dest.name, task_id=task_id
    )
    stages["export"] = {
        "dest": str(dest),
        "historical_verdict": historical_verdict,
        "operational_status": release_status,
    }
    return {"task_id": task_id, "stages": stages,
            "verdict": historical_verdict,
            "historical_verdict": historical_verdict,
            "operational_status": release_status,
            "exported": str(dest)}
