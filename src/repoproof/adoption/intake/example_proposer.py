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
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel, Field

MAX_CANDIDATES = 8
_RUN_TIMEOUT_S = 60
_OUTPUT_CAP = 20_000


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

    def truth_provenance(self) -> str:
        if not self.confirmed:
            return "UNCONFIRMED"
        if self.expected_overridden:
            return "USER_OVERRIDDEN"
        return "UPSTREAM_DERIVED_USER_CONFIRMED"

    @property
    def usable_as_golden(self) -> bool:
        """上游给出了输出 → 可以做成 golden 样例。

        上游**抛错**的候选不在此列:golden 样例只表达成功路径(输入 →
        期望 stdout),错误行为由题面(statement)与骨架的 exit 1 语义承担。
        这类候选仍然有用 —— 它是"这个输入会让上游炸"的**行为证据**,
        提醒你把该行为写进题面,而不是等真发时被 oracle 撞出来。
        """
        return self.upstream_output is not None and not self.upstream_error


class ProposalBatch(BaseModel):
    candidates: list[CandidateExample] = Field(default_factory=list)
    drafter: str = ""
    note: str = ""


# --------------------------------------------------------------- ① 候选输入

_LITERAL = re.compile(r"""["']([^"'\n]{1,120})["']""")


def mine_evidence_literals(upstream_dir: Path, *, cap: int = 12,
                           import_module_names: list[str] | None = None) -> list[str]:
    """从钉版上游的 README 里挖出**现成的示例输入**(确定性,零模型)。

    为什么要有这一步(2026-08-27 实测):离线模板起草是域盲的 —— 它给
    "典型输入""非 ASCII 输入"这种通用串,对 webcolors 这类任务一条可用的
    都没有(6 条候选全部让上游抛错)。而 README 的 doctest 里就躺着
    `hex_to_name("#daa520")` —— 作者亲手写的、保证有意义的输入。

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
    "REFERENCE_EXECUTION_ERROR",
    "REFERENCE_NO_OUTPUT",
    "REFERENCE_OUTPUT_TOO_LARGE",
    "REFERENCE_REJECTED",
    "REFERENCE_USER_INPUT_ERROR",
})


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


def reference_is_placeholder(source: str) -> str:
    """reference 还是"起草占位"吗?→ 返回原因(空串表示看起来是真实现)。

    背景(2026-08-27 用户实测):离线模板起草出来的 reference 长这样 ——

        import webcolors
        def extract(input_path):
            ...
            return str(webcolors)

    它**确实 import 了上游、确实有确定性输出**,所以骨架检查(抛
    NotImplementedError)放它过去。但它没有实现任何能力:拿它跑候选,
    每条"上游实际输出"都是 `<module 'webcolors' from ...>`,用户一确认
    就把模块字符串冻进了验收真值 —— 一个看起来全绿、实则空心的合同。

    用 AST 判,不用正则:只认"extract 的返回值是 `str(<顶层 import 的模块>)`"
    这一个精确形状,避免误伤真实现。
    """
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return f"reference_impl 语法错误:{exc}"

    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                modules.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])

    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.FunctionDef) and fn.name == "extract"):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Return) or node.value is None:
                continue
            v = node.value
            if (isinstance(v, ast.Call) and isinstance(v.func, ast.Name)
                    and v.func.id == "str" and len(v.args) == 1
                    and isinstance(v.args[0], ast.Name)
                    and v.args[0].id in modules):
                return (f"reference_impl 还是起草占位:它只是把上游模块本身"
                        f"转成字符串(`return str({v.args[0].id})`),并没有实现能力。"
                        "拿它跑出来的「上游实际输出」会是模块地址,不是你要的结果 —— "
                        "请先在上面把参考实现补成真调上游能力的版本。")
    return ""


def _sanitised_env(home: Path, extra_paths: list[str]) -> dict:
    """净化环境:只留跑得起来的最小集合。

    密钥、REPOPROOF_* 连接配置一律不进 —— 这里执行的是**第三方代码**,
    给它看见 API key 没有任何正当理由(与会话装配的净化口径同向)。
    """
    keep = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8")}
    keep["HOME"] = str(home)
    keep["TMPDIR"] = str(home)
    if extra_paths:
        keep["PYTHONPATH"] = os.pathsep.join(extra_paths)
    keep["PYTHONDONTWRITEBYTECODE"] = "1"
    return keep


def _reference_lock_path(draft_dir: Path) -> Path | None:
    lock = Path(draft_dir) / "reference.lock.txt"
    return lock if lock.is_file() and lock.read_text(encoding="utf-8").strip() else None


def _python_in_venv(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


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

    sandbox = Path("/usr/bin/sandbox-exec")
    if sys.platform != "darwin" or not sandbox.is_file():
        raise ReferenceIsolationError(
            "当前主机没有受支持的 reference runtime 隔离后端；"
            "为避免让第三方 reference 联网，Studio 已在模型调用前停止。"
        )
    real_root = writable_root.resolve()
    escaped_root = str(real_root).replace("\\", "\\\\").replace('"', '\\"')
    profile = (
        "(version 1)"
        "(allow default)"
        "(deny network*)"
        "(deny file-write*)"
        f'(allow file-write* (subpath "{escaped_root}") '
        '(literal "/dev/null"))'
    )
    return [str(sandbox), "-p", profile, *argv]


@contextmanager
def prepared_reference_environment(
    draft_dir: Path,
    *,
    wheelhouse: Path | None = None,
    timeout_s: int = 600,
) -> Iterator[str | None]:
    """Yield one disposable interpreter containing the reference lock closure.

    The pinned upstream source tree is still placed first on ``PYTHONPATH`` by
    :func:`run_reference_on_candidates`; the venv supplies only the dependency
    closure which a source checkout does not contain.  When no lock exists we
    preserve the source-only behavior used by synthetic/stdlib references.

    With no caller-provided wheelhouse, dependencies are first downloaded as
    wheels and then installed with ``--no-index``.  Consequently third-party
    code is never executed with network access during candidate evaluation,
    and sdists/build hooks are not accepted on this Product intake path.
    """
    lock = _reference_lock_path(Path(draft_dir))
    if lock is None:
        yield None
        return

    with tempfile.TemporaryDirectory(prefix="rp-reference-env-") as temp:
        root = Path(temp)
        venv = root / "venv"
        managed_wheels = root / "wheels"
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
                f"参考环境创建失败（HARNESS）：{exc}"
            ) from exc
        if created.returncode != 0:
            raise ReferenceEnvironmentError(
                "参考环境创建失败（HARNESS）："
                f"{(created.stderr or created.stdout or '')[-800:]}"
            )

        python = _python_in_venv(venv)
        install_wheels = Path(wheelhouse) if wheelhouse is not None else managed_wheels
        if wheelhouse is None:
            managed_wheels.mkdir()
            downloaded = subprocess.run(  # noqa: S603 - fixed interpreter and argv
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
            if downloaded.returncode != 0:
                raise ReferenceEnvironmentError(
                    "参考依赖下载失败（HARNESS；尚未调用模型）："
                    f"{(downloaded.stderr or downloaded.stdout or '')[-1200:]}"
                )
        elif not install_wheels.is_dir():
            raise ReferenceEnvironmentError(
                f"参考 wheelhouse 不存在或不是目录（HARNESS）：{install_wheels}"
            )

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
        if installed.returncode != 0:
            raise ReferenceEnvironmentError(
                "参考依赖离线安装失败（HARNESS；尚未调用模型）："
                f"{(installed.stderr or installed.stdout or '')[-1200:]}"
            )
        yield str(python)


def run_reference_on_candidates(
    batch: ProposalBatch, *, draft_dir: Path, upstream_dir: Path,
    python_exe: str | None = None, timeout_s: int = _RUN_TIMEOUT_S,
    isolation_required: bool = False,
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
    placeholder = reference_is_placeholder(ref_src)
    if placeholder:
        raise ExampleProposalError(placeholder)

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
            )

    up = Path(upstream_dir)
    extra = [str(up / "src"), str(up)] if (up / "src").is_dir() else [str(up)]

    with tempfile.TemporaryDirectory(prefix="rp-example-probe-") as tmp:
        tmpd = Path(tmp)
        payload = []
        for i, c in enumerate(batch.candidates):
            f = tmpd / f"in_{i}_{Path(c.input_name).name}"
            f.write_text(c.input_text, encoding="utf-8")
            payload.append({"name": c.input_name, "path": str(f)})
        payload_path = tmpd / "_payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        runner = tmpd / "_runner.py"
        runner.write_text(_RUNNER, encoding="utf-8")

        argv = [
            python_exe or sys.executable,
            str(runner),
            str(Path(draft_dir)),
            str(payload_path),
        ]
        if isolation_required:
            argv = _sandboxed_reference_argv(argv, tmpd)
        proc = subprocess.run(                       # noqa: S603 固定 argv
            argv,
            capture_output=True, text=True, timeout=timeout_s,
            cwd=str(tmpd), env=_sanitised_env(tmpd, extra), check=False)

    try:
        doc = json.loads((proc.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise ExampleProposalError(
            "上游探测没有给出可解析结果:"
            f"{(proc.stderr or proc.stdout or '')[-500:]}") from exc
    if doc.get("fatal"):
        raise ExampleProposalError(str(doc["fatal"]))

    by_name = {r["name"]: r for r in doc.get("results", [])}
    updated: list[CandidateExample] = []
    for c in batch.candidates:
        r = by_name.get(c.input_name, {})
        updated.append(c.model_copy(update={
            "upstream_output": (str(r["output"]) if "output" in r else None),
            "upstream_error": (str(r["error"]) if "error" in r else None),
            "upstream_output_truncated": bool(r.get("output_truncated")),
        }))
    return batch.model_copy(update={"candidates": updated})


# ----------------------------------------------------------------- ③ 人确认

def confirm_candidate(candidate: CandidateExample, *,
                      expected_text: str | None = None) -> CandidateExample:
    """人闸:确认一条候选；人工改写真值必须留下不同 provenance。

    空字符串也可能是上游真实、合法的 stdout，不能把它误判成“没有输出”。

    没有"全部确认"的批量口子 —— 与计划确认(`confirm_plan` 逐项)同律:
    一次点击只为一条负责,才叫确认。
    """
    text = expected_text if expected_text is not None else candidate.upstream_output
    if text is None:
        raise ExampleProposalError(
            f"{candidate.input_name}:上游对这条输入抛错,做不成 golden 样例"
            "(样例只表达成功路径)。它的正当去处是**写进题面的错误行为**:"
            "把「这类输入应当报错并 exit 1」说清楚。上游错误:"
            f"{candidate.upstream_error}")
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
