"""Golden 样例助手 —— 降低上手门槛,但**不接管真值判定**。

## 为什么这个模块长这样

用户的痛点是真的:第一次用的人不知道"样例"该怎么写,面对空的
`examples/` 目录就卡住了。但直接让模型写"期望输出"会让整条判定链失去
意义 —— 模型出题 + 模型答题,PASS 不再证明任何事(批次二
`pyspellchecker` 的 false-success 就是同型死法:题面/reference/oracle
互相印证着错下去,一路绿到运营态)。

所以拆成三段,每段的产出者不同:

  ① 候选**输入**  ← 模型(输入不是判据;模型在这里反而能补边界/畸形样本)
  ② 候选**输出**  ← **钉版上游真跑**(不是模型猜的,是上游此刻的实际行为)
  ③ **逐条确认**  ← 人(可改可删;未确认的一条都不进 examples.yaml)

②的实现刻意**复用 draft 束里的 `reference_impl`**:按纪律它必须真
import 上游,所以"跑它"就等于"问上游此刻怎么答",而且与 oracle 用的是
同一条语义 —— 不另造第二套执行路径,也就没有第二套语义可漂移。

## 边界(不许被"方便"侵蚀)

- 本模块**不产出** `confirmed=True`:那一位只能由人翻(见 `confirm_candidate`);
- 候选输出旁边必须挂着"这是上游实际输出,不是对错判定"的语义 —— 判定
  它是不是你要的能力,仍然是人的活(`semver._deprecated` 那种废弃 API
  会给出漂亮输出,只有人能说"我不要这个");
- 跑 reference **是在执行第三方代码**:Studio 路径要求 OS 级网络/写入沙箱，
  同时净化环境、使用临时 HOME/cwd 并设置超时，绝不在 Studio 进程里
  import 上游。这个边界面向人工准入的公开仓库，不冒充敌对代码读取隔离。
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import secrets
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from repoproof.execution.import_hook import (
    ENV_LEDGER,
    ENV_MODULE,
    ENV_SECRET,
    verify_import_receipts,
    write_hook_dir,
)
from repoproof.execution.offline_sandbox import (
    OfflineSandboxUnavailable,
    offline_sandbox_argv,
    sanitised_subprocess_env,
)

MAX_CANDIDATES = 8
_RUN_TIMEOUT_S = 60
_OUTPUT_CAP = 20_000
_REFERENCE_EXACT_PIN_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9][A-Za-z0-9._+!-]*"
)
_REFERENCE_WHEELHOUSE_MANIFEST = "manifest.json"


class ExampleProposalError(RuntimeError):
    pass


class ReferenceEnvironmentError(ExampleProposalError):
    """The Harness could not prepare the pinned reference environment.

    This is deliberately distinct from a candidate rejected by upstream: an
    environment failure is owned by the Harness and must stop *before* an LLM
    is called or an Agent repair round is consumed.
    """

    reason_code = "REFERENCE_ENVIRONMENT_SETUP_FAILED"


class ReferenceIsolationError(ReferenceEnvironmentError):
    """The host cannot enforce the Product reference runtime boundary."""

    reason_code = "REFERENCE_RUNTIME_ISOLATION_UNAVAILABLE"


class ReferenceWheelhouseMaterializationError(ReferenceEnvironmentError):
    """The exact-pinned reference wheel cache could not be prepared."""

    reason_code = "REFERENCE_WHEELHOUSE_MATERIALIZATION_FAILED"


class ReferenceWheelhouseIntegrityError(ReferenceEnvironmentError):
    """A previously prepared reference wheel cache no longer matches."""

    reason_code = "REFERENCE_WHEELHOUSE_INTEGRITY_FAILED"


class ReferenceOfflineInstallError(ReferenceEnvironmentError):
    """The disposable interpreter cannot install the cached wheel closure."""

    reason_code = "REFERENCE_OFFLINE_INSTALL_FAILED"


class CandidateTruthEvidence(BaseModel):
    """Public, candidate-scoped identity for one reference execution.

    The signed receipt itself and its one-time verification secret stay in the
    server-managed evidence store.  This public projection is safe to render in
    a browser, but it is not sufficient on its own to confirm a golden sample.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    evidence_id: str
    correlation_id: str
    import_module: str
    reference_sha256: str
    upstream_identity_sha256: str
    input_sha256: str
    result_kind: str
    result_sha256: str
    runtime_receipt_sha256: str
    imports: int
    calls: int
    truth_binding_sha256: str

    @model_validator(mode="after")
    def _well_formed(self) -> CandidateTruthEvidence:
        if self.schema_version != 1:
            raise ValueError("candidate truth evidence schema_version 必须为 1")
        for name in (
            "evidence_id",
            "correlation_id",
            "reference_sha256",
            "upstream_identity_sha256",
            "input_sha256",
            "result_sha256",
            "runtime_receipt_sha256",
            "truth_binding_sha256",
        ):
            if re.fullmatch(r"[0-9a-f]{64}", str(getattr(self, name))) is None:
                raise ValueError(f"{name} 必须是小写 SHA-256")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", self.import_module) is None:
            raise ValueError("candidate truth evidence import_module 无效")
        if self.result_kind not in {"output", "error"}:
            raise ValueError("candidate truth evidence result_kind 无效")
        if self.imports < 1 or self.calls < 0:
            raise ValueError("candidate truth evidence runtime counts 无效")
        if self.result_kind == "output" and self.calls < 1:
            raise ValueError("成功候选必须有自己那次执行的上游调用证据")
        return self


