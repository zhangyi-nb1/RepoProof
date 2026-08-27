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
- 跑 reference **是在执行第三方代码**:统一走 `_run_isolated`(净化环境、
  临时 HOME/cwd、超时),绝不在 Studio 进程里 import 上游。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field

MAX_CANDIDATES = 8
_RUN_TIMEOUT_S = 60
_OUTPUT_CAP = 20_000


class ExampleProposalError(RuntimeError):
    pass


class CandidateExample(BaseModel):
    """一条候选样例。`upstream_output` 是**上游实际输出**,不是判定。"""

    input_name: str
    input_text: str
    why: str = ""                       # 模型为什么提这条(展示用)
    upstream_output: str | None = None
    upstream_error: str | None = None
    confirmed: bool = False             # 只能经 confirm_candidate 翻

    def truth_provenance(self) -> str:
        return "UPSTREAM_DERIVED_USER_CONFIRMED" if self.confirmed else "UNCONFIRMED"

    @property
    def usable_as_golden(self) -> bool:
        """上游给出了输出 → 可以做成 golden 样例。

        上游**抛错**的候选不在此列:golden 样例只表达成功路径(输入 →
        期望 stdout),错误行为由题面(statement)与骨架的 exit 1 语义承担。
        这类候选仍然有用 —— 它是"这个输入会让上游炸"的**行为证据**,
        提醒你把该行为写进题面,而不是等真发时被 oracle 撞出来。
        """
        return bool(self.upstream_output) and not self.upstream_error


class ProposalBatch(BaseModel):
    candidates: list[CandidateExample] = Field(default_factory=list)
    drafter: str = ""
    note: str = ""


# --------------------------------------------------------------- ① 候选输入

def propose_inputs(*, goal: str, overview: dict, drafter, n: int = 4,
                   existing_inputs: list[str] | None = None) -> ProposalBatch:
    """问模型要 n 条候选**输入**(只要输入,不要答案)。

    `existing_inputs` 会被交给模型作为"已经有了这些,请给不一样的",并在
    返回后做一次去重 —— 模型重复给同一条不算错,但不能悄悄混进去。
    """
    n = max(1, min(int(n), MAX_CANDIDATES))
    context = {
        "capability_goal": goal,
        "repository": overview.get("repository", ""),
        "repo_headline": overview.get("headline", ""),
        "repo_prose": (overview.get("prose") or "")[:800],
        "surfaces": [s.get("value") for s in (overview.get("surfaces") or [])][:12],
        "how_many": n,
        "already_have": list(existing_inputs or [])[:20],
    }
    raw = drafter.propose_example_inputs(context)
    items = raw.get("inputs") if isinstance(raw, dict) else raw
    if not isinstance(items, list) or not items:
        raise ExampleProposalError("起草器没有给出候选输入")

    seen = {_norm_input(x) for x in (existing_inputs or [])}
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
        name = str(item.get("input_name") or "").strip() or f"case_{i}.txt"
        out.append(CandidateExample(
            input_name=Path(name).name, input_text=text,
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


# ------------------------------------------------- ② 候选输出(上游真跑)

_RUNNER = r'''
import json, sys, traceback
from pathlib import Path

ref_dir, payload_path = sys.argv[1], sys.argv[2]
sys.path.insert(0, ref_dir)
out = []
try:
    import reference_impl as ref
except BaseException:
    print(json.dumps({"fatal": "reference_impl 无法导入:\n" + traceback.format_exc()[-1500:]}))
    raise SystemExit(0)

for item in json.loads(Path(payload_path).read_text(encoding="utf-8")):
    p = Path(item["path"])
    try:
        value = ref.extract(p)
        out.append({"name": item["name"], "output": str(value)})
    except BaseException as exc:
        out.append({"name": item["name"],
                    "error": f"{type(exc).__name__}: {exc}"[:800]})
print(json.dumps({"results": out}))
'''


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


def run_reference_on_candidates(
    batch: ProposalBatch, *, draft_dir: Path, upstream_dir: Path,
    python_exe: str | None = None, timeout_s: int = _RUN_TIMEOUT_S,
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

        proc = subprocess.run(                       # noqa: S603 固定 argv
            [python_exe or sys.executable, str(runner), str(Path(draft_dir)),
             str(payload_path)],
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
            "upstream_output": (str(r["output"])[:_OUTPUT_CAP] if "output" in r else None),
            "upstream_error": (str(r["error"]) if "error" in r else None),
        }))
    return batch.model_copy(update={"candidates": updated})


# ----------------------------------------------------------------- ③ 人确认

def confirm_candidate(candidate: CandidateExample, *,
                      expected_text: str | None = None) -> CandidateExample:
    """人闸:确认一条候选。`expected_text` 非空即表示"我改过了,以我的为准"。

    没有"全部确认"的批量口子 —— 与计划确认(`confirm_plan` 逐项)同律:
    一次点击只为一条负责,才叫确认。
    """
    text = expected_text if expected_text is not None else candidate.upstream_output
    if text is None or not str(text).strip():
        raise ExampleProposalError(
            f"{candidate.input_name}:上游对这条输入抛错,做不成 golden 样例"
            "(样例只表达成功路径)。它的正当去处是**写进题面的错误行为**:"
            "把「这类输入应当报错并 exit 1」说清楚。上游错误:"
            f"{candidate.upstream_error}")
    return candidate.model_copy(update={"upstream_output": str(text), "confirmed": True})


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
