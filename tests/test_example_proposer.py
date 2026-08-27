"""Golden 样例助手的钉死 —— 重点是**它没有接管真值判定**。

正面能力(降低上手门槛)与负面边界(不许模型写答案、不许批量放行、
抽查不许用见过的输入)一一对应;负控比正控重要,去 flake/图方便都不许
把它们掏空。

零网络:上游用合成的迷你包,reference 真 import 它 —— 与产线同一条
语义(reference 必须真调上游),只是把"上游"换成可控物。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repoproof.adoption.intake.example_proposer import (
    CandidateExample,
    ExampleProposalError,
    ProposalBatch,
    assert_unseen_input,
    confirm_candidate,
    propose_inputs,
    run_reference_on_candidates,
)

_UPSTREAM = '''
def shout(text):
    if not text.strip():
        raise ValueError("empty input")
    return text.strip().upper() + "!"
'''

_REFERENCE = '''"""reference:真调 pinned 上游。"""
from pathlib import Path

import minishout


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        return minishout.shout(input_path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise UserInputError(str(e)) from e
'''


class _StubDrafter:
    name = "stub"

    def __init__(self, inputs):
        self._inputs = inputs
        self.seen_context: dict = {}

    def propose_example_inputs(self, context):
        self.seen_context = context
        return {"inputs": self._inputs}


@pytest.fixture
def world(tmp_path: Path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    (upstream / "minishout.py").write_text(_UPSTREAM, encoding="utf-8")
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "reference_impl.py").write_text(_REFERENCE, encoding="utf-8")
    return {"upstream": upstream, "draft": draft}


# ------------------------------------------------------------- ① 候选输入

def test_proposer_keeps_empty_input_as_a_legitimate_edge_case():
    """空输入是**最有价值**的边界样本之一,不许因为"看起来空"被吃掉。

    早期实现用 `not text.strip()` 过滤,恰好把它静默丢了(实测)。"""
    d = _StubDrafter([{"input_name": "a.txt", "input_text": "hi", "why": "典型"},
                      {"input_name": "empty.txt", "input_text": "", "why": "空输入"}])
    batch = propose_inputs(goal="喊话", overview={}, drafter=d, n=4)
    assert [c.input_name for c in batch.candidates] == ["a.txt", "empty.txt"]


def test_proposer_dedupes_against_existing_and_itself():
    d = _StubDrafter([{"input_name": "a.txt", "input_text": "hi", "why": ""},
                      {"input_name": "b.txt", "input_text": "hi\n", "why": ""},   # 仅行尾差异
                      {"input_name": "c.txt", "input_text": "seen", "why": ""},   # 与既有重合
                      {"input_name": "d.txt", "input_text": "fresh", "why": ""}])
    batch = propose_inputs(goal="喊话", overview={}, drafter=d, n=8,
                           existing_inputs=["seen"])
    assert [c.input_text for c in batch.candidates] == ["hi", "fresh"]


def test_proposer_never_marks_anything_confirmed():
    """**负控**:助手产出的候选一律 unconfirmed —— confirmed 只能由人翻。"""
    d = _StubDrafter([{"input_name": "a.txt", "input_text": "hi", "why": ""}])
    batch = propose_inputs(goal="喊话", overview={}, drafter=d)
    assert all(not c.confirmed for c in batch.candidates)
    assert all(c.truth_provenance() == "UNCONFIRMED" for c in batch.candidates)


# --------------------------------------------------- ② 上游真跑(候选输出)

def test_upstream_run_produces_real_outputs_and_records_errors(world):
    batch = ProposalBatch(candidates=[
        CandidateExample(input_name="ok.txt", input_text="hello"),
        CandidateExample(input_name="empty.txt", input_text="   "),
    ])
    out = run_reference_on_candidates(
        batch, draft_dir=world["draft"], upstream_dir=world["upstream"])
    ok, bad = out.candidates
    assert ok.upstream_output == "HELLO!" and ok.usable_as_golden
    # 上游抛错如实记下,并且**不算**可做 golden(样例只表达成功路径)
    assert bad.upstream_output is None and "empty input" in (bad.upstream_error or "")
    assert not bad.usable_as_golden


def test_upstream_run_refuses_skeleton_reference(world):
    """reference 还是骨架时,候选输出没有来源 —— 如实拒绝,不猜。"""
    (world["draft"] / "reference_impl.py").write_text(
        "def extract(p):\n    raise NotImplementedError\n", encoding="utf-8")
    with pytest.raises(ExampleProposalError, match="骨架"):
        run_reference_on_candidates(
            ProposalBatch(candidates=[CandidateExample(input_name="a.txt", input_text="x")]),
            draft_dir=world["draft"], upstream_dir=world["upstream"])


def test_upstream_run_env_is_sanitised(world, monkeypatch):
    """**负控**:被执行的第三方代码不得看见密钥与连接配置。"""
    monkeypatch.setenv("REPOPROOF_API_KEY", "sk-should-never-be-visible")
    monkeypatch.setenv("REPOPROOF_API_BASE", "https://secret.invalid")
    (world["draft"] / "reference_impl.py").write_text(
        "import os\nfrom pathlib import Path\n\n\n"
        "def extract(input_path: Path) -> str:\n"
        "    return ','.join(sorted(k for k in os.environ if 'REPOPROOF' in k or k.endswith('KEY')))\n",
        encoding="utf-8")
    out = run_reference_on_candidates(
        ProposalBatch(candidates=[CandidateExample(input_name="a.txt", input_text="x")]),
        draft_dir=world["draft"], upstream_dir=world["upstream"])
    assert out.candidates[0].upstream_output == "", out.candidates[0].upstream_output


# ----------------------------------------------------------------- ③ 人确认

def test_confirm_flips_the_bit_and_records_provenance(world):
    c = CandidateExample(input_name="a.txt", input_text="hi", upstream_output="HI!")
    done = confirm_candidate(c)
    assert done.confirmed and done.truth_provenance() == "UPSTREAM_DERIVED_USER_CONFIRMED"
    assert not c.confirmed, "确认必须返回新对象,不许就地改掉原候选"


def test_confirm_accepts_user_override():
    c = CandidateExample(input_name="a.txt", input_text="hi", upstream_output="HI!")
    done = confirm_candidate(c, expected_text="HI!!(我改的)")
    assert done.upstream_output == "HI!!(我改的)" and done.confirmed


def test_confirm_refuses_error_candidate_and_says_where_it_belongs():
    """**负控**:上游抛错的候选不能被确认成 golden;提示要指出正当去处。"""
    c = CandidateExample(input_name="bad.txt", input_text="",
                         upstream_error="UserInputError: empty input")
    with pytest.raises(ExampleProposalError, match="题面"):
        confirm_candidate(c)


# --------------------------------------------------------- fresh 抽查去重闸

def test_fresh_audit_input_must_be_unseen():
    """**负控**:抽查用见过的输入 = 复读,不是独立检查 —— 硬拒。"""
    with pytest.raises(ExampleProposalError, match="没见过的输入"):
        assert_unseen_input("red\n", ["  red  ", "navy"])
    assert_unseen_input("teal", ["red", "navy"])       # 没见过 → 放行


# ------------------------------------------------- reference 占位检测(真实事故)

def test_placeholder_reference_is_refused(world):
    """**负控**:起草占位(`return str(<上游模块>)`)不许拿来产候选输出。

    2026-08-27 用户实测:离线模板起草出的 reference 真 import 了上游、
    也有确定性输出,所以骨架检查(NotImplementedError)放它过去 —— 但它
    没实现任何能力。拿它跑候选,每条"上游实际输出"都是模块地址,用户一
    确认就把 `<module 'webcolors' from ...>` 冻进了验收真值:一个看起来
    全绿、实则空心的合同。
    """
    (world["draft"] / "reference_impl.py").write_text(
        "from pathlib import Path\n\nimport minishout\n\n\n"
        "def extract(input_path: Path) -> str:\n"
        "    data = input_path.read_text(encoding='utf-8')\n"
        "    return str(minishout)\n", encoding="utf-8")
    with pytest.raises(ExampleProposalError, match="起草占位"):
        run_reference_on_candidates(
            ProposalBatch(candidates=[CandidateExample(input_name="a.txt", input_text="x")]),
            draft_dir=world["draft"], upstream_dir=world["upstream"])


def test_real_reference_is_not_mistaken_for_placeholder(world):
    """**正控**:真实现不许被误伤 —— 判别只认那一个精确形状(AST)。"""
    from repoproof.adoption.intake.example_proposer import reference_is_placeholder

    assert reference_is_placeholder(
        (world["draft"] / "reference_impl.py").read_text(encoding="utf-8")) == ""
    # 返回值里**包含** str(...) 但不是裸模块 → 真实现,放行
    assert reference_is_placeholder(
        "import minishout\n\n\ndef extract(p):\n"
        "    return str(minishout.shout(p.read_text()))\n") == ""