class CandidateExample(BaseModel):
    """一条候选样例。`upstream_output` 是**上游实际输出**,不是判定。"""

    input_name: str
    input_text: str
    why: str = ""                       # 模型为什么提这条(展示用)
    upstream_output: str | None = None
    upstream_error: str | None = None
    upstream_output_truncated: bool = False
    confirmed: bool = False             # 只能经 confirm_candidate 翻
    expected_overridden: bool = False   # 人工改真值时不得冒充上游派生
    admission_status: Literal[
        "NOT_EVALUATED", "ADMITTED", "REJECTED"
    ] = "NOT_EVALUATED"
    admission_reason_codes: tuple[str, ...] = ()
    truth_evidence: CandidateTruthEvidence | None = None
    # Never serialised to the browser.  Product Studio persists this signed
    # ledger + one-time secret in its server-managed evidence store before it
    # returns the public candidate projection.
    managed_runtime_evidence: dict[str, str] | None = Field(
        default=None,
        exclude=True,
        repr=False,
    )

    def truth_provenance(self) -> str:
        if not self.confirmed:
            return "UNCONFIRMED"
        if self.expected_overridden:
            return "USER_OVERRIDDEN"
        return "UPSTREAM_DERIVED_USER_CONFIRMED"

    @model_validator(mode="after")
    def _admission_is_consistent(self) -> CandidateExample:
        if any(_PUBLIC_REASON_RE.fullmatch(item) is None for item in self.admission_reason_codes):
            raise ValueError("candidate admission reason codes are invalid")
        if len(self.admission_reason_codes) != len(set(self.admission_reason_codes)):
            raise ValueError("candidate admission reason codes must be unique")
        if self.admission_status == "ADMITTED" and (
            self.upstream_output is None
            or self.upstream_error is not None
            or self.admission_reason_codes
        ):
            raise ValueError("admitted candidate must have one clean reference output")
        if self.admission_status == "REJECTED" and not self.admission_reason_codes:
            raise ValueError("rejected candidate must explain its admission failure")
        if self.admission_status == "NOT_EVALUATED" and self.admission_reason_codes:
            raise ValueError("unevaluated candidate cannot carry admission failures")
        return self

    @property
    def usable_as_golden(self) -> bool:
        """上游给出了输出 → 可以做成 golden 样例。

        上游**抛错**的候选不在此列:golden 样例只表达成功路径(输入 →
        期望 stdout),错误行为由题面(statement)与骨架的 exit 1 语义承担。
        这类候选仍然有用 —— 它是"这个输入会让上游炸"的**行为证据**,
        提醒你把该行为写进题面,而不是等真发时被 oracle 撞出来。
        """
        return (
            self.upstream_output is not None
            and not self.upstream_error
            and self.admission_status != "REJECTED"
        )


class ProposalBatch(BaseModel):
    candidates: list[CandidateExample] = Field(default_factory=list)
    drafter: str = ""
    note: str = ""
    reference_evidence: dict[str, object] | None = None


def _domain_sha256(domain: bytes, document: dict[str, object]) -> str:
    payload = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256()
    digest.update(domain + b"\0")
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)
    return digest.hexdigest()


def upstream_runtime_identity(
    upstream_dir: Path,
    *,
    import_module: str,
    runtime_artifact_sha256: str | None = None,
) -> str:
    """Bind candidate truth to its source provenance and executable runtime.

    Git repositories use commit/tree identities plus a digest of any working
    tree status.  Synthetic/non-Git fixtures fall back to a deterministic tree
    digest.  Product Studio may additionally bind the identity of the admitted
    wheel closure actually imported by the reference process.  This keeps a
    source checkout as provenance without pretending an unbuilt checkout is an
    executable distribution.  No repository names, formats or capability
    vocabulary participate in this mechanism.
    """

    root = Path(upstream_dir)
    if root.is_symlink() or not root.is_dir():
        raise ExampleProposalError("REFERENCE_UPSTREAM_IDENTITY_UNAVAILABLE")
    module = str(import_module).strip()
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", module) is None:
        raise ExampleProposalError("REFERENCE_IMPORT_MODULE_INVALID")

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - fixed git argv
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    head = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    status = git("status", "--porcelain=v1", "--untracked-files=all")
    if (
        head.returncode == tree.returncode == status.returncode == 0
        and not status.stdout.strip()
    ):
        identity: dict[str, object] = {
            "kind": "git-worktree-v1",
            "head": head.stdout.strip(),
            "tree": tree.stdout.strip(),
            "worktree": "clean",
        }
    else:
        digest = hashlib.sha256(b"repoproof-upstream-tree-v1\0")
        found = False
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            relative = path.relative_to(root)
            if ".git" in relative.parts or "__pycache__" in relative.parts:
                continue
            if path.is_symlink():
                raise ExampleProposalError("REFERENCE_UPSTREAM_TREE_HAS_SYMLINK")
            if not path.is_file() or path.suffix == ".pyc":
                continue
            found = True
            body = path.read_bytes()
            encoded = relative.as_posix().encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            digest.update(len(body).to_bytes(8, "big"))
            digest.update(body)
        if not found:
            raise ExampleProposalError("REFERENCE_UPSTREAM_IDENTITY_UNAVAILABLE")
        identity = {"kind": "content-tree-v1", "tree_sha256": digest.hexdigest()}
    identity["import_module"] = module
    if runtime_artifact_sha256 is not None:
        runtime_digest = str(runtime_artifact_sha256).strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", runtime_digest) is None:
            raise ExampleProposalError("REFERENCE_RUNTIME_ARTIFACT_IDENTITY_INVALID")
        identity["runtime_artifact"] = {
            "kind": "admitted-wheel-closure-v1",
            "sha256": runtime_digest,
        }
    return _domain_sha256(b"repoproof-upstream-runtime-identity-v1", identity)


def _candidate_truth_binding(
    *,
    input_name: str,
    input_text: str,
    result_kind: str,
    result_text: str,
    import_module: str,
    reference_sha256: str,
    upstream_identity_sha256: str,
    runtime_receipt_sha256: str,
) -> str:
    return _domain_sha256(
        b"repoproof-candidate-truth-binding-v1",
        {
            "input_name": input_name,
            "input_sha256": hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
            "result_kind": result_kind,
            "result_sha256": hashlib.sha256(result_text.encode("utf-8")).hexdigest(),
            "import_module": import_module,
            "reference_sha256": reference_sha256,
            "upstream_identity_sha256": upstream_identity_sha256,
            "runtime_receipt_sha256": runtime_receipt_sha256,
        },
    )


