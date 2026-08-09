"""宿主级 GUIDED 运行驱动(TESTPLAN-V2 Phase 1,T1+ 形态;RFC-009 §六)。

样例管线(guided_repair.py,Docker+adaptation 区)不动;本模块是宿主级
形态的对应物:agent 直接在**宿主快照树内**工作(editable_zones=host),
执行后端 = LocalWorktreeBackend(模式 L),快照/回滚 = 会话内 git。

链条(每步与 TESTPLAN 条款对应):

    HostContract 加载(冻结 YAML,sha 入 trace)
    → 保护目录指纹 pre(§4-6)
    → 会话装配:宿主快照(排除+替身,§4-5)+ PII 出口扫描必须 0 命中
      + 上游固定快照 + 公开测试入 host 树 + oracle 会话外持有(哈希守护)
    → 会话内 git S0 基线提交(快照/回滚/diff 计量的锚)
    → per-run venv **重建**(冻结 wheelhouse,PIP_NO_INDEX;预注册教训:
      venv 不可复制)+ 合成语料重建索引
    → Host Baseline Gate:pytest 全量不达基线 → BLOCKED 零预算(§4-3)
    → guided ≤max_rounds 轮(RepairLoop 编排;公开测试+宿主回归每轮全量,
      失败→FailurePacket;劣化→git 回滚到最佳)
    → 冻结适配 = git diff S0..best(patch 预算核查)
    → 独立验证:隐藏 oracle(会话外路径)/宿主回归(不降于基线)/Policy
      (oracle+上游+公开测试三树不变、因果链、token/patch 预算)
    → 全过 → clean_adoption 重放:全新会话 + git apply + **从修改后的
      requirements.txt 重建 venv**(依赖必须被声明,否则重放如实失败)
    → Completion Gate 判定 → 保护目录指纹 post 对账
    → benchmarks/v2/runs.jsonl 记账(§9;BLOCKED 也记)。

循环永不宣布成功;最终结论只出自 Completion Gate。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from repoproof.adoption.repair.failure_packet import FailurePacket, build_failure_packets
from repoproof.adoption.repair.repair_budget import RepairBudget
from repoproof.adoption.repair.repair_loop import RepairLoop, RoundResult, full_score
from repoproof.agents.provider_gate import PreflightResult, ProviderConfig
from repoproof.domain.models import (
    AdaptationManifest,
    Budgets,
    VerificationResult,
    sha256_bytes,
    sha256_file,
)
from repoproof.execution.local_worktree_backend import LocalWorktreeBackend
from repoproof.harness.host_guard import (
    HostGuardError,
    is_protected,
    snapshot_protected,
    verify_protected_unchanged,
)
from repoproof.harness.host_snapshot import prepare_host_snapshot, scan_for_pii
from repoproof.harness.oracle_guard import hash_tree, make_read_only, trees_equal
from repoproof.harness.trace import verify_chain
from repoproof.persistence.bench_records import append_run
from repoproof.persistence.run_store import FileRunStore
from repoproof.runner.guided_repair import (
    SCOPE_MARKER,
    RepairRoundRecord,
    extract_scope_change,
    render_packets,
)
from repoproof.verification import completion_gate
from repoproof.verification.junit import parse_junit_xml
from repoproof.verification.verifiers import (
    REPLAY_MODE_CLEAN,
    parse_pytest,
    policy_result,
    replay_result,
)

_ROUND_HEADER = (
    "\n\n==== GUIDED REPAIR ROUND {idx}/{max_rounds} ====\n"
    "This is a bounded repair round on the SAME host working tree (the best\n"
    "state so far has been restored if an earlier round regressed). Address\n"
    "the failure packets below; they summarise the PUBLIC acceptance tests\n"
    "and the host regression suite only. If — and only if — the task cannot\n"
    "proceed without a scope change (new large dependency, network access,\n"
    "changing success criteria, touching forbidden paths), print one line\n"
    "starting with `{marker}` followed by the reason, then submit.\n"
    "Never invent test results.\n"
)


# --------------------------------------------------------------- 冻结契约
class HostInfo(BaseModel):
    repo: str
    commit: str
    copy_path: str
    baseline_manifest: str = "HOST_BASELINE_MANIFEST.json"
    regression_command: list[str]
    regression_baseline: str = ""


class HostSourceRepo(BaseModel):
    url: str
    resolved_commit: str
    distribution: str
    import_module: str
    license: str = ""


class HostRequirement(BaseModel):
    id: str
    text: str


class HostCapability(BaseModel):
    statement: str
    requirements: list[HostRequirement]


class HostConstraints(BaseModel):
    editable_zones: list[str] = Field(default_factory=lambda: ["."])
    forbidden: list[str] = Field(default_factory=list)
    network_at_test_time: bool = False


class HostBudgets(BaseModel):
    """semantics="total":calls/commands/tokens 为全 run 上限(v1);
    semantics="per_round":上述三类**每轮重置**(2026-08-09 用户决定,
    动机=总额语义下首轮烧光额度、修复轮空转)。patch/wall 恒为全 run。"""

    semantics: str = "total"
    max_rounds: int
    max_model_calls: int
    max_commands: int
    max_patch_files: int
    max_patch_lines: int
    max_wall_time_minutes: int
    max_input_tokens_total: int
    max_output_tokens_total: int

    @property
    def per_round(self) -> bool:
        return self.semantics == "per_round"

    def as_budgets(self) -> Budgets:
        """映射到既有 Budgets 模型(policy/token 复用的公共语言)。"""
        return Budgets(
            max_agent_steps=self.max_model_calls,
            max_wall_time_minutes=self.max_wall_time_minutes,
            max_patch_files=self.max_patch_files,
            max_patch_lines=self.max_patch_lines,
            max_input_tokens_total=self.max_input_tokens_total,
            max_output_tokens_total=self.max_output_tokens_total,
        )


class HostAcceptance(BaseModel):
    public_test_command: list[str]
    hidden_oracle_command: list[str]


class HostContract(BaseModel):
    """宿主级任务契约(benchmarks/v2/tasks/*/contract.yaml,冻结对象)。"""

    task_id: str
    task_version: str
    kind: str
    host: HostInfo
    source_repo: HostSourceRepo
    capability: HostCapability
    constraints: HostConstraints = HostConstraints()
    budgets: HostBudgets
    acceptance: HostAcceptance
    task_shape: dict = Field(default_factory=dict)
    failure_taxonomy_expected: list[str] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> tuple["HostContract", str]:
        raw = Path(path).read_bytes()
        data = yaml.safe_load(raw)
        contract = cls.model_validate(data)
        if contract.kind != "host_integrated":
            raise ValueError(f"kind 必须是 host_integrated,得到 {contract.kind!r}")
        return contract, sha256_bytes(raw)


class HostRunError(RuntimeError):
    pass


# --------------------------------------------------------------- 工具函数
def _expected_regression_passed(baseline: str) -> int:
    """'591 passed, 7 skipped, 0 failed' → 591(回归判据=不降于基线)。"""
    import re

    m = re.search(r"(\d+)\s+passed", baseline)
    return int(m.group(1)) if m else 0


def integrity_scope(project_root: Path) -> list[str]:
    """指纹对账集 = 保护目录去掉 RepoProof 自身(§4-6 主目录语义)。

    RepoProof 仍在写护栏黑名单(会话根不得落于其中),但 run 合法写
    自己的 runs/ 与 benchmarks/,对其拍指纹必然自误报。"""
    import os as _os

    from repoproof.harness.host_guard import protected_dirs

    self_norm = _os.path.realpath(str(project_root)).lower().rstrip("/")
    return [d for d in protected_dirs() if d != self_norm]


def _read_substitutes(host_copy: Path) -> dict[str, str]:
    """替身内容取自副本内文件(引导手册保证其为合成;PII 扫描兜底)。

    快照默认排除这些文件后再写入替身——直接用副本里经 591 基线锚定的
    精细替身,而非 host_snapshot 的极简默认(后者会挂档案格式测试)。"""
    from repoproof.harness.host_snapshot import DEFAULT_SUBSTITUTES

    subs: dict[str, str] = {}
    for name, fallback in DEFAULT_SUBSTITUTES.items():
        src = host_copy / name
        subs[name] = src.read_text(encoding="utf-8") if src.exists() else fallback
    return subs


def build_host_prompt(contract: HostContract, *, wheel_note: str) -> str:
    """契约 → agent 提示的唯一投影(不含任何 oracle/隐藏信息)。"""
    cap = contract.capability
    req_lines = [f"[{r.id}] {' '.join(r.text.split())}" for r in cap.requirements]
    forbidden = [f"- {' '.join(f.split())}" for f in contract.constraints.forbidden]
    b = contract.budgets
    parts = [
        "You are integrating a capability from a pinned open-source repo into a\n"
        "REAL host project (OfferClaw). You work directly inside the host tree.",
        f"GOAL\n{cap.statement.strip()}",
        "REQUIREMENTS (each is verified)\n" + "\n".join(req_lines),
        "YOUR ENVIRONMENT\n"
        "- You start in the host project root (a disposable snapshot; git is\n"
        "  available and the baseline is already committed).\n"
        "- ../upstream          read-only pinned source checkout of "
        f"{contract.source_repo.distribution} @ {contract.source_repo.resolved_commit[:12]}\n"
        "- ./public_tests       PUBLIC acceptance tests — run them yourself:\n"
        "    .venv/bin/python -m pytest public_tests/ -q\n"
        "- ./.venv              host virtualenv with all host deps preinstalled\n"
        "- ./tests              host regression suite (MUST stay green):\n"
        "    .venv/bin/python -m pytest tests/ -q\n"
        f"- pip is OFFLINE: it resolves ONLY from a local wheel index ({wheel_note}).\n"
        "  Install the target library with .venv/bin/pip install <dist>; resolve any\n"
        "  dependency conflict yourself (diagnose, then pin what you need).\n"
        "- DECLARE new dependencies in requirements.txt with working version pins:\n"
        "  final acceptance rebuilds a CLEAN environment strictly from\n"
        "  requirements.txt + your committed files; undeclared deps will fail there.",
        "HARD RULES\n" + "\n".join(forbidden) + "\n- Do not modify ./public_tests or ../upstream.",
        "BUDGETS\n"
        + (f"- PER ROUND (reset each round): model calls {b.max_model_calls}, "
           f"executed commands {b.max_commands}, "
           f"input/output token allowance {b.max_input_tokens_total}/{b.max_output_tokens_total}; "
           if b.per_round else
           f"- model calls: {b.max_model_calls} total; executed commands: {b.max_commands} total; ")
        + f"patch budget: {b.max_patch_files} files / {b.max_patch_lines} lines (whole run); "
        f"wall time: {b.max_wall_time_minutes} minutes (whole run).\n"
        "Acceptance is judged AFTER you finish by additional tests you cannot see;\n"
        "there is no partial credit for claims.\n"
        "When done, submit with: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
    ]
    return "\n\n".join(parts)


class _Session:
    """一次装配好的宿主会话(主 run 与 clean replay 各一个)。"""

    def __init__(self, backend: LocalWorktreeBackend, session: str, root: Path,
                 venv_py: str) -> None:
        self.backend = backend
        self.id = session
        self.root = root
        self.venv_py = venv_py  # 会话内 venv python(相对 host 的路径)


class HostGuidedRunner:
    """宿主级 guided runner。所有 exec 走 LocalWorktreeBackend(净化环境/
    假 HOME/护栏/cwd 钉死焊在后端);oracle 路径永不进入会话与 agent 环境。"""

    def __init__(
        self,
        contract_path: Path,
        project_root: Path,
        *,
        runs_root: Path | None = None,
        wheelhouse: Path | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.contract_path = Path(contract_path)
        self.contract, self.contract_sha = HostContract.load(self.contract_path)
        self.task_dir = self.contract_path.parent
        self.host_copy = Path(self.contract.host.copy_path).expanduser().resolve()
        if is_protected(self.host_copy):
            raise HostGuardError(f"宿主副本命中受保护目录:{self.host_copy}")
        if not self.host_copy.is_dir():
            raise HostRunError(f"宿主副本不存在:{self.host_copy}")
        self.oracle_src = self.task_dir / "oracle"
        self.public_tests_src = self.task_dir / "public_tests"
        for p in (self.oracle_src, self.public_tests_src):
            if not p.is_dir():
                raise HostRunError(f"任务包目录缺失:{p}")
        self.upstream_src = (
            self.project_root / "upstream-cache"
            / f"upstream-{self.contract.source_repo.resolved_commit[:12]}"
        )
        self.wheelhouse = Path(
            wheelhouse
            or Path("~/RepoProofBench").expanduser()
            / f"wheelhouse-offerclaw-{self.contract.host.commit[:7]}"
        ).expanduser().resolve()
        self.run_id = f"{self.contract.task_id}-{time.strftime('%Y%m%d-%H%M%S')}"
        self.store = FileRunStore((runs_root or self.project_root / "runs") / self.run_id)
        self.budgets = self.contract.budgets.as_budgets()
        self.timings: dict[str, float] = {}
        self._verify_static_resources()

    # ------------------------------------------------------------ 静态核验
    def _verify_static_resources(self) -> None:
        if not self.upstream_src.is_dir():
            raise HostRunError(
                f"上游固定快照缺失:{self.upstream_src}(引导期先克隆并 detach)")
        head = subprocess.run(  # noqa: S603 — 固定 argv,只读查询
            ["git", "-C", str(self.upstream_src), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False)
        if head.stdout.strip() != self.contract.source_repo.resolved_commit:
            raise HostRunError(
                f"上游快照 HEAD {head.stdout.strip()[:12]} != 契约 pinned "
                f"{self.contract.source_repo.resolved_commit[:12]}")
        if not self.wheelhouse.is_dir():
            raise HostRunError(f"冻结 wheelhouse 缺失:{self.wheelhouse}")
        manifest = self.wheelhouse / "wheelhouse_manifest.json"
        if not manifest.is_file():
            raise HostRunError(f"wheelhouse manifest 缺失:{manifest}")
        self.env_baseline_hash = json.loads(
            manifest.read_text(encoding="utf-8"))["env_baseline_hash"]

    # ------------------------------------------------------------ 会话装配
    def _git(self, s: _Session, *args: str, timeout_s: int = 120):
        return s.backend.exec(
            s.id,
            ["git", "-c", "user.name=repoproof-harness",
             "-c", "user.email=harness@repoproof.invalid",
             "-c", "commit.gpgsign=false", *args],
            timeout_s=timeout_s, workdir="host")

    def _assemble(self, backend: LocalWorktreeBackend, label: str) -> _Session:
        """装配一个会话:快照+替身+PII 扫描+上游+公开测试+S0 提交。"""
        ev = self.store.append_event
        session = backend.start(name_prefix=f"rp-host-{label}", env={
            "PIP_NO_INDEX": "1",
            "PIP_FIND_LINKS": str(self.wheelhouse),
            # A 类只读缓存共享(TESTPLAN §4-3):共享 + 离线开关;假 HOME 不变
            "MODELSCOPE_CACHE": str(Path("~/.cache/modelscope").expanduser()),
            "PYTHONHASHSEED": "0",
        })
        root = backend.session_root(session)
        snap = prepare_host_snapshot(
            self.host_copy, root / "host",
            substitutes=_read_substitutes(self.host_copy))
        pii = scan_for_pii(root / "host")
        if pii:
            backend.destroy(session)
            raise HostRunError(f"PII 出口扫描命中 {len(pii)} 条,拒绝开跑:{pii[:3]}")
        shutil.copytree(self.upstream_src, root / "upstream", symlinks=False,
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(self.public_tests_src, root / "host" / "public_tests",
                        ignore=shutil.ignore_patterns("__pycache__"))
        s = _Session(backend, session, root, ".venv/bin/python")
        r = self._git(s, "add", "-A")
        if r.exit_code != 0:
            backend.destroy(session)
            raise HostRunError(f"git add 失败:{r.stderr.decode(errors='replace')[-300:]}")
        r = self._git(s, "commit", "-q", "--allow-empty", "-m", "rp-host S0 baseline")
        if r.exit_code != 0:
            backend.destroy(session)
            raise HostRunError(f"S0 提交失败:{r.stderr.decode(errors='replace')[-300:]}")
        head = self._git(s, "rev-parse", "HEAD")
        s.base_commit = head.stdout.decode().strip()  # type: ignore[attr-defined]
        ev(f"host.session_assembled.{label}", actor="harness", payload={
            "files": snap["files"], "excluded": len(snap["excluded"]),
            "substituted": snap["substituted"], "pii_hits": 0,
            "base_commit": s.base_commit,
        })
        return s

    def _build_env_in_session(self, s: _Session, *, timeout_s: int = 900) -> dict:
        """per-run venv 重建(预注册教训:绝不复制)+ 合成语料建索引。"""
        t0 = time.monotonic()
        r1 = s.backend.exec(s.id, ["python3", "-m", "venv", ".venv"],
                            timeout_s=300, workdir="host")
        if r1.exit_code != 0:
            raise HostRunError(f"venv 创建失败:{r1.stderr.decode(errors='replace')[-300:]}")
        r2 = s.backend.exec(
            s.id, [".venv/bin/pip", "install", "-q", "-r", "requirements.txt"],
            timeout_s=timeout_s, workdir="host")
        if r2.exit_code != 0:
            raise HostRunError(
                "宿主依赖安装失败(wheelhouse 不全?):"
                + (r2.stdout + r2.stderr).decode(errors="replace")[-500:])
        venv_s = round(time.monotonic() - t0, 1)
        t1 = time.monotonic()
        r3 = s.backend.exec(s.id, [".venv/bin/python", "rag_ingest.py"],
                            timeout_s=600, workdir="host")
        if r3.exit_code != 0:
            raise HostRunError(
                "合成语料建索引失败:" + (r3.stdout + r3.stderr).decode(errors="replace")[-500:])
        return {"venv_s": venv_s, "ingest_s": round(time.monotonic() - t1, 1)}

    # ------------------------------------------------------------ 基线与测量
    def _pytest_counts(self, s: _Session, xml_name: str, stdout: str) -> dict:
        """结构化计数:junitxml 优先(pytest 9 的 -q 失败态不打总结行,
        正则解析会漏计——首次冒烟实测),正则仅作兜底。"""
        xml_path = s.root / xml_name
        junit = parse_junit_xml(xml_path.read_bytes() if xml_path.exists() else None)
        if junit.get("junit_present") and not junit.get("junit_parse_error"):
            nodes = junit.get("nodes", [])
            failed = sorted(n["node_id"] for n in nodes if n["outcome"] in ("failed", "error"))
            passed = sum(1 for n in nodes if n["outcome"] == "passed")
            return {"passed_checks": passed, "failed_checks": len(failed),
                    "total_checks": len(nodes), "failed_tests": failed}
        return {k: v for k, v in parse_pytest(stdout).items()}

    def _run_regression(self, s: _Session, *, timeout_s: int = 900) -> dict:
        cmd = self.contract.host.regression_command
        argv = ([s.venv_py, *cmd[1:]] if cmd and cmd[0] == "python"
                else [s.venv_py, "-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider"])
        xml_name = "rp_reg.xml"
        (s.root / xml_name).unlink(missing_ok=True)
        argv = [*argv, "--junitxml", f"../{xml_name}"]
        res = s.backend.exec(s.id, argv, timeout_s=timeout_s, workdir="host")
        stdout = res.stdout.decode(errors="replace")
        return {"exit_code": res.exit_code, "stdout": stdout,
                **self._pytest_counts(s, xml_name, stdout)}

    def _run_public(self, s: _Session, *, timeout_s: int = 600) -> dict:
        xml_path = s.root / "rp_public.xml"
        if xml_path.exists():
            xml_path.unlink()
        res = s.backend.exec(
            s.id,
            [s.venv_py, "-m", "pytest", "public_tests/", "-q", "-p", "no:cacheprovider",
             "--junitxml", "../rp_public.xml"],
            timeout_s=timeout_s, workdir="host")
        junit = parse_junit_xml(xml_path.read_bytes() if xml_path.exists() else None)
        junit["pytest_exit"] = res.exit_code
        junit["stdout_tail"] = res.stdout.decode(errors="replace")[-600:]
        return junit

    def _run_oracle(self, s: _Session, oracle_snap: Path, *, timeout_s: int = 600) -> dict:
        """隐藏验收:oracle 目录在会话外(run_dir 下),路径只在 harness 手里。"""
        xml_name = "rp_oracle.xml"
        (s.root / xml_name).unlink(missing_ok=True)
        res = s.backend.exec(
            s.id,
            [s.venv_py, "-m", "pytest", str(oracle_snap), "-q", "-p", "no:cacheprovider",
             "--junitxml", f"../{xml_name}"],
            timeout_s=timeout_s, workdir="host",
            env={"PYTHONPATH": str(s.root / "host"),
                 "OFFERCLAW_HOST_ROOT": str(s.root / "host")})
        stdout = res.stdout.decode(errors="replace")
        return {"exit_code": res.exit_code, "stdout": stdout,
                **self._pytest_counts(s, xml_name, stdout)}

    def _baseline_gate(self, s: _Session) -> tuple[bool, dict]:
        """Host Baseline Gate(§4-3):不达基线 → BLOCKED 零预算。"""
        report: dict = {}
        reg = self._run_regression(s)
        expected = _expected_regression_passed(self.contract.host.regression_baseline)
        report["pytest"] = {
            "exit_code": reg["exit_code"], "passed": reg["passed_checks"],
            "failed": reg["failed_checks"], "expected_passed": expected,
        }
        ok = reg["exit_code"] == 0 and reg["passed_checks"] >= expected
        r = s.backend.exec(s.id, [s.venv_py, "verify_pipeline.py"],
                           timeout_s=300, workdir="host")
        report["verify_pipeline.py"] = {"exit_code": r.exit_code,
                                        "tail": r.stdout.decode(errors="replace")[-200:]}
        ok = ok and r.exit_code == 0
        # verify_docs 的基线判据 = "0 处未围栏裸露" 不退化(Manifest
        # known_deviations:chunks 交叉核对 112 vs 3538 因合成语料重建,
        # 其非零退出码是已知预期差异,不作门禁)——实测本判据由首次冒烟
        # BLOCKED 校准(2026-08-09)。
        rd = s.backend.exec(s.id, [s.venv_py, "verify_docs.py"],
                            timeout_s=300, workdir="host")
        rd_out = rd.stdout.decode(errors="replace")
        docs_ok = rd.exit_code == 0 or "0 处未围栏" in rd_out
        report["verify_docs.py"] = {"exit_code": rd.exit_code, "bare_ok": docs_ok,
                                    "tail": rd_out[-200:]}
        ok = ok and docs_ok
        rdoc = s.backend.exec(s.id, [s.venv_py, "doctor.py"], timeout_s=300, workdir="host")
        report["doctor"] = {"exit_code": rdoc.exit_code,
                            "tail": rdoc.stdout.decode(errors="replace")[-300:],
                            "note": "已知预期差异(chunks 口径/合成密钥 WARN),不作门禁"}
        return ok, report

    # ------------------------------------------------------------ diff 计量
    def _diff_stats(self, s: _Session, base: str, head: str = "HEAD") -> dict:
        num = self._git(s, "diff", "--numstat", f"{base}..{head}")
        files: list[str] = []
        lines = 0
        for row in num.stdout.decode(errors="replace").splitlines():
            parts = row.split("\t")
            if len(parts) != 3:
                continue
            a, d, path = parts
            files.append(path)
            lines += (int(a) if a.isdigit() else 0) + (int(d) if d.isdigit() else 0)
        return {"files": files, "total_files": len(files), "total_lines": lines}

    # ------------------------------------------------------------------ 主流程
    def run(
        self,
        provider: ProviderConfig | None,
        preflight: PreflightResult | None,
        *,
        model_factory: Callable[[dict], object] | None = None,
        run_order: int | str = "UNKNOWN",
        run_index: int | str = "UNKNOWN",
        keep_session: bool = False,
    ) -> dict:
        import os as _os

        ev = self.store.append_event
        t0 = time.monotonic()
        contract = self.contract
        b = contract.budgets
        model_name = provider.model_name if provider else "fake-scripted"
        ev("run.start", actor="runner", payload={
            "run_id": self.run_id, "mode": "host-guided-repair",
            "task_id": contract.task_id, "max_rounds": b.max_rounds,
            "execution_backend": "local-worktree",
            "env_baseline_hash": self.env_baseline_hash,
            "model": model_name,
            "provider_config_sha256": preflight.provider_config_sha256 if preflight else None,
        })
        ev("contract.frozen", actor="harness",
           payload={"task_id": contract.task_id, "sha256": self.contract_sha})

        integrity_before = snapshot_protected(integrity_scope(self.project_root))
        # 会话根不得落在保护目录内(RepoProof 自身也是保护目录),
        # 放 RepoProofBench 工作区;产物/trace 仍在 runs/<id>/ 下。
        sessions_root = Path("~/RepoProofBench/_sessions").expanduser() / self.run_id
        backend = LocalWorktreeBackend(sessions_root=sessions_root)
        oracle_snap = self.store.run_dir / "oracle_snapshot"
        shutil.copytree(self.oracle_src, oracle_snap,
                        ignore=shutil.ignore_patterns("__pycache__"))
        make_read_only(oracle_snap)
        oracle_before = hash_tree(oracle_snap)
        ev("oracle.hashed", actor="harness", payload={"files": len(oracle_before)})

        verdict_record: dict = {}
        missing_external: list[str] = []
        budget_exhausted: str | None = None
        agent_metrics: dict = {"model_calls": 0, "commands": 0, "denied": 0,
                               "exit_status": None, "cost": "UNKNOWN"}
        repair_summary: dict = {}
        records: list[RepairRoundRecord] = []
        public_by_round: list[int] = []
        regression_by_round: list[int] = []
        adaptation_manifest: AdaptationManifest | None = None
        cap = reg = pol = rep = None
        first_outcome: dict = {}
        s: _Session | None = None
        upstream_before: dict = {}
        public_before: dict = {}

        try:
            s = self._assemble(backend, "agent")
            upstream_before = hash_tree(s.root / "upstream")
            public_before = hash_tree(s.root / "host" / "public_tests")
            self.timings["env_build"] = 0.0
            t_env = time.monotonic()
            env_report = self._build_env_in_session(s)
            self.timings["env_build"] = round(time.monotonic() - t_env, 1)
            ev("host.env_built", actor="harness", payload=env_report)

            t_gate = time.monotonic()
            gate_ok, gate_report = self._baseline_gate(s)
            self.timings["baseline_gate_s"] = round(time.monotonic() - t_gate, 1)
            ev("host.baseline_gate", actor="harness",
               payload={"ok": gate_ok, **gate_report})
            if not gate_ok:
                missing_external.append("HOST_BASELINE_UNHEALTHY(会话内基线不达标,零预算)")
                raise _BaselineUnhealthy(gate_report)

            # ---------------- agent 阶段 ----------------
            from repoproof.agents.backend import MiniSWEBackend
            from repoproof.agents.repoproof_env import RepoProofEnvironment

            env = RepoProofEnvironment(
                backend=backend,           # 同形接口:session 字符串当 container
                container=s.id,
                store=self.store,
                command_timeout_s=Budgets().max_command_minutes * 60,
                command_budget=b.max_commands,          # 全 run 共享(跨轮)
                budget_visibility=False,
                model_call_limit=b.max_model_calls,
                wall_limit_s=b.max_wall_time_minutes * 60,
                default_cwd="host",
            )
            token_totals = {"in": 0, "out": 0, "seen": False}   # 累计(记账)
            round_scope: dict = {"cur": None}                    # 回调同时写当前轮
            make_budget_model = None
            if model_factory is None:
                assert provider is not None and preflight is not None
                _os.environ.setdefault("MSWEA_COST_TRACKING", "ignore_errors")
                _os.environ["OPENAI_API_KEY"] = provider.api_key
                _os.environ["OPENAI_API_BASE"] = provider.api_base
                _os.environ["OPENAI_BASE_URL"] = provider.api_base
                import litellm as _litellm
                from minisweagent.models.litellm_model import LitellmModel
                from minisweagent.models.litellm_textbased_model import LitellmTextbasedModel

                from repoproof.agents.token_budget import TokenBudgetedModel

                def _usage_cb(kwargs, completion_response, start_time, end_time):  # noqa: ANN001
                    usage = getattr(completion_response, "usage", None)
                    if usage:
                        pin = getattr(usage, "prompt_tokens", 0) or 0
                        pout = getattr(usage, "completion_tokens", 0) or 0
                        token_totals["seen"] = True
                        token_totals["in"] += pin
                        token_totals["out"] += pout
                        cur = round_scope["cur"]
                        if cur is not None:
                            cur["seen"] = True
                            cur["in"] += pin
                            cur["out"] += pout

                _litellm.success_callback = [_usage_cb]
                model_cls = (LitellmTextbasedModel
                             if preflight.action_protocol == "textbased" else LitellmModel)
                mkwargs = {"temperature": 0} if preflight.temperature == "0" else {}
                inner_model = model_cls(model_name=f"openai/{provider.model_name}",
                                        model_kwargs=mkwargs)

                def make_budget_model(totals_dict: dict) -> TokenBudgetedModel:
                    return TokenBudgetedModel(
                        inner=inner_model,
                        totals=totals_dict,
                        max_input_tokens=b.max_input_tokens_total,
                        max_output_tokens=b.max_output_tokens_total,
                        on_exhausted=lambda payload: ev("budget.exhausted", actor="harness",
                                                        payload=payload),
                    )

                model = make_budget_model(token_totals)   # total 语义:全程一个额度
            else:
                model = model_factory(token_totals)

            base_prompt = build_host_prompt(
                contract, wheel_note=f"wheelhouse {self.wheelhouse.name}")
            prompt_sha = sha256_bytes(base_prompt.encode())
            ev("agent.prompt", actor="harness",
               payload={"sha256": prompt_sha, "chars": len(base_prompt)})

            repair_dir = self.store.run_dir / "repair"
            repair_dir.mkdir(exist_ok=True)
            metrics_acc = {"model_calls": 0, "commands": 0, "denied": 0}
            last_exit: dict = {"status": None, "exhausted": None}
            per_round_usage: list[tuple[int, int]] = []
            expected_reg = _expected_regression_passed(contract.host.regression_baseline)
            t_agent = time.monotonic()

            def run_round(idx: int, packets: list[FailurePacket],
                          best_snapshot: str | None) -> RoundResult:
                t_round = time.monotonic()
                ev("repair.round.start", actor="harness",
                   payload={"round": idx, "packets": len(packets)})
                # 劣化轮回滚:恢复到最佳提交(venv/chroma 属 gitignore 不回滚,
                # 依赖状态单调——L 模式已知限制,重放会从声明重建作最终裁决)
                if best_snapshot:
                    cur = self._git(s, "rev-parse", "HEAD").stdout.decode().strip()
                    if cur != best_snapshot:
                        self._git(s, "reset", "--hard", best_snapshot)
                        self._git(s, "clean", "-fd")
                        ev("repair.restored_best", actor="harness",
                           payload={"round": idx, "snapshot": best_snapshot[:12]})
                base_hash = self._git(s, "rev-parse", "HEAD").stdout.decode().strip()

                if b.per_round:
                    # 每轮重置:calls/commands/tokens 各自满额起步(v2 语义)
                    round_totals = {"in": 0, "out": 0, "seen": False}
                    round_scope["cur"] = round_totals
                    round_model = (make_budget_model(round_totals)
                                   if make_budget_model else model)
                    env.commands_used = 0
                    env.command_budget = b.max_commands
                    step_limit = b.max_model_calls
                else:
                    round_totals = token_totals
                    round_model = model
                    step_limit = b.max_model_calls - metrics_acc["model_calls"]
                    if step_limit <= 0:
                        return RoundResult(
                            adapter_snapshot=base_hash, passed=0,
                            failed_nodes=["budget::model_calls"],
                            failure_details={}, diff_lines=0,
                            tokens_used=token_totals["in"] + token_totals["out"],
                            commands_used=0, collected_ok=False, within_budget=False)

                round_prompt = (
                    base_prompt
                    + _ROUND_HEADER.format(idx=idx, max_rounds=b.max_rounds,
                                           marker=SCOPE_MARKER)
                    + render_packets(packets)
                )
                mback = MiniSWEBackend(
                    model=round_model, env=env,
                    step_limit=step_limit,
                    cost_limit=Budgets().monetary_soft_cap_usd,
                    output_path=self.store.run_dir / f"trajectory_round{idx}.json",
                )
                result = mback.run_task(round_prompt)
                last_exit["status"] = result.exit_status
                last_exit["exhausted"] = getattr(round_model, "exhausted", None)
                metrics_acc["model_calls"] += result.n_model_calls
                if b.per_round:
                    metrics_acc["commands"] += env.commands_used
                    per_round_usage.append((round_totals["in"], round_totals["out"]))
                else:
                    metrics_acc["commands"] = env.commands_used
                metrics_acc["denied"] = env.denied_count

                self._git(s, "add", "-A")
                self._git(s, "commit", "-q", "--allow-empty", "-m", f"rp-host round {idx}")
                head = self._git(s, "rev-parse", "HEAD").stdout.decode().strip()
                diff = self._diff_stats(s, s.base_commit, head)  # type: ignore[attr-defined]
                tampered = [p for p in diff["files"] if p.startswith("public_tests/")]

                junit = self._run_public(s)
                nodes = junit.get("nodes", [])
                collected_ok = bool(junit.get("junit_present")) and not junit.get("junit_parse_error")
                failed_nodes = [n["node_id"] for n in nodes if n["outcome"] != "passed"]
                details = {n["node_id"]: n.get("message", "") for n in nodes
                           if n["outcome"] != "passed"}
                passed = sum(1 for n in nodes if n["outcome"] == "passed")

                regr = self._run_regression(s)
                reg_failed = regr["failed_checks"] + max(0, expected_reg - regr["passed_checks"])
                if reg_failed:
                    failed_nodes.append("host_regression::suite")
                    details["host_regression::suite"] = (
                        f"regression {regr['passed_checks']}/{expected_reg} passed, "
                        f"{regr['failed_checks']} failed")

                scope_req = extract_scope_change(result.submission)
                rr = RoundResult(
                    adapter_snapshot=head,
                    passed=passed,
                    failed_nodes=failed_nodes,
                    failure_details=details,
                    diff_lines=diff["total_lines"],
                    tokens_used=(round_totals["in"] + round_totals["out"] if b.per_round
                                 else token_totals["in"] + token_totals["out"]),
                    commands_used=result.commands_used,
                    scope_change_request=scope_req,
                    collected_ok=collected_ok,
                    policy_violations=env.denied_count + len(tampered),
                    regression_failed=reg_failed,
                    within_budget=result.exit_status not in
                    ("TokenBudgetExhausted", "LimitsExceeded"),
                )
                packets_next = build_failure_packets(failed_nodes, details)
                record = RepairRoundRecord(
                    round_index=idx,
                    base_snapshot_hash=base_hash,
                    adaptation_root=head,
                    changed_files=diff["files"],
                    diff_lines=diff["total_lines"],
                    public_passed=passed,
                    public_failed=len([n for n in failed_nodes
                                       if not n.startswith("host_regression")]),
                    regression_passed=regr["passed_checks"],
                    regression_failed=reg_failed,
                    policy_violations=env.denied_count + len(tampered),
                    model_calls=result.n_model_calls,
                    commands=result.commands_used,
                    tokens_in=(round_totals["in"] if round_totals["seen"] else "UNKNOWN"),
                    tokens_out=(round_totals["out"] if round_totals["seen"] else "UNKNOWN"),
                    wall_time_s=round(time.monotonic() - t_round, 1),
                    failure_packets=[p.to_dict() for p in packets_next],
                    scope_change_request=scope_req,
                    score=full_score(rr),
                )
                records.append(record)
                public_by_round.append(passed)
                regression_by_round.append(regr["passed_checks"])
                rd = repair_dir / f"round-{idx}"
                rd.mkdir(exist_ok=True)
                (rd / "record.json").write_text(
                    json.dumps(record.to_dict(), ensure_ascii=False, indent=2,
                               sort_keys=True), encoding="utf-8")
                ev("repair.round.end", actor="harness", payload={
                    "round": idx, "public_passed": passed,
                    "public_failed": len(failed_nodes),
                    "regression_passed": regr["passed_checks"],
                    "tampered_public_tests": tampered,
                    "exit_status": result.exit_status,
                    "scope_change": bool(scope_req)})
                return rr

            # 真正的全局硬墙在 env(命令数)与 TokenBudgetedModel(token);
            # RoundResult 报的是累计值,RepairLoop 内部再求和会重复计数,
            # 故此处上限放大 max_rounds 倍只作兜底,不作首要执法者。
            loop = RepairLoop(
                run_round,
                budget=RepairBudget(
                    max_rounds=b.max_rounds,
                    max_tokens=(b.max_input_tokens_total + b.max_output_tokens_total)
                    * b.max_rounds,
                    max_commands=b.max_commands * b.max_rounds,
                    max_diff_lines=b.max_patch_lines),
                score_fn=full_score,
            )
            outcome = loop.run()
            cur = self._git(s, "rev-parse", "HEAD").stdout.decode().strip()
            if cur != outcome.final_adapter:
                self._git(s, "reset", "--hard", outcome.final_adapter)
                self._git(s, "clean", "-fd")
            for r in records:
                r.selected_as_best = (r.round_index == outcome.best_round)
                (repair_dir / f"round-{r.round_index}" / "record.json").write_text(
                    json.dumps(r.to_dict(), ensure_ascii=False, indent=2,
                               sort_keys=True), encoding="utf-8")
            repair_summary = {
                "rounds_run": outcome.rounds_run,
                "best_round": outcome.best_round,
                "best_public_passed": outcome.best_passed,
                "stop_reason": outcome.stop_reason,
                "rolled_back_rounds": outcome.rolled_back_rounds,
                "pending_scope_change": outcome.pending_scope_change,
            }
            (repair_dir / "summary.json").write_text(
                json.dumps(repair_summary, ensure_ascii=False, indent=2,
                           sort_keys=True), encoding="utf-8")
            ev("repair.summary", actor="harness", payload=repair_summary)
            agent_metrics = {
                **metrics_acc,
                "exit_status": last_exit["status"],
                "cost": "UNKNOWN",
                "input_tokens": token_totals["in"] if token_totals["seen"] else "UNKNOWN",
                "output_tokens": token_totals["out"] if token_totals["seen"] else "UNKNOWN",
                "agent_wall_s": round(time.monotonic() - t_agent, 1),
            }
            if model_factory is None:
                import litellm as _litellm
                _litellm.success_callback = []
                for traj in self.store.run_dir.glob("trajectory_round*.json"):
                    assert provider.api_key.encode() not in traj.read_bytes(), \
                        "API key leaked into trajectory"
            # per_round:早先轮次的耗尽会被下一轮满额"复活",只有**终轮**
            # 耗尽才把整个 run 标为额度收束;total:沿用全程单额度语义。
            final_ex = (last_exit.get("exhausted") if b.per_round
                        else getattr(model, "exhausted", None))
            if final_ex:
                scope = "final_round" if b.per_round else "total"
                budget_exhausted = (f"{final_ex['kind']} "
                                    f"({final_ex['used']} >= {final_ex['limit']}, {scope})")
            ev("agent.end", actor="harness", payload=agent_metrics)

            # ---------------- scope change 停点 ----------------
            if repair_summary.get("pending_scope_change"):
                verdict_record = {
                    "verdict": "BLOCKED", "state": "SCOPE_CHANGE_PENDING_USER",
                    "scope_change_request": repair_summary["pending_scope_change"]}
                return self._finish(
                    verdict_record, integrity_before, backend, s, keep_session,
                    agent_metrics=agent_metrics, repair_summary=repair_summary,
                    records=records, public_by_round=public_by_round,
                    regression_by_round=regression_by_round,
                    run_order=run_order, run_index=run_index, model_name=model_name,
                    preflight=preflight, budget_exhausted=budget_exhausted,
                    gate_reasons=["AI 请求范围变更,已暂停等待用户决定:"
                                  + str(repair_summary["pending_scope_change"])],
                    t0=t0)

            # ---------------- 冻结适配(git diff S0..best)----------------
            diff_final = self._diff_stats(s, s.base_commit)  # type: ignore[attr-defined]
            patch = self._git(s, "diff", "--binary",
                              f"{s.base_commit}..HEAD",  # type: ignore[attr-defined]
                              timeout_s=120)
            patch_bytes = patch.stdout
            (self.store.run_dir / "adaptation.patch").write_bytes(patch_bytes)
            adaptation_manifest = AdaptationManifest(
                files=[{"path": p} for p in diff_final["files"]],
                total_files=diff_final["total_files"],
                total_lines=diff_final["total_lines"],
                tree_root_sha256=sha256_bytes(patch_bytes),
                frozen=True)
            self.store.save_json("adaptation_manifest.json", adaptation_manifest.model_dump())
            ev("adaptation.frozen", actor="harness", payload={
                "files": adaptation_manifest.total_files,
                "lines": adaptation_manifest.total_lines,
                "root": adaptation_manifest.tree_root_sha256})

            # ---------------- 独立验证 ----------------
            t_verify = time.monotonic()
            cap_run = self._run_oracle(s, oracle_snap)
            cap = VerificationResult(
                verifier="CapabilityVerifier",
                passed=cap_run["exit_code"] == 0,
                detail=(f"passed_checks={cap_run['passed_checks']}, "
                        f"failed_checks={cap_run['failed_checks']}, "
                        f"total_checks={cap_run['total_checks']}"
                        + ("" if cap_run["exit_code"] == 0 else
                           " — failing: " + ", ".join(
                               t.split("::")[-1] for t in cap_run["failed_tests"][:12]))),
                extra={"exit_code": cap_run["exit_code"], **{
                    k: cap_run[k] for k in
                    ("passed_checks", "failed_checks", "total_checks", "failed_tests")}})
            reg_run = self._run_regression(s)
            reg_ok = reg_run["exit_code"] == 0 and reg_run["passed_checks"] >= expected_reg
            reg = VerificationResult(
                verifier="HostRegressionVerifier",
                passed=reg_ok,
                detail=(f"passed_checks={reg_run['passed_checks']}, "
                        f"failed_checks={reg_run['failed_checks']}, "
                        f"baseline={expected_reg}"
                        + ("" if reg_ok else " — host regression below baseline")),
                extra={"exit_code": reg_run["exit_code"],
                       "passed_checks": reg_run["passed_checks"],
                       "failed_tests": reg_run["failed_tests"]})

            # per_round 语义下,受约束的量是"单轮最大用量"而非累计
            # (累计对比每轮上限会假报违规)。usage 未上报时保持 UNKNOWN。
            if b.per_round and per_round_usage and token_totals["seen"]:
                tb_in: int | str = max(u[0] for u in per_round_usage)
                tb_out: int | str = max(u[1] for u in per_round_usage)
            else:
                tb_in = agent_metrics.get("input_tokens")
                tb_out = agent_metrics.get("output_tokens")
            pol = policy_result(
                token_budget={
                    "input_used": tb_in,
                    "output_used": tb_out,
                    "input_limit": b.max_input_tokens_total,
                    "output_limit": b.max_output_tokens_total,
                },
                trace_path=self.store.trace_path,
                oracle_before=oracle_before,
                oracle_after=hash_tree(oracle_snap),
                upstream_before=upstream_before,
                upstream_after=hash_tree(s.root / "upstream"),
                adaptation_manifest=adaptation_manifest,
                adaptation_recheck_ok=(
                    self._git(s, "rev-parse", "HEAD").stdout.decode().strip()
                    == outcome.final_adapter),
                adaptation_recheck_detail="session HEAD == frozen best commit",
                budgets=self.budgets,
                evidence=[])
            pub_ok, pub_diff = trees_equal(
                public_before, hash_tree(s.root / "host" / "public_tests"))
            if not pub_ok:
                pol = VerificationResult(
                    verifier="PolicyVerifier", passed=False,
                    detail=pol.detail + f"; PUBLIC_TESTS_TAMPERED: {pub_diff[:5]}",
                    evidence=pol.evidence,
                    extra={**pol.extra, "public_tests_tampered": pub_diff[:10]})
            self.timings["verification_s"] = round(time.monotonic() - t_verify, 1)

            first_outcome = {
                "capability_exit": cap_run["exit_code"],
                "capability_failed": sorted(cap_run["failed_tests"]),
                "regression_exit": reg_run["exit_code"],
                "probe_normalized_sha": sha256_bytes(json.dumps({
                    "cap_failed": sorted(cap_run["failed_tests"]),
                    "cap_passed": cap_run["passed_checks"],
                    "reg_passed": reg_run["passed_checks"],
                }, sort_keys=True).encode()),
            }

            # ---------------- clean replay(全过才有资格)----------------
            if cap.passed and reg.passed and pol.passed and budget_exhausted is None:
                if not keep_session:
                    backend.destroy(s.id)
                    s = None
                t_replay = time.monotonic()
                try:
                    replay_outcome = self._clean_replay(backend, patch_bytes, oracle_snap,
                                                        expected_reg)
                    rep = replay_result(first=first_outcome, replay=replay_outcome,
                                        mode=REPLAY_MODE_CLEAN,
                                        evidence=[first_outcome["probe_normalized_sha"]])
                    rep.extra["replay_model_calls"] = 0
                    rep.extra["replay_agent_commands"] = 0
                except Exception as exc:  # noqa: BLE001
                    rep = VerificationResult(
                        verifier="ReplayVerifier", passed=False,
                        detail=f"replay infrastructure failure: {exc}",
                        extra={"mode": REPLAY_MODE_CLEAN})
                self.timings["replay_s"] = round(time.monotonic() - t_replay, 1)

        except _BaselineUnhealthy as exc:
            verdict_record = {"verdict": "BLOCKED", "state": "HOST_BASELINE_UNHEALTHY",
                              "baseline_report": exc.report}
            return self._finish(
                verdict_record, integrity_before, backend, s, keep_session,
                agent_metrics=agent_metrics, repair_summary={}, records=[],
                public_by_round=[], regression_by_round=[],
                run_order=run_order, run_index=run_index, model_name=model_name,
                preflight=preflight, budget_exhausted=None,
                gate_reasons=["HOST_BASELINE_UNHEALTHY:宿主基线不达标,未消耗任何模型预算"],
                t0=t0)
        finally:
            if s is not None and not keep_session:
                backend.destroy(s.id)

        # ---------------- Completion Gate ----------------
        for r in (cap, reg, pol) + ((rep,) if rep else ()):
            self.store.save_verification(r)
            ev("verification.result", actor=r.verifier,
               payload={"passed": r.passed, "detail": r.detail})
        gate = completion_gate.decide(
            capability=cap, regression=reg, policy=pol, replay=rep,
            adaptation=adaptation_manifest,
            missing_external=missing_external, budget_exhausted=budget_exhausted)
        ev("gate.verdict", actor="completion-gate", payload=gate.model_dump(mode="json"))
        verdict_record = {
            "verdict": gate.verdict.value,
            "gate_reasons": gate.reasons,
            "capability": cap.detail if cap else "not_run",
            "regression": reg.detail if reg else "not_run",
            "policy": pol.detail if pol else "not_run",
            "replay": rep.detail if rep else None,
        }
        return self._finish(
            verdict_record, integrity_before, backend, None, keep_session,
            agent_metrics=agent_metrics, repair_summary=repair_summary,
            records=records, public_by_round=public_by_round,
            regression_by_round=regression_by_round,
            run_order=run_order, run_index=run_index, model_name=model_name,
            preflight=preflight, budget_exhausted=budget_exhausted,
            gate_reasons=gate.reasons, t0=t0,
            adaptation_manifest=adaptation_manifest,
            capability_vr=cap, regression_vr=reg, policy_vr=pol, replay_vr=rep,
            first_outcome=first_outcome)

    # ------------------------------------------------------------ clean replay
    def _clean_replay(self, backend: LocalWorktreeBackend, patch_bytes: bytes,
                      oracle_snap: Path, expected_reg: int) -> dict:
        """全新会话 + git apply + 从(补丁后的)requirements 重建 venv。

        依赖必须被声明进 requirements.txt——重放环境只从声明重建,
        未声明的运行期 pip install 在这里如实失败(源 §24 Dependency Delta)。"""
        ev = self.store.append_event
        s = self._assemble(backend, "replay")
        try:
            (s.root / "adaptation.patch").write_bytes(patch_bytes)
            if patch_bytes.strip():
                r = s.backend.exec(s.id, ["git", "apply", "../adaptation.patch"],
                                   timeout_s=120, workdir="host")
                if r.exit_code != 0:
                    raise HostRunError(
                        "重放 git apply 失败:" + r.stderr.decode(errors="replace")[-300:])
            self._git(s, "add", "-A")
            self._git(s, "commit", "-q", "--allow-empty", "-m", "rp-host replay apply")
            self._build_env_in_session(s)
            cap_run = self._run_oracle(s, oracle_snap)
            reg_run = self._run_regression(s)
            outcome = {
                "capability_exit": cap_run["exit_code"],
                "capability_failed": sorted(cap_run["failed_tests"]),
                "regression_exit": reg_run["exit_code"],
                "probe_normalized_sha": sha256_bytes(json.dumps({
                    "cap_failed": sorted(cap_run["failed_tests"]),
                    "cap_passed": cap_run["passed_checks"],
                    "reg_passed": reg_run["passed_checks"],
                }, sort_keys=True).encode()),
            }
            ev("replay.done", actor="harness", payload={
                "capability_exit": cap_run["exit_code"],
                "regression_passed": reg_run["passed_checks"],
                "expected_regression": expected_reg})
            return outcome
        finally:
            backend.destroy(s.id)

    # ------------------------------------------------------------ 收尾与记账
    def _finish(
        self, verdict_record: dict, integrity_before: dict,
        backend: LocalWorktreeBackend, s: _Session | None, keep_session: bool,
        *, agent_metrics: dict, repair_summary: dict,
        records: list[RepairRoundRecord], public_by_round: list[int],
        regression_by_round: list[int], run_order, run_index, model_name: str,
        preflight: PreflightResult | None, budget_exhausted: str | None,
        gate_reasons: list[str], t0: float,
        adaptation_manifest: AdaptationManifest | None = None,
        capability_vr: VerificationResult | None = None,
        regression_vr: VerificationResult | None = None,
        policy_vr: VerificationResult | None = None,
        replay_vr: VerificationResult | None = None,
        first_outcome: dict | None = None,
    ) -> dict:
        ev = self.store.append_event
        if s is not None and not keep_session:
            backend.destroy(s.id)
        if not keep_session:
            backend.destroy_all()
            shutil.rmtree(backend.sessions_root, ignore_errors=True)
        integrity = verify_protected_unchanged(integrity_before)
        if not integrity["ok"]:
            ev("integrity.MISMATCH", actor="harness", payload=integrity)
        self.timings["total_wall_s"] = round(time.monotonic() - t0, 1)
        ev("run.end", actor="runner", payload={
            "verdict": verdict_record.get("verdict"),
            "main_dir_integrity_ok": integrity["ok"],
            "timings": self.timings})

        chain_ok, n_events, chain_err = verify_chain(self.store.trace_path)
        trace_sha = sha256_file(self.store.trace_path)
        failure_types = sorted({
            p["type"] for r in records for p in (r.failure_packets or [])})
        report = {
            "run_id": self.run_id,
            "task_id": self.contract.task_id,
            "mode": "host-guided-repair",
            "final_verdict": verdict_record.get("verdict"),
            **verdict_record,
            "gate_reasons": gate_reasons,
            "agent": agent_metrics,
            "repair": repair_summary,
            "public_passed_by_round": public_by_round,
            "regression_by_round": regression_by_round,
            "budget_exhausted": budget_exhausted,
            "adaptation_root": (adaptation_manifest.tree_root_sha256
                                if adaptation_manifest else None),
            "main_dir_integrity": integrity,
            "final_trace_sha256": trace_sha,
            "trace_events": n_events,
            "trace_chain_ok": chain_ok,
            "trace_chain_error": chain_err,
            "timings": self.timings,
            "first_outcome": first_outcome or {},
        }
        self.store.save_json("report.json", report)

        harness_commit = subprocess.run(  # noqa: S603
            ["git", "-C", str(self.project_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False).stdout.strip() or "UNKNOWN"
        rounds_used = repair_summary.get("rounds_run") or len(records) or "UNKNOWN"
        record = {
            "run_id": self.run_id,
            "task_id": self.contract.task_id,
            "task_version": self.contract.task_version,
            "harness_commit": harness_commit,
            "host_commit": self.contract.host.commit,
            "source_commit": self.contract.source_repo.resolved_commit,
            "model": model_name,
            "provider": "openai-compatible" if preflight else "fake",
            "provider_config_hash": (preflight.provider_config_sha256
                                     if preflight else "UNKNOWN"),
            "run_index": run_index,
            "run_order": run_order,
            "guided": True,
            "max_rounds": self.contract.budgets.max_rounds,
            "rounds_used": rounds_used,
            "model_calls": agent_metrics.get("model_calls"),
            "commands": agent_metrics.get("commands"),
            "input_tokens": agent_metrics.get("input_tokens"),
            "output_tokens": agent_metrics.get("output_tokens"),
            "wall_time": self.timings.get("total_wall_s"),
            "cost": agent_metrics.get("cost", "UNKNOWN"),
            "public_passed_by_round": public_by_round or "UNKNOWN",
            "regression_by_round": regression_by_round or "UNKNOWN",
            "rollback_count": len(repair_summary.get("rolled_back_rounds", []) or []),
            "scope_change_count": 1 if repair_summary.get("pending_scope_change") else 0,
            "stagnation": repair_summary.get("stop_reason") == "stagnation",
            "final_capability": capability_vr.detail if capability_vr else "UNKNOWN",
            "final_regression": regression_vr.detail if regression_vr else "UNKNOWN",
            "policy": (("PASS" if policy_vr.passed else "FAIL")
                       if policy_vr else "UNKNOWN"),
            "replay": (("PASS" if replay_vr.passed else "FAIL")
                       if replay_vr else "UNKNOWN"),
            "verdict": verdict_record.get("verdict"),
            "failure_types": failure_types or "UNKNOWN",
            "execution_backend": "local-worktree",
            "env_baseline_hash": self.env_baseline_hash,
            "main_dir_integrity": "ok" if integrity["ok"] else "MISMATCH",
            "trace_sha256": trace_sha,
            "bundle_path": str(self.store.run_dir),
        }
        append_run(self.project_root, record)
        ev("bench.recorded", actor="harness", payload={"runs_jsonl": "benchmarks/v2/runs.jsonl"})
        return report


class _BaselineUnhealthy(Exception):
    def __init__(self, report: dict) -> None:
        super().__init__("HOST_BASELINE_UNHEALTHY")
        self.report = report


# ------------------------------------------------------------------ CLI 入口
def run_host_guided_cli(
    contract_path: Path,
    project_root: Path,
    *,
    fake: str | None = None,
    run_order: int | str = "UNKNOWN",
    run_index: int | str = "UNKNOWN",
    wheelhouse: Path | None = None,
    keep_session: bool = False,
) -> dict:
    """准入 → 预检 → 宿主级 guided 运行。

    fake:
      None        真实模型(REPOPROOF_API_BASE/KEY/MODEL 环境变量)
      "noop"      fake 模型什么都不做直接提交(FAIL 路径冒烟)
      "positive"  fake 模型脚本化注入正控(PASS 路径冒烟;绝不用于正式 run)
    """
    if fake is None:
        # 预检在 runner 构造(=建 run 目录)之前:preflight 拦截绝不留下
        # 无 report.json 的隐身 run 目录(LESSONS #12 教训)。
        from repoproof.agents.provider_gate import run_preflight
        from repoproof.runner.agent_run import provider_from_env

        provider = provider_from_env()
        pf = run_preflight(provider)
        if not pf.ready:
            return {"blocked": True, "preflight": pf.summary(),
                    "agent_model_call_count": 0}
        runner = HostGuidedRunner(contract_path, project_root, wheelhouse=wheelhouse)
        report = runner.run(provider, pf, run_order=run_order, run_index=run_index,
                            keep_session=keep_session)
        return {"blocked": False, "preflight": pf.summary(), "report": report}
    runner = HostGuidedRunner(contract_path, project_root, wheelhouse=wheelhouse)

    from repoproof.agents.fake_model import FakeModel

    def factory(_totals: dict):
        return FakeModel(script=_fake_script(fake, runner))

    report = runner.run(None, None, model_factory=factory,
                        run_order=run_order, run_index=run_index,
                        keep_session=keep_session)
    return {"blocked": False, "preflight": None, "report": report}


def _fake_script(kind: str, runner: HostGuidedRunner) -> list[dict]:
    """冒烟脚本。positive 脚本读取正控参考实现(harness 侧冒烟专用;
    正式 run 走真实模型,正控内容永不进入其提示或环境)。"""
    if kind == "noop":
        return [{"content": "noop submit",
                 "actions": [{"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"}]}]
    if kind != "positive":
        raise ValueError(f"未知 fake 模式:{kind}")
    positive = (runner.task_dir / "controls" / "positive" / "sdk_mcp.py").read_text(
        encoding="utf-8")
    mcp_pins = "fastapi-mcp\nmcp<2.0\n"
    steps = [
        {"actions": [{"command": ".venv/bin/pip install -q fastapi-mcp 'mcp<2.0'"}]},
        {"actions": [{"command":
                      "cat > sdk_mcp.py <<'RP_EOF'\n" + positive + "\nRP_EOF"}]},
        {"actions": [{"command":
                      "printf '\\nfrom sdk_mcp import mount_sdk_mcp\\n"
                      "mount_sdk_mcp(app)\\n' >> rag_api.py"}]},
        {"actions": [{"command":
                      "printf '" + mcp_pins.replace("\n", "\\n") + "' >> requirements.txt"}]},
        {"actions": [{"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"}]},
    ]
    return steps
