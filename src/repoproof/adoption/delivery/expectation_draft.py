"""期望草稿(RFC-008 §八)— 上游实际输出只是「能力证据」,不是期望。

流程:隔离环境跑 pinned upstream 的公开样例(probe 可注入:真实用
容器,测试用 fake)→ 生成候选期望并标注每个字段来源(上游原生/
宿主已有 Schema/建议新增/不确定)→ 用户逐条编辑与确认 → 全部确认
且覆盖 正常/边界/错误 三类输入后,才允许导出为 RequirementSpec/
装配用样例。未确认不可 Freeze(结构性强制,不是提示)。零 LLM。
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

UPSTREAM_NATIVE = "upstream_native"
HOST_SCHEMA = "host_schema"
SUGGESTED_NEW = "suggested_new"
UNCERTAIN = "uncertain"

NORMAL = "normal"
BOUNDARY = "boundary"
ERROR = "error"

HARD = "hard"
SOFT = "soft"


class DraftNotConfirmed(ValueError):
    pass


class ExpectationCase(BaseModel):
    input: str
    case_kind: str = NORMAL              # normal / boundary / error
    upstream_output: str | None = None   # 证据:pinned upstream 的真实输出
    upstream_error: str | None = None    # 证据:上游异常(错误输入常见)
    candidate_expected: str = ""         # 候选期望(用户可编辑)
    field_origin: str = UNCERTAIN        # 候选期望的来源标注
    hardness: str = HARD                 # hard / soft requirement
    user_confirmed: bool = False         # 用户逐条确认
    note: str = ""


class ExpectationDraft(BaseModel):
    goal: str
    upstream_ref: str                    # distribution@commit,证据锚点
    cases: list[ExpectationCase] = []
    user_reviewed_upstream_evidence: bool = False  # 用户声明已核对证据

    def to_dict(self) -> dict:
        return self.model_dump()

    def unconfirmed(self) -> list[str]:
        return [c.input for c in self.cases if not c.user_confirmed]

    def missing_kinds(self) -> list[str]:
        have = {c.case_kind for c in self.cases}
        return [k for k in (NORMAL, BOUNDARY, ERROR) if k not in have]

    def to_examples(self) -> list[dict]:
        """→ 装配用样例。全部确认 + 三类输入齐 + 用户已核对证据,
        否则 DraftNotConfirmed——上游输出永远不能未经确认变成期望。"""
        problems: list[str] = []
        if self.missing_kinds():
            problems.append(f"缺少输入类型:{self.missing_kinds()}(必须覆盖 正常/边界/错误)")
        if self.unconfirmed():
            problems.append(f"以下样例未经你确认:{self.unconfirmed()}")
        if not self.user_reviewed_upstream_evidence:
            problems.append("你尚未声明已核对上游实际输出证据")
        empty = [c.input for c in self.cases if not c.candidate_expected.strip()]
        if empty:
            problems.append(f"以下样例期望为空:{empty}")
        if problems:
            raise DraftNotConfirmed(";".join(problems))
        return [{"input": c.input, "expected": c.candidate_expected} for c in self.cases]


def probe_from_baseline_junit(
    nodes: list[dict],
    public_examples: list[dict],
) -> Callable[[str], tuple[str | None, str | None]]:
    """把「直连基线」(容器内 pinned upstream 跑公开样例)的 JUnit 结果
    变成探针:test_example_N ↔ 第 N 个公开样例;失败断言消息中的
    「实际: …」片段就是上游真实输出(证据)。这就是 §八 的
    Upstream Calibration 真实来源——隔离环境、固定版本、零手工转录。"""
    by_input: dict[str, tuple[str | None, str | None]] = {}
    for i, ex in enumerate(public_examples, 1):
        node = next((n for n in nodes if n.get("node_id", "").endswith(f"test_example_{i}")), None)
        if node is None:
            by_input[ex["input"]] = (None, "baseline 未覆盖该样例")
        elif node.get("outcome") == "passed":
            by_input[ex["input"]] = (ex.get("expected", ""), None)  # 直连已满足:期望即输出
        else:
            msg = str(node.get("message", ""))
            marker = "实际: "
            if marker in msg:
                by_input[ex["input"]] = (msg.split(marker, 1)[1].strip(), None)
            else:
                by_input[ex["input"]] = (None, msg[:200] or "上游执行失败(无输出)")
    return lambda text: by_input.get(text, (None, "no probe result"))


def build_expectation_draft(
    goal: str,
    upstream_ref: str,
    inputs: list[dict],
    probe: Callable[[str], tuple[str | None, str | None]],
    host_schema_names: list[str] | None = None,
) -> ExpectationDraft:
    """inputs: [{input, case_kind, hardness?}];probe(input) → (output, error)。

    候选期望的生成规则(确定性):
    - 上游正常输出 → candidate = `contains:` 最短稳定片段?不猜——
      candidate 直接给上游输出全文,origin=upstream_native,由用户裁剪;
    - 宿主已有 Schema 命中(输出形如其字段名)→ origin=host_schema;
    - 上游报错的 error 类输入 → candidate 建议 `contains:` 错误类别,
      origin=suggested_new(预期异常需要用户定义包装行为);
    - 探针失败/无输出 → origin=uncertain,candidate 留空强制用户填。
    """
    schema_names = [s.split(" ")[0] for s in (host_schema_names or [])]
    cases: list[ExpectationCase] = []
    for spec in inputs:
        text = spec["input"]
        kind = spec.get("case_kind", NORMAL)
        out, err = probe(text)
        if out is not None:
            origin = HOST_SCHEMA if any(n and n in out for n in schema_names) else UPSTREAM_NATIVE
            cases.append(ExpectationCase(
                input=text, case_kind=kind, upstream_output=out,
                candidate_expected=out, field_origin=origin,
                hardness=spec.get("hardness", HARD),
                note="候选=上游实际输出(证据);请核对并按需要改成 contains: 断言"))
        elif err is not None and kind == ERROR:
            cases.append(ExpectationCase(
                input=text, case_kind=kind, upstream_error=err,
                candidate_expected="", field_origin=SUGGESTED_NEW,
                hardness=spec.get("hardness", HARD),
                note=f"上游对该输入抛出:{err[:120]}——请定义你的项目应有的包装行为(预期异常)"))
        else:
            cases.append(ExpectationCase(
                input=text, case_kind=kind, upstream_error=err,
                candidate_expected="", field_origin=UNCERTAIN,
                hardness=spec.get("hardness", SOFT),
                note="探针未取得输出——期望必须由你给出"))
    return ExpectationDraft(goal=goal, upstream_ref=upstream_ref, cases=cases)