def validate_candidate_truth_evidence(candidate: CandidateExample) -> None:
    """Recompute the public candidate binding; absence always fails closed."""

    evidence = candidate.truth_evidence
    if evidence is None:
        raise ExampleProposalError("CANDIDATE_TRUTH_EVIDENCE_MISSING")
    if candidate.upstream_output is None or candidate.upstream_error is not None:
        raise ExampleProposalError("CANDIDATE_TRUTH_EVIDENCE_NOT_CONFIRMABLE")
    input_sha256 = hashlib.sha256(candidate.input_text.encode("utf-8")).hexdigest()
    result_sha256 = hashlib.sha256(candidate.upstream_output.encode("utf-8")).hexdigest()
    if (
        evidence.result_kind != "output"
        or evidence.input_sha256 != input_sha256
        or evidence.result_sha256 != result_sha256
    ):
        raise ExampleProposalError("CANDIDATE_TRUTH_EVIDENCE_CONTENT_MISMATCH")
    binding = _candidate_truth_binding(
        input_name=candidate.input_name,
        input_text=candidate.input_text,
        result_kind="output",
        result_text=candidate.upstream_output,
        import_module=evidence.import_module,
        reference_sha256=evidence.reference_sha256,
        upstream_identity_sha256=evidence.upstream_identity_sha256,
        runtime_receipt_sha256=evidence.runtime_receipt_sha256,
    )
    if binding != evidence.truth_binding_sha256:
        raise ExampleProposalError("CANDIDATE_TRUTH_EVIDENCE_BINDING_MISMATCH")
    want_id = _domain_sha256(
        b"repoproof-candidate-evidence-id-v1",
        {
            "correlation_id": evidence.correlation_id,
            "truth_binding_sha256": binding,
        },
    )
    if want_id != evidence.evidence_id:
        raise ExampleProposalError("CANDIDATE_TRUTH_EVIDENCE_ID_MISMATCH")


# --------------------------------------------------------------- ① 候选输入

_LITERAL = re.compile(r"""["']([^"'\n]{1,120})["']""")


def mine_evidence_literals(upstream_dir: Path, *, cap: int = 12,
                           import_module_names: list[str] | None = None) -> list[str]:
    """从钉版上游的 README 里挖出**现成的示例输入**(确定性,零模型)。

    离线模板是域盲的，泛化占位输入可能全部落在上游有效域之外；README
    与上游测试中的作者示例则是可追溯的高信号候选来源。

    与本模块的总纲一致:**从证据里提取,而不是凭空发明**。挖出来的仍然
    只是"候选输入",期望输出照旧由上游真跑给出、由人确认。
    """
    text = ""
    for name in ("README.md", "README.rst", "README.txt", "README"):
        f = Path(upstream_dir) / name
        if f.is_file():
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            break
    out: list[str] = []
    seen: set[str] = set()

    def harvest(body: str, *, only_calls: bool) -> None:
        for line in body.splitlines():
            s = line.strip()
            looks_like_code = (s.startswith(">>>") or s.startswith("...")
                               or ("(" in s and ("=" in s or "." in s)))
            if not looks_like_code:
                continue
            if only_calls and "(" not in s:
                continue
            for lit in _LITERAL.findall(s):
                key = lit.strip()
                if not key or key in seen or len(key) > 120:
                    continue
                seen.add(key)
                out.append(key)
                if len(out) >= cap:
                    return

    harvest(text, only_calls=False)       # ① README:作者亲手写的示例,最高信号
    if len(out) >= cap:
        return out

    # ② 上游自己的测试:"这个库到底吃什么输入"的最好证据。只取**提到某个
    #    公开入口**的行,避免把测试里的无关字面量(路径、断言消息)一起挖进来。
    names = {n for n in (import_module_names or []) if n}
    for f in sorted(Path(upstream_dir).rglob("test*.py"))[:20]:
        try:
            body = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        wanted = "\n".join(ln for ln in body.splitlines()
                            if not names or any(n in ln for n in names))
        harvest(wanted, only_calls=True)
        if len(out) >= cap:
            break
    return out


def propose_inputs(*, goal: str, overview: dict, drafter, n: int = 4,
                   existing_inputs: list[str] | None = None,
                   existing_names: list[str] | None = None) -> ProposalBatch:
    """问模型要 n 条候选**输入**(只要输入,不要答案)。

    `existing_inputs` 只在本地做去重。既有样例可能来自用户私有文件，正文
    绝不进入模型上下文；模型只知道已有多少条。repair 反馈也只接收稳定的
    公开 reason code/fingerprint，不接收 reference 原始异常或失败输入正文。
    """
    n = max(1, min(int(n), MAX_CANDIDATES))
    existing = list(existing_inputs or [])
    context = {
        "capability_goal": goal,
        "repository": overview.get("repository", ""),
        "repo_headline": overview.get("headline", ""),
        "repo_prose": (overview.get("prose") or "")[:800],
        "surfaces": [s.get("value") for s in (overview.get("surfaces") or [])][:12],
        # README 里挖到的现成示例值(证据,不是模型发明的)
        "evidence_literals": list(overview.get("evidence_literals") or [])[:12],
        "how_many": n,
        "existing_input_count": len(existing),
        "failed_attempts": _sanitise_public_failed_attempts(
            overview.get("failed_attempts") or []
        )[:12],
    }
    raw = drafter.propose_example_inputs(context)
    items = raw.get("inputs") if isinstance(raw, dict) else raw
    if not isinstance(items, list) or not items:
        raise ExampleProposalError("起草器没有给出候选输入")

    seen = {_norm_input(x) for x in existing}
    seen_names = {Path(x).name.casefold() for x in (existing_names or [])}
    out: list[CandidateExample] = []
    for i, item in enumerate(items[:n], start=1):
        if not isinstance(item, dict) or "input_text" not in item:
            continue
        # 空输入**是**合法候选(边界行为必须被题面写死)。只在模型压根没给
        # 这个键时才丢 —— 早期版本用 `not text.strip()` 过滤,把最有价值的
        # 那条边界样本静默吃掉了。
        text = str(item.get("input_text") or "")
        if _norm_input(text) in seen:          # 与既有样例或彼此重复 → 丢
            continue
        seen.add(_norm_input(text))
        raw_name = Path(str(item.get("input_name") or "").strip()).name
        name = raw_name if raw_name not in {"", ".", ".."} else f"case_{i}.txt"
        base, suffix = Path(name).stem or f"case_{i}", Path(name).suffix
        serial = 2
        while name.casefold() in seen_names:
            name = f"{base}-{serial}{suffix}"
            serial += 1
        seen_names.add(name.casefold())
        out.append(CandidateExample(
            input_name=name, input_text=text,
            why=str(item.get("why") or "")))
    if not out:
        raise ExampleProposalError("候选输入去重后为空(模型给的都与既有样例重复)")
    return ProposalBatch(candidates=out,
                         drafter=str(getattr(drafter, "name", "unknown")),
                         note="候选输入由模型生成;期望输出将由钉版上游真跑给出,"
                              "并需你逐条确认后才会成为验收真值")


def _norm_input(text: str) -> str:
    """去重键:规范化行尾与首尾空白。判"见过没有"不能被一个换行骗过去。"""
    return "\n".join(ln.rstrip() for ln in str(text).replace("\r\n", "\n").split("\n")).strip()


_PUBLIC_REASON_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_EXCEPTION_TYPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,119}$")
_PUBLIC_REASON_CODES = frozenset({
    "CANDIDATE_NOT_IN_ADMITTED_SUCCESS_DOMAIN",
    "REFERENCE_EXECUTION_ERROR",
    "REFERENCE_NO_OUTPUT",
    "REFERENCE_OUTPUT_TOO_LARGE",
    "REFERENCE_REJECTED",
    "REFERENCE_USER_INPUT_ERROR",
})


def public_candidate_failure(candidate: CandidateExample) -> dict[str, str]:
    """Return model-safe feedback without leaking task verifier diagnostics."""

    if candidate.admission_status == "REJECTED":
        reason_code = "CANDIDATE_NOT_IN_ADMITTED_SUCCESS_DOMAIN"
        return {
            "reason_code": reason_code,
            "failure_fingerprint": hashlib.sha256(
                reason_code.encode("ascii")
            ).hexdigest(),
        }
    return public_reference_failure(
        upstream_error=candidate.upstream_error,
        output_truncated=candidate.upstream_output_truncated,
    )


def public_reference_failure(*, upstream_error: str | None,
                             output_truncated: bool = False) -> dict[str, str]:
    """Turn a local reference failure into model-safe repair feedback.

    A reference exception can contain arbitrary file contents or absolute host
    paths.  Its message is therefore never hashed or copied into the prompt.
    The exception *type* is used only to select a coarse allow-listed reason;
    the fingerprint is then derived from that reason alone, so it is stable
    without becoming a content oracle for private data.
    """
    raw_error = str(upstream_error or "")
    exception_type = raw_error.partition(":")[0].strip()
    if not _EXCEPTION_TYPE_RE.fullmatch(exception_type):
        exception_type = "UNKNOWN"
    short_type = exception_type.rsplit(".", 1)[-1]
    if output_truncated or short_type == "ReferenceOutputTooLarge":
        reason_code = "REFERENCE_OUTPUT_TOO_LARGE"
    elif not raw_error:
        reason_code = "REFERENCE_NO_OUTPUT"
    elif short_type == "UserInputError":
        reason_code = "REFERENCE_USER_INPUT_ERROR"
    else:
        reason_code = "REFERENCE_EXECUTION_ERROR"
    fingerprint = hashlib.sha256(reason_code.encode("ascii")).hexdigest()
    return {"reason_code": reason_code, "failure_fingerprint": fingerprint}


def _sanitise_public_failed_attempts(rows: object) -> list[dict[str, str]]:
    """Allow-list repair feedback immediately before it reaches a drafter."""
    if not isinstance(rows, list):
        return []
    safe: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        reason_code = str(row.get("reason_code") or "")
        if (
            not _PUBLIC_REASON_RE.fullmatch(reason_code)
            or reason_code not in _PUBLIC_REASON_CODES
        ):
            reason_code = "REFERENCE_REJECTED"
        # Never trust even an opaque caller-provided digest: a 64-character
        # hexadecimal credential is still a credential.  Derive this value
        # again from the allow-listed public category immediately before the
        # model call.
        fingerprint = hashlib.sha256(reason_code.encode("ascii")).hexdigest()
        safe.append({
            "reason_code": reason_code,
            "failure_fingerprint": fingerprint,
        })
    return safe


# ------------------------------------------------- ② 候选输出(上游真跑)

_RUNNER = r'''
import json, sys, traceback
from pathlib import Path

ref_dir, payload_path = sys.argv[1], sys.argv[2]
sys.path.insert(0, ref_dir)
out = []
output_cap = __OUTPUT_CAP__
try:
    import reference_impl as ref
except BaseException:
    print(json.dumps({"fatal": "reference_impl 无法导入:\n" + traceback.format_exc()[-1500:]}))
    raise SystemExit(0)

for item in json.loads(Path(payload_path).read_text(encoding="utf-8")):
    p = Path(item["path"])
    try:
        value = str(ref.extract(p))
        if len(value) > output_cap:
            out.append({
                "name": item["name"],
                "error": f"ReferenceOutputTooLarge: output exceeds {output_cap} characters",
                "output_truncated": True,
            })
        else:
            out.append({"name": item["name"], "output": value})
    except BaseException as exc:
        out.append({"name": item["name"],
                    "error": f"{type(exc).__name__}: {exc}"[:800]})
print(json.dumps({"results": out}))
'''.replace("__OUTPUT_CAP__", str(_OUTPUT_CAP))


def _sanitised_env(home: Path, extra_paths: list[str]) -> dict:
    """净化环境:只留跑得起来的最小集合。

    密钥、REPOPROOF_* 连接配置一律不进 —— 这里执行的是**第三方代码**,
    给它看见 API key 没有任何正当理由(与会话装配的净化口径同向)。
    """
    return sanitised_subprocess_env(home, extra_paths)


def _reference_lock_path(draft_dir: Path) -> Path | None:
    lock = Path(draft_dir) / "reference.lock.txt"
    return lock if lock.is_file() and lock.read_text(encoding="utf-8").strip() else None


def _python_in_venv(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _normalised_reference_lock_text(raw: str) -> str:
    pins = [
        line.strip()
        for line in str(raw).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not pins or any(_REFERENCE_EXACT_PIN_RE.fullmatch(pin) is None for pin in pins):
        raise ReferenceWheelhouseMaterializationError(
            "参考依赖锁不是完整的精确版本列表（HARNESS；尚未调用模型）。"
        )
    return "\n".join(pins) + "\n"


def _normalised_reference_lock(lock: Path) -> str:
    try:
        if lock.is_symlink() or not lock.is_file():
            raise OSError("lock is not a regular file")
        raw = lock.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ReferenceWheelhouseMaterializationError(
            "参考依赖锁不可安全读取（HARNESS；尚未调用模型）。"
        ) from exc
    return _normalised_reference_lock_text(raw)


def _reference_wheelhouse_identity(lock: Path) -> tuple[str, str]:
    normalised = _normalised_reference_lock(lock)
    lock_sha256 = hashlib.sha256(normalised.encode("utf-8")).hexdigest()
    identity = {
        "schema_version": 1,
        "lock_sha256": lock_sha256,
        "python_cache_tag": str(getattr(sys.implementation, "cache_tag", "")),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "platform": sys.platform,
        "machine": platform.machine(),
    }
    cache_key = hashlib.sha256(
        b"repoproof-reference-wheelhouse-v1\0"
        + json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return cache_key, lock_sha256


def _path_has_symlink(path: Path) -> bool:
    absolute = Path(path).absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            return True
        if not current.exists():
            break
    return False


def _wheel_manifest(wheelhouse: Path) -> dict[str, object]:
    wheels: dict[str, dict[str, object]] = {}
    for wheel in sorted(wheelhouse.glob("*.whl")):
        if wheel.is_symlink() or not wheel.is_file():
            raise ReferenceWheelhouseIntegrityError(
                "参考 wheelhouse 包含不安全文件（HARNESS；尚未调用模型）。"
            )
        digest = hashlib.sha256()
        with wheel.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        wheels[wheel.name] = {
            "sha256": digest.hexdigest(),
            "size": wheel.stat().st_size,
        }
    if not wheels:
        raise ReferenceWheelhouseIntegrityError(
            "参考 wheelhouse 没有可安装 wheel（HARNESS；尚未调用模型）。"
        )
    return {"wheels": wheels}


def _validate_reference_wheelhouse(
    wheelhouse: Path,
    *,
    cache_key: str,
    lock_sha256: str,
) -> None:
    if wheelhouse.is_symlink() or not wheelhouse.is_dir():
        raise ReferenceWheelhouseIntegrityError(
            "参考 wheelhouse 缓存身份无效（HARNESS；尚未调用模型）。"
        )
    manifest_path = wheelhouse / _REFERENCE_WHEELHOUSE_MANIFEST
    try:
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise OSError("manifest is not a regular file")
        if manifest_path.stat().st_size > 1024 * 1024:
            raise ValueError("manifest too large")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ReferenceWheelhouseIntegrityError(
            "参考 wheelhouse 清单不可验证（HARNESS；尚未调用模型）。"
        ) from exc
    if not isinstance(manifest, dict):
        raise ReferenceWheelhouseIntegrityError(
            "参考 wheelhouse 清单根节点无效（HARNESS；尚未调用模型）。"
        )
    actual = _wheel_manifest(wheelhouse)
    expected_wheels = manifest.get("wheels")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("cache_key") != cache_key
        or manifest.get("lock_sha256") != lock_sha256
        or expected_wheels != actual["wheels"]
    ):
        raise ReferenceWheelhouseIntegrityError(
            "参考 wheelhouse 与依赖锁身份不一致（HARNESS；尚未调用模型）。"
        )


def reference_wheelhouse_runtime_identity(
    lock: Path,
    *,
    cache_root: Path,
) -> str:
    """Return the identity of an already admitted executable wheel closure.

    The helper is deliberately cache-only: candidate confirmation and audit
    materialisation must never acquire new bytes merely to make an old truth
    record look current.  Generation first materialises the content-addressed
    cache through :func:`prepared_reference_environment`, then calls this
    function to bind the revalidated manifest and wheel bytes into evidence.
    """

    cache_key, lock_sha256 = _reference_wheelhouse_identity(Path(lock))
    wheelhouse = Path(cache_root).expanduser() / cache_key
    _validate_reference_wheelhouse(
        wheelhouse,
        cache_key=cache_key,
        lock_sha256=lock_sha256,
    )
    manifest = json.loads(
        (wheelhouse / _REFERENCE_WHEELHOUSE_MANIFEST).read_text(encoding="utf-8")
    )
    return _domain_sha256(
        b"repoproof-reference-runtime-artifact-v1",
        {
            "cache_key": cache_key,
            "lock_sha256": lock_sha256,
            "wheels": manifest["wheels"],
        },
    )


def ensure_reference_wheelhouse(
    lock: Path,
    *,
    cache_root: Path,
    timeout_s: int = 600,
) -> Path:
    """Return an immutable-by-identity, persistent wheel closure for ``lock``.

    Network access is permitted only while materialising a cache miss.  Every
    candidate/reference execution later installs solely from this admitted
    directory with ``--no-index``.  Cached bytes are rehashed before reuse, so
    a stale or modified cache fails closed rather than silently redownloading.
    """

    cache_key, lock_sha256 = _reference_wheelhouse_identity(Path(lock))
    root = Path(cache_root).expanduser()
    try:
        if _path_has_symlink(root) or root.is_symlink():
            raise OSError("cache root is a symlink")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not root.is_dir() or root.is_symlink():
            raise OSError("cache root is not a regular directory")
    except OSError as exc:
        raise ReferenceWheelhouseMaterializationError(
            "参考 wheelhouse 缓存目录不可用（HARNESS；尚未调用模型）。"
        ) from exc
    target = root / cache_key
    if target.exists():
        _validate_reference_wheelhouse(
            target,
            cache_key=cache_key,
            lock_sha256=lock_sha256,
        )
        return target

    with tempfile.TemporaryDirectory(prefix=f".{cache_key[:12]}-", dir=root) as temp:
        stage = Path(temp)
        wheels = stage / "wheels"
        wheels.mkdir(mode=0o700)
        environment = _sanitised_env(stage, [])
        try:
            downloaded = subprocess.run(  # noqa: S603 - fixed interpreter/argv
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "download",
                    "--disable-pip-version-check",
                    "--only-binary=:all:",
                    "--dest",
                    str(wheels),
                    "-r",
                    str(lock),
                ],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                env=environment,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReferenceWheelhouseMaterializationError(
                "参考依赖 wheelhouse 建立失败（HARNESS；尚未调用模型）。"
            ) from exc
        if downloaded.returncode != 0:
            raise ReferenceWheelhouseMaterializationError(
                "参考依赖 wheelhouse 建立失败（HARNESS；尚未调用模型）。"
            )
        actual = _wheel_manifest(wheels)
        manifest = {
            "schema_version": 1,
            "cache_key": cache_key,
            "lock_sha256": lock_sha256,
            "wheels": actual["wheels"],
        }
        manifest_path = wheels / _REFERENCE_WHEELHOUSE_MANIFEST
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            os.replace(wheels, target)
        except OSError as exc:
            # A concurrent producer may have won the same content-addressed
            # cache key.  Admit that directory only after full re-verification.
            if not target.is_dir():
                raise ReferenceWheelhouseMaterializationError(
                    "参考 wheelhouse 无法原子保存（HARNESS；尚未调用模型）。"
                ) from exc
        _validate_reference_wheelhouse(
            target,
            cache_key=cache_key,
            lock_sha256=lock_sha256,
        )
        return target


def _sandboxed_reference_argv(argv: list[str], writable_root: Path) -> list[str]:
    """Wrap a reference command in an OS-enforced offline/write sandbox.

    Product Studio currently supports this boundary on macOS through the
    system ``sandbox-exec`` facility.  Network access is denied outright and
    writes are limited to the disposable candidate directory (plus
    ``/dev/null``).  We deliberately fail closed on hosts where no reviewed
    backend exists instead of silently treating an environment scrub as
    isolation.

    Read access is not claimed as a hostile-code boundary: RepoProof's stated
    scope remains human-admitted public repositories.  Environment secrets are
    removed separately by :func:`_sanitised_env`, and no reference output is
    sent back to the model.
    """

    try:
        return offline_sandbox_argv(argv, writable_root)
    except OfflineSandboxUnavailable as exc:
        raise ReferenceIsolationError(
            "当前主机没有受支持的 reference runtime 隔离后端；"
            "为避免让第三方 reference 联网，Studio 已在模型调用前停止。"
        ) from exc


@contextmanager
def prepared_reference_environment(
    draft_dir: Path,
    *,
    wheelhouse: Path | None = None,
    wheelhouse_cache_root: Path | None = None,
    resolved_lock_text: str | None = None,
    timeout_s: int = 600,
) -> Iterator[str | None]:
    """Yield one disposable interpreter containing the reference lock closure.

    The venv contains the exact executable wheel closure. Product callers bind
    that closure into candidate evidence and import it directly; the pinned
    source checkout remains the provenance identity. When no lock exists we
    preserve the source-only behavior used by synthetic/stdlib references.

    Studio supplies ``wheelhouse_cache_root`` so a lock/interpreter identity is
    materialised once and re-verified on every reuse.  Other callers may still
    provide an already admitted wheelhouse directly.  Installation is always
    ``--no-index``; third-party code therefore never executes with network
    access during candidate evaluation, and sdists/build hooks are rejected.
    """
    disk_lock = _reference_lock_path(Path(draft_dir))
    selected_lock_text: str | None = None
    if resolved_lock_text is not None:
        selected_lock_text = _normalised_reference_lock_text(resolved_lock_text)
        if (
            disk_lock is not None
            and _normalised_reference_lock(disk_lock) != selected_lock_text
        ):
            raise ReferenceWheelhouseIntegrityError(
                "草稿依赖锁与 Core 解析结果不一致（HARNESS；尚未调用模型）。"
            )
    elif disk_lock is not None:
        selected_lock_text = _normalised_reference_lock(disk_lock)
    if selected_lock_text is None:
        yield None
        return

    with tempfile.TemporaryDirectory(prefix="rp-reference-env-") as temp:
        root = Path(temp)
        venv = root / "venv"
        managed_wheels = root / "wheels"
        lock = disk_lock or (root / "resolved-reference.lock.txt")
        if disk_lock is None:
            lock.write_text(selected_lock_text, encoding="utf-8")
        env = _sanitised_env(root, [])
        try:
            created = subprocess.run(  # noqa: S603 - fixed interpreter and argv
                [sys.executable, "-m", "venv", str(venv)],
                capture_output=True,
                text=True,
                timeout=min(timeout_s, 120),
                env=env,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReferenceEnvironmentError(
                "参考环境创建失败（HARNESS；尚未调用模型）。"
            ) from exc
        if created.returncode != 0:
            raise ReferenceEnvironmentError(
                "参考环境创建失败（HARNESS；尚未调用模型）。"
            )

        python = _python_in_venv(venv)
        if wheelhouse is not None:
            install_wheels = Path(wheelhouse)
        elif wheelhouse_cache_root is not None:
            install_wheels = ensure_reference_wheelhouse(
                lock,
                cache_root=wheelhouse_cache_root,
                timeout_s=timeout_s,
            )
        else:
            install_wheels = managed_wheels
        if wheelhouse is None and wheelhouse_cache_root is None:
            managed_wheels.mkdir()
            try:
                downloaded = subprocess.run(  # noqa: S603 - fixed interpreter/argv
                    [
                        str(python),
                        "-m",
                        "pip",
                        "download",
                        "--disable-pip-version-check",
                        "--only-binary=:all:",
                        "--dest",
                        str(managed_wheels),
                        "-r",
                        str(lock),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                    env=env,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise ReferenceWheelhouseMaterializationError(
                    "参考依赖 wheelhouse 建立失败（HARNESS；尚未调用模型）。"
                ) from exc
            if downloaded.returncode != 0:
                raise ReferenceWheelhouseMaterializationError(
                    "参考依赖 wheelhouse 建立失败（HARNESS；尚未调用模型）。"
                )
        elif not install_wheels.is_dir():
            raise ReferenceWheelhouseIntegrityError(
                "参考 wheelhouse 不存在或身份无效（HARNESS；尚未调用模型）。"
            )

        try:
            installed = subprocess.run(  # noqa: S603 - fixed interpreter and argv
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-index",
                    "--find-links",
                    str(install_wheels),
                    "-r",
                    str(lock),
                ],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                env=env,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReferenceOfflineInstallError(
                "参考依赖无法从受管 wheelhouse 离线安装（HARNESS；尚未调用模型）。"
            ) from exc
        if installed.returncode != 0:
            raise ReferenceOfflineInstallError(
                "参考依赖无法从受管 wheelhouse 离线安装（HARNESS；尚未调用模型）。"
            )
        yield str(python)


def run_reference_on_candidates(
    batch: ProposalBatch, *, draft_dir: Path, upstream_dir: Path,
    python_exe: str | None = None, timeout_s: int = _RUN_TIMEOUT_S,
    isolation_required: bool = False,
    import_module: str | None = None,
    runtime_artifact_sha256: str | None = None,
) -> ProposalBatch:
    """在隔离子进程里跑 draft 束的 `reference_impl`,给每条候选拿到上游实际输出。

    失败(导入不了、抛异常)一律**如实记下**而不是丢掉:"这个输入会让上游
    抛 ValueError"本身就是你需要写进题面的行为。
    """
    ref_py = Path(draft_dir) / "reference_impl.py"
    if not ref_py.is_file():
        raise ExampleProposalError(f"draft 束里没有 reference_impl.py:{draft_dir}")
    ref_src = ref_py.read_text(encoding="utf-8")
    if "NotImplementedError" in ref_src:
        raise ExampleProposalError(
            "reference_impl 还是骨架(仍抛 NotImplementedError)—— 它必须先被"
            "补成真调上游的实现,候选输出才有来源")
    # Safe default for callers outside Studio: a lock must never be ignored.
    # Studio prepares one environment for the whole bounded proposal batch and
    # passes ``python_exe`` explicitly, avoiding repeated downloads per round.
    if python_exe is None and _reference_lock_path(Path(draft_dir)) is not None:
        with prepared_reference_environment(draft_dir, timeout_s=max(timeout_s, 600)) as prepared:
            return run_reference_on_candidates(
                batch,
                draft_dir=draft_dir,
                upstream_dir=upstream_dir,
                python_exe=prepared,
                timeout_s=timeout_s,
                isolation_required=isolation_required,
                import_module=import_module,
                runtime_artifact_sha256=runtime_artifact_sha256,
            )

    up = Path(upstream_dir)
    # An admitted wheel closure is the executable upstream.  Do not prepend the
    # raw checkout: extension-backed projects may contain Python modules but no
    # compiled artifacts, and would otherwise shadow their valid locked wheel.
    # Source-only synthetic and legacy callers retain the historical behavior.
    extra = (
        []
        if runtime_artifact_sha256 is not None
        else ([str(up / "src"), str(up)] if (up / "src").is_dir() else [str(up)])
    )
    module = str(import_module or "").strip()
    if import_module is not None and re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_.]*",
        module,
    ) is None:
        raise ExampleProposalError("REFERENCE_IMPORT_MODULE_INVALID")
    reference_sha256 = hashlib.sha256(ref_src.encode("utf-8")).hexdigest()
    upstream_identity_sha256 = (
        upstream_runtime_identity(
            up,
            import_module=module,
            runtime_artifact_sha256=runtime_artifact_sha256,
        )
        if module
        else ""
    )

    def run_one(
        root: Path,
        candidate: CandidateExample | None,
        *,
        serial: int,
    ) -> CandidateExample | None:
        """One candidate owns one process, secret and signed receipt ledger."""

        invocation = root / f"candidate-{serial}"
        invocation.mkdir()
        hook_dir: Path | None = None
        hook_ledger: Path | None = None
        hook_secret = ""
        correlation_id = secrets.token_hex(32)
        if module:
            hook_dir = write_hook_dir(invocation / "_reference_hook")
            hook_ledger = invocation / "_reference_upstream_receipts.jsonl"
            hook_secret = secrets.token_hex(32)

        payload: list[dict[str, str]] = []
        if candidate is not None:
            source = invocation / f"input-{Path(candidate.input_name).name}"
            source.write_text(candidate.input_text, encoding="utf-8")
            payload.append({"name": candidate.input_name, "path": str(source)})
        payload_path = invocation / "payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        runner = invocation / "runner.py"
        runner.write_text(_RUNNER, encoding="utf-8")
        argv = [
            python_exe or sys.executable,
            str(runner),
            str(Path(draft_dir)),
            str(payload_path),
        ]
        if isolation_required:
            argv = _sandboxed_reference_argv(argv, root)
        run_env = _sanitised_env(
            invocation,
            [*((str(hook_dir),) if hook_dir is not None else ()), *extra],
        )
        if module and hook_ledger is not None:
            run_env.update({
                ENV_MODULE: module,
                ENV_LEDGER: str(hook_ledger),
                ENV_SECRET: hook_secret,
            })
        proc = subprocess.run(  # noqa: S603 - fixed interpreter/runner argv
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(invocation),
            env=run_env,
            check=False,
        )
        try:
            doc = json.loads((proc.stdout or "").strip().splitlines()[-1])
        except (ValueError, IndexError) as exc:
            raise ExampleProposalError(
                "上游探测没有给出可解析结果:"
                f"{(proc.stderr or proc.stdout or '')[-500:]}"
            ) from exc
        if doc.get("fatal"):
            raise ExampleProposalError(str(doc["fatal"]))

        rows = list(doc.get("results") or [])
        row = rows[0] if candidate is not None and len(rows) == 1 else None
        if candidate is not None and not isinstance(row, dict):
            raise ExampleProposalError("REFERENCE_CANDIDATE_RESULT_MISSING")

        receipt: dict[str, object] | None = None
        ledger_text = ""
        if module and hook_ledger is not None:
            successful = bool(row is not None and "output" in row)
            receipt = verify_import_receipts(
                hook_ledger,
                hook_secret,
                module=module,
                min_calls=(1 if successful else 0),
            )
            if not receipt["ok"]:
                raise ExampleProposalError(
                    "REFERENCE_UPSTREAM_CALL_NOT_OBSERVED:该候选自己的参考"
                    "执行没有产生可验证的上游调用；不能借用同批"
                    "其他候选的调用为它铸造真值。"
                )
            ledger_text = hook_ledger.read_text(encoding="utf-8")
        if candidate is None:
            return None

        output = str(row["output"]) if row is not None and "output" in row else None
        error = str(row["error"]) if row is not None and "error" in row else None
        result_kind = "output" if output is not None else "error"
        result_text = output if output is not None else str(error or "")
        evidence: CandidateTruthEvidence | None = None
        managed: dict[str, str] | None = None
        if module and receipt is not None:
            receipt_imports = receipt.get("imports")
            receipt_calls = receipt.get("calls")
            if not isinstance(receipt_imports, int) or not isinstance(
                receipt_calls,
                int,
            ):
                raise ExampleProposalError("REFERENCE_RUNTIME_RECEIPT_INVALID")
            receipt_sha256 = hashlib.sha256(ledger_text.encode("utf-8")).hexdigest()
            truth_binding = _candidate_truth_binding(
                input_name=candidate.input_name,
                input_text=candidate.input_text,
                result_kind=result_kind,
                result_text=result_text,
                import_module=module,
                reference_sha256=reference_sha256,
                upstream_identity_sha256=upstream_identity_sha256,
                runtime_receipt_sha256=receipt_sha256,
            )
            evidence_id = _domain_sha256(
                b"repoproof-candidate-evidence-id-v1",
                {
                    "correlation_id": correlation_id,
                    "truth_binding_sha256": truth_binding,
                },
            )
            evidence = CandidateTruthEvidence(
                evidence_id=evidence_id,
                correlation_id=correlation_id,
                import_module=module,
                reference_sha256=reference_sha256,
                upstream_identity_sha256=upstream_identity_sha256,
                input_sha256=hashlib.sha256(
                    candidate.input_text.encode("utf-8")
                ).hexdigest(),
                result_kind=result_kind,
                result_sha256=hashlib.sha256(result_text.encode("utf-8")).hexdigest(),
                runtime_receipt_sha256=receipt_sha256,
                imports=receipt_imports,
                calls=receipt_calls,
                truth_binding_sha256=truth_binding,
            )
            managed = {"secret": hook_secret, "ledger": ledger_text}
        return candidate.model_copy(update={
            "upstream_output": output,
            "upstream_error": error,
            "upstream_output_truncated": bool(
                row.get("output_truncated") if row is not None else False
            ),
            "truth_evidence": evidence,
            "managed_runtime_evidence": managed,
        })

    with tempfile.TemporaryDirectory(prefix="rp-example-probe-") as tmp:
        tmpd = Path(tmp)
        if not batch.candidates:
            run_one(tmpd, None, serial=0)
            updated: list[CandidateExample] = []
        else:
            updated = []
            for serial, candidate in enumerate(batch.candidates, start=1):
                result = run_one(tmpd, candidate, serial=serial)
                if result is None:  # pragma: no cover - candidate always returns one
                    raise ExampleProposalError("REFERENCE_CANDIDATE_RESULT_MISSING")
                updated.append(result)

    public_ids = [
        candidate.truth_evidence.evidence_id
        for candidate in updated
        if candidate.truth_evidence is not None
    ]
    return batch.model_copy(update={
        "candidates": updated,
        # Compatibility field remains readable, but it is explicitly only a
        # summary.  Confirmation consumes each candidate's own managed record.
        "reference_evidence": ({
            "schema_version": 2,
            "kind": "CANDIDATE_SCOPED_RUNTIME_UPSTREAM_CALL_SUMMARY",
            "import_module": module,
            "reference_sha256": reference_sha256,
            "upstream_identity_sha256": upstream_identity_sha256,
            "candidate_evidence_ids": public_ids,
        } if module else None),
    })


# ----------------------------------------------------------------- ③ 人确认

def confirm_candidate(candidate: CandidateExample, *,
                      expected_text: str | None = None) -> CandidateExample:
    """人闸:确认一条候选；人工改写真值必须留下不同 provenance。

    空字符串也可能是上游真实、合法的 stdout，不能把它误判成“没有输出”。

    没有"全部确认"的批量口子 —— 与计划确认(`confirm_plan` 逐项)同律:
    一次点击只为一条负责,才叫确认。
    """
    if candidate.admission_status == "REJECTED":
        raise ExampleProposalError(
            f"{candidate.input_name}:候选未通过当前输出合同与独立语义预筛，"
            "不能加入成功路径 golden 样例。"
        )
    text = expected_text if expected_text is not None else candidate.upstream_output
    if text is None:
        raise ExampleProposalError(
            f"{candidate.input_name}:上游对这条输入抛错,做不成 golden 样例"
            "(样例只表达成功路径)。它的正当去处是**写进题面的错误行为**:"
            "把「这类输入应当报错并 exit 1」说清楚。上游错误:"
            f"{candidate.upstream_error}")
    # Historical candidate documents remain parseable, but they cannot mint a
    # *new* upstream-derived golden after this evidence protocol is active.
    validate_candidate_truth_evidence(candidate)
    overridden = (
        candidate.expected_overridden
        or (expected_text is not None and expected_text != candidate.upstream_output)
    )
    return candidate.model_copy(update={
        "upstream_output": str(text),
        "confirmed": True,
        "expected_overridden": overridden,
    })


def assert_unseen_input(new_input: str, existing_inputs: list[str]) -> None:
    """fresh 抽查料的去重闸:与既有样例输入重合即**拒收**。

    抽查的全部意义是"工具没见过的输入"。让一条见过的输入混进来,抽查就
    从独立检查退化成复读 —— 这是硬拒,不是提醒。
    """
    key = _norm_input(new_input)
    if any(key == _norm_input(x) for x in existing_inputs):
        raise ExampleProposalError(
            "这份抽查输入与已有 golden 样例重合 —— 抽查必须用工具没见过的输入,"
            "否则它证明不了任何事")
