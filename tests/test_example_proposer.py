"""Golden 样例助手的钉死 —— 重点是**它没有接管真值判定**。

正面能力(降低上手门槛)与负面边界(不许模型写答案、不许批量放行、
抽查不许用见过的输入)一一对应;负控比正控重要,去 flake/图方便都不许
把它们掏空。

零网络:上游用合成的迷你包,reference 真 import 它 —— 与产线同一条
语义(reference 必须真调上游),只是把"上游"换成可控物。
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from repoproof.adoption.intake import example_proposer
from repoproof.adoption.intake.example_proposer import (
    CandidateExample,
    ExampleProposalError,
    ProposalBatch,
    ReferenceIsolationError,
    ReferenceWheelhouseIntegrityError,
    _sandboxed_reference_argv,
    assert_unseen_input,
    confirm_candidate,
    ensure_reference_wheelhouse,
    prepared_reference_environment,
    propose_inputs,
    public_reference_failure,
    reference_wheelhouse_runtime_identity,
    run_reference_on_candidates,
    upstream_runtime_identity,
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


def test_proposer_keeps_private_examples_and_raw_failures_out_of_drafter_context():
    private_sample = "PRIVATE-SAMPLE-BODY-4b20"
    raw_reference_error = "UserInputError: /Users/alice/secret says hunter2"
    d = _StubDrafter([
        {"input_name": "fresh.txt", "input_text": "fresh", "why": "new"},
    ])
    batch = propose_inputs(
        goal="喊话",
        overview={
            "failed_attempts": [{
                "input_name": "private.txt",
                "input_text": private_sample,
                "upstream_error": raw_reference_error,
                "reason_code": "REFERENCE_USER_INPUT_ERROR",
                "failure_fingerprint": "a" * 64,
            }],
        },
        drafter=d,
        n=1,
        existing_inputs=[private_sample],
        existing_names=["private.txt"],
    )

    encoded = str(d.seen_context)
    assert private_sample not in encoded
    assert raw_reference_error not in encoded
    assert "private.txt" not in encoded
    assert "already_have" not in d.seen_context
    assert d.seen_context["existing_input_count"] == 1
    assert d.seen_context["failed_attempts"][0]["reason_code"] == (
        "REFERENCE_USER_INPUT_ERROR"
    )
    assert d.seen_context["failed_attempts"][0]["failure_fingerprint"] != "a" * 64
    assert len(d.seen_context["failed_attempts"][0]["failure_fingerprint"]) == 64
    assert [candidate.input_text for candidate in batch.candidates] == ["fresh"]


def test_public_reference_failure_fingerprint_never_depends_on_error_message():
    first = public_reference_failure(
        upstream_error="UserInputError: TOP-SECRET-CONTENT",
    )
    second = public_reference_failure(
        upstream_error="UserInputError: /Users/alice/private/data.txt",
    )

    assert first == second
    assert first["reason_code"] == "REFERENCE_USER_INPUT_ERROR"
    assert "SECRET" not in str(first)
    assert "/Users" not in str(first)


def test_proposer_allocates_unique_names_across_existing_and_same_batch():
    d = _StubDrafter([
        {"input_name": "case.txt", "input_text": "one", "why": ""},
        {"input_name": "case.txt", "input_text": "two", "why": ""},
    ])
    batch = propose_inputs(
        goal="喊话",
        overview={},
        drafter=d,
        n=2,
        existing_names=["case.txt"],
    )
    assert [c.input_name for c in batch.candidates] == ["case-2.txt", "case-3.txt"]


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
        batch,
        draft_dir=world["draft"],
        upstream_dir=world["upstream"],
        import_module="minishout",
    )
    ok, bad = out.candidates
    assert ok.upstream_output == "HELLO!" and ok.usable_as_golden
    # 上游抛错如实记下,并且**不算**可做 golden(样例只表达成功路径)
    assert bad.upstream_output is None and "empty input" in (bad.upstream_error or "")
    assert not bad.usable_as_golden
    assert ok.truth_evidence is not None
    assert bad.truth_evidence is not None
    assert ok.truth_evidence.evidence_id != bad.truth_evidence.evidence_id
    assert ok.truth_evidence.correlation_id != bad.truth_evidence.correlation_id
    assert ok.truth_evidence.calls == 1
    assert bad.truth_evidence.calls == 1
    assert ok.managed_runtime_evidence is not None
    assert "managed_runtime_evidence" not in ok.model_dump(mode="json")
    assert out.reference_evidence == {
        "schema_version": 2,
        "kind": "CANDIDATE_SCOPED_RUNTIME_UPSTREAM_CALL_SUMMARY",
        "import_module": "minishout",
        "reference_sha256": out.reference_evidence["reference_sha256"],
        "upstream_identity_sha256": out.reference_evidence[
            "upstream_identity_sha256"
        ],
        "candidate_evidence_ids": [
            ok.truth_evidence.evidence_id,
            bad.truth_evidence.evidence_id,
        ],
    }


def test_upstream_run_never_turns_a_truncated_output_into_truth(world):
    """Large reference output must stop visibly, never become a partial golden."""
    (world["draft"] / "reference_impl.py").write_text(
        "from pathlib import Path\n\n"
        "def extract(input_path: Path) -> str:\n"
        "    return 'x' * 20001\n",
        encoding="utf-8",
    )
    out = run_reference_on_candidates(
        ProposalBatch(candidates=[CandidateExample(input_name="large.txt", input_text="x")]),
        draft_dir=world["draft"],
        upstream_dir=world["upstream"],
    )
    candidate = out.candidates[0]
    assert candidate.upstream_output is None
    assert candidate.upstream_output_truncated is True
    assert "ReferenceOutputTooLarge" in (candidate.upstream_error or "")
    assert not candidate.usable_as_golden


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
    monkeypatch.setenv("REPOPROOF_API_KEY", "test-secret-that-must-never-be-visible")
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


@pytest.mark.skipif(
    sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file(),
    reason="macOS reference sandbox conformance",
)
def test_studio_reference_runtime_denies_network_and_writes_outside_probe(
    world: dict[str, Path],
    tmp_path: Path,
) -> None:
    outside = tmp_path / "must-not-be-written.txt"
    (world["draft"] / "reference_impl.py").write_text(
        "import errno\n"
        "import socket\n"
        "from pathlib import Path\n\n\n"
        "def extract(input_path: Path) -> str:\n"
        "    sock = socket.socket()\n"
        "    network_errno = sock.connect_ex(('127.0.0.1', 9))\n"
        "    sock.close()\n"
        "    try:\n"
        f"        Path({str(outside)!r}).write_text('escape')\n"
        "    except OSError as exc:\n"
        "        write_errno = exc.errno\n"
        "    else:\n"
        "        write_errno = 0\n"
        "    return f'{network_errno}:{write_errno}'\n",
        encoding="utf-8",
    )
    out = run_reference_on_candidates(
        ProposalBatch(
            candidates=[CandidateExample(input_name="case.txt", input_text="x")]
        ),
        draft_dir=world["draft"],
        upstream_dir=world["upstream"],
        isolation_required=True,
    )
    assert out.candidates[0].upstream_output == "1:1"
    assert not outside.exists()


def test_required_reference_isolation_fails_closed_without_reviewed_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(ReferenceIsolationError, match="没有受支持"):
        _sandboxed_reference_argv(["python", "runner.py"], tmp_path)


def _write_test_wheel(
    dest: Path,
    *,
    distribution: str,
    package: str,
    source: str,
    requires: list[str] | None = None,
) -> None:
    """Build the smallest standards-compliant pure Python wheel, offline."""

    version = "1.0.0"
    wheel_name = f"{distribution}-{version}-py3-none-any.whl"
    dist_info = f"{distribution}-{version}.dist-info"
    metadata = [
        "Metadata-Version: 2.1",
        f"Name: {distribution}",
        f"Version: {version}",
    ]
    metadata.extend(f"Requires-Dist: {requirement}" for requirement in (requires or []))
    with zipfile.ZipFile(dest / wheel_name, "w") as archive:
        archive.writestr(f"{package}/__init__.py", source)
        archive.writestr(f"{dist_info}/METADATA", "\n".join(metadata) + "\n")
        archive.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: repoproof-test\n"
            "Root-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(f"{dist_info}/RECORD", "")


def test_reference_wheelhouse_cache_is_hash_bound_reused_and_tamper_evident(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = tmp_path / "reference.lock.txt"
    lock.write_text("rootpkg==1.0.0\n", encoding="utf-8")
    cache = tmp_path / "reference-wheelhouses"
    downloads: list[list[str]] = []

    def fake_download(argv, **_kwargs):
        args = [str(item) for item in argv]
        downloads.append(args)
        destination = Path(args[args.index("--dest") + 1])
        _write_test_wheel(
            destination,
            distribution="rootpkg",
            package="rootpkg",
            source="VALUE = 'cached'\n",
        )
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(example_proposer.subprocess, "run", fake_download)

    first = ensure_reference_wheelhouse(lock, cache_root=cache)
    second = ensure_reference_wheelhouse(lock, cache_root=cache)

    assert first == second
    assert len(downloads) == 1
    assert (first / "manifest.json").is_file()

    wheel = next(first.glob("*.whl"))
    wheel.write_bytes(wheel.read_bytes() + b"tampered")
    with pytest.raises(ReferenceWheelhouseIntegrityError):
        ensure_reference_wheelhouse(lock, cache_root=cache)
    assert len(downloads) == 1, "tampered evidence must fail closed, not redownload"


def test_reference_environment_installs_transitive_wheels_but_runs_pinned_source(
    tmp_path: Path,
) -> None:
    """The source checkout wins while its wheel-only dependency is available.

    This is the exact feedparser failure shape: importing the pinned source
    requires ``feedparser-sgmllib``, which is not present in the checkout.
    Candidate generation must build that closure before asking an LLM for an
    input, rather than misclassifying ModuleNotFoundError as a bad candidate.
    """

    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "reference.lock.txt").write_text("rootpkg==1.0.0\n", encoding="utf-8")
    (draft / "reference_impl.py").write_text(
        "from pathlib import Path\nimport rootpkg\n\n"
        "def extract(input_path: Path) -> str:\n"
        "    return rootpkg.convert(input_path.read_text(encoding='utf-8'))\n",
        encoding="utf-8",
    )
    upstream = tmp_path / "upstream"
    (upstream / "src" / "rootpkg").mkdir(parents=True)
    (upstream / "src" / "rootpkg" / "__init__.py").write_text(
        "import helperpkg\n\n"
        "def convert(text):\n"
        "    return 'SOURCE:' + helperpkg.decorate(text)\n",
        encoding="utf-8",
    )
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    _write_test_wheel(
        wheels,
        distribution="rootpkg",
        package="rootpkg",
        source="def convert(text):\n    return 'WHEEL:' + text\n",
        requires=["helperpkg==1.0.0"],
    )
    _write_test_wheel(
        wheels,
        distribution="helperpkg",
        package="helperpkg",
        source="def decorate(text):\n    return text.strip().upper()\n",
    )

    batch = ProposalBatch(candidates=[
        CandidateExample(input_name="case.txt", input_text="hello"),
    ])
    with prepared_reference_environment(draft, wheelhouse=wheels) as python_exe:
        out = run_reference_on_candidates(
            batch,
            draft_dir=draft,
            upstream_dir=upstream,
            python_exe=python_exe,
        )

    assert out.candidates[0].upstream_output == "SOURCE:HELLO"


def test_admitted_runtime_uses_locked_wheel_without_unbuilt_source_shadow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Product runtime imports the admitted wheel; checkout remains provenance.

    Extension-backed projects often cannot import directly from a checkout.
    A source package that references an absent compiled module therefore models
    the Biopython failure without coupling the Harness test to Biopython.
    """

    draft = tmp_path / "draft"
    draft.mkdir()
    lock = draft / "reference.lock.txt"
    lock.write_text("rootpkg==1.0.0\n", encoding="utf-8")
    (draft / "reference_impl.py").write_text(
        "from pathlib import Path\nimport rootpkg\n\n"
        "def extract(input_path: Path) -> str:\n"
        "    return rootpkg.convert(input_path.read_text(encoding='utf-8'))\n",
        encoding="utf-8",
    )
    upstream = tmp_path / "upstream"
    (upstream / "src" / "rootpkg").mkdir(parents=True)
    (upstream / "src" / "rootpkg" / "__init__.py").write_text(
        "from . import _native\n\n"
        "def convert(text):\n    return _native.convert(text)\n",
        encoding="utf-8",
    )
    cache = tmp_path / "reference-wheelhouses"

    def fake_download(argv, **_kwargs):
        args = [str(item) for item in argv]
        destination = Path(args[args.index("--dest") + 1])
        _write_test_wheel(
            destination,
            distribution="rootpkg",
            package="rootpkg",
            source="def convert(text):\n    return 'WHEEL:' + text.strip().upper()\n",
        )
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(example_proposer.subprocess, "run", fake_download)
    # Materialise through the real content-addressed cache path, then restore
    # subprocess so venv creation and offline installation are real.
    ensure_reference_wheelhouse(lock, cache_root=cache)
    monkeypatch.undo()
    runtime_sha = reference_wheelhouse_runtime_identity(lock, cache_root=cache)
    batch = ProposalBatch(candidates=[
        CandidateExample(input_name="case.txt", input_text="hello"),
    ])
    with prepared_reference_environment(
        draft,
        wheelhouse_cache_root=cache,
    ) as python_exe:
        out = run_reference_on_candidates(
            batch,
            draft_dir=draft,
            upstream_dir=upstream,
            python_exe=python_exe,
            import_module="rootpkg",
            runtime_artifact_sha256=runtime_sha,
        )

    assert out.candidates[0].upstream_output == "WHEEL:HELLO"
    evidence = out.candidates[0].truth_evidence
    assert evidence is not None
    assert evidence.upstream_identity_sha256 == upstream_runtime_identity(
        upstream,
        import_module="rootpkg",
        runtime_artifact_sha256=runtime_sha,
    )
    assert evidence.upstream_identity_sha256 != upstream_runtime_identity(
        upstream,
        import_module="rootpkg",
    )


def test_core_resolved_lock_can_prepare_reference_without_mutating_draft(
    tmp_path: Path,
) -> None:
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "reference_impl.py").write_text(
        "from pathlib import Path\nimport rootpkg\n\n"
        "def extract(input_path: Path) -> str:\n"
        "    return rootpkg.convert(input_path.read_text(encoding='utf-8'))\n",
        encoding="utf-8",
    )
    upstream = tmp_path / "upstream"
    (upstream / "rootpkg").mkdir(parents=True)
    (upstream / "rootpkg" / "__init__.py").write_text(
        "import helperpkg\n\n"
        "def convert(text):\n"
        "    return 'SOURCE:' + helperpkg.decorate(text)\n",
        encoding="utf-8",
    )
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    _write_test_wheel(
        wheels,
        distribution="rootpkg",
        package="rootpkg",
        source="def convert(text):\n    return 'WHEEL:' + text\n",
        requires=["helperpkg==1.0.0"],
    )
    _write_test_wheel(
        wheels,
        distribution="helperpkg",
        package="helperpkg",
        source="def decorate(text):\n    return text.strip().upper()\n",
    )
    batch = ProposalBatch(candidates=[
        CandidateExample(input_name="case.txt", input_text="hello"),
    ])

    with prepared_reference_environment(
        draft,
        wheelhouse=wheels,
        resolved_lock_text="rootpkg==1.0.0\n",
    ) as python_exe:
        out = run_reference_on_candidates(
            batch,
            draft_dir=draft,
            upstream_dir=upstream,
            python_exe=python_exe,
        )

    assert out.candidates[0].upstream_output == "SOURCE:HELLO"
    assert not (draft / "reference.lock.txt").exists()


# ----------------------------------------------------------------- ③ 人确认

def _candidate_with_truth(world, text: str = "hi") -> CandidateExample:
    return run_reference_on_candidates(
        ProposalBatch(candidates=[CandidateExample(input_name="a.txt", input_text=text)]),
        draft_dir=world["draft"],
        upstream_dir=world["upstream"],
        import_module="minishout",
    ).candidates[0]


def test_confirm_flips_the_bit_and_records_provenance(world):
    c = _candidate_with_truth(world)
    done = confirm_candidate(c)
    assert done.confirmed and done.truth_provenance() == "UPSTREAM_DERIVED_USER_CONFIRMED"
    assert not c.confirmed, "确认必须返回新对象,不许就地改掉原候选"


def test_confirm_accepts_user_override(world):
    c = _candidate_with_truth(world)
    done = confirm_candidate(c, expected_text="HI!!(我改的)")
    assert done.upstream_output == "HI!!(我改的)" and done.confirmed
    assert done.truth_provenance() == "USER_OVERRIDDEN"


def test_empty_upstream_stdout_is_a_confirmable_exact_output(world):
    (world["draft"] / "reference_impl.py").write_text(
        "from pathlib import Path\nimport minishout\n\n"
        "def extract(input_path: Path) -> str:\n"
        "    minishout.shout(input_path.read_text())\n"
        "    return ''\n",
        encoding="utf-8",
    )
    c = run_reference_on_candidates(
        ProposalBatch(candidates=[CandidateExample(
            input_name="empty-output.txt",
            input_text="quiet",
        )]),
        draft_dir=world["draft"],
        upstream_dir=world["upstream"],
        import_module="minishout",
    ).candidates[0]
    assert c.usable_as_golden
    done = confirm_candidate(c)
    assert done.confirmed and done.upstream_output == ""


def test_confirm_refuses_error_candidate_and_says_where_it_belongs():
    """**负控**:上游抛错的候选不能被确认成 golden;提示要指出正当去处。"""
    c = CandidateExample(input_name="bad.txt", input_text="",
                         upstream_error="UserInputError: empty input")
    with pytest.raises(ExampleProposalError, match="题面"):
        confirm_candidate(c)


def test_historical_candidate_without_scoped_evidence_cannot_mint_new_truth():
    legacy = CandidateExample(
        input_name="legacy.txt",
        input_text="old",
        upstream_output="OLD!",
    )
    # Historical data remains readable, but a new confirmation fails closed.
    assert legacy.input_name == "legacy.txt"
    with pytest.raises(ExampleProposalError, match="CANDIDATE_TRUTH_EVIDENCE_MISSING"):
        confirm_candidate(legacy)


# --------------------------------------------------------- fresh 抽查去重闸

def test_fresh_audit_input_must_be_unseen():
    """**负控**:抽查用见过的输入 = 复读,不是独立检查 —— 硬拒。"""
    with pytest.raises(ExampleProposalError, match="没见过的输入"):
        assert_unseen_input("red\n", ["  red  ", "navy"])
    assert_unseen_input("teal", ["red", "navy"])       # 没见过 → 放行


# ----------------------------------------------- reference 上游运行时调用证据

def test_reference_without_runtime_upstream_call_cannot_mint_truth(world):
    """Importing a package is not evidence that its capability produced truth."""
    (world["draft"] / "reference_impl.py").write_text(
        "from pathlib import Path\n\nimport minishout\n\n\n"
        "def extract(input_path: Path) -> str:\n"
        "    data = input_path.read_text(encoding='utf-8')\n"
        "    return str(minishout)\n", encoding="utf-8")
    with pytest.raises(ExampleProposalError, match="REFERENCE_UPSTREAM_CALL_NOT_OBSERVED"):
        run_reference_on_candidates(
            ProposalBatch(candidates=[CandidateExample(input_name="a.txt", input_text="x")]),
            draft_dir=world["draft"],
            upstream_dir=world["upstream"],
            import_module="minishout",
        )


def test_reference_call_evidence_is_independent_of_source_code_shape(world):
    """A real call passes even when written in a form no source heuristic knows."""
    (world["draft"] / "reference_impl.py").write_text(
        "import minishout\n\n\ndef extract(p):\n"
        "    operation = getattr(minishout, 'shout')\n"
        "    return str(operation(p.read_text()))\n",
        encoding="utf-8",
    )
    out = run_reference_on_candidates(
        ProposalBatch(candidates=[CandidateExample(input_name="a.txt", input_text="hi")]),
        draft_dir=world["draft"],
        upstream_dir=world["upstream"],
        import_module="minishout",
    )
    assert out.candidates[0].upstream_output == "HI!"
    assert out.candidates[0].truth_evidence is not None
    assert out.candidates[0].truth_evidence.calls == 1


def test_one_candidate_cannot_borrow_another_candidates_upstream_calls(world):
    """Two calls in candidate A cannot satisfy candidate B's zero-call output."""

    (world["draft"] / "reference_impl.py").write_text(
        "from pathlib import Path\nimport minishout\n\n"
        "def extract(input_path: Path) -> str:\n"
        "    text = input_path.read_text()\n"
        "    if text == 'borrow':\n"
        "        return 'LOCAL-ONLY'\n"
        "    return minishout.shout(text) + minishout.shout(text)\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ExampleProposalError,
        match="REFERENCE_UPSTREAM_CALL_NOT_OBSERVED",
    ):
        run_reference_on_candidates(
            ProposalBatch(candidates=[
                CandidateExample(input_name="real.txt", input_text="real"),
                CandidateExample(input_name="borrow.txt", input_text="borrow"),
            ]),
            draft_dir=world["draft"],
            upstream_dir=world["upstream"],
            import_module="minishout",
        )


# --------------------------------------------------------------- 证据挖掘

def test_evidence_mining_prefers_readme_then_upstream_tests(tmp_path: Path):
    """从**上游自己的证据**里挖候选输入,而不是凭空发明。

    2026-08-27 实测:离线模板是域盲的 —— 它给"典型输入""非 ASCII 输入"
    这种通用串,对 webcolors 那类任务 6 条候选全部让上游抛错,等于没帮上忙。
    README 的 doctest 里却躺着 `hex_to_name("#daa520")`:作者亲手写的、
    保证有意义的输入。次级来源是上游自己的测试(「这库到底吃什么输入」
    的最好证据),只取提到公开入口的行,避免把断言消息一起挖进来。
    """
    from repoproof.adoption.intake.example_proposer import mine_evidence_literals

    up = tmp_path / "up"
    (up / "tests").mkdir(parents=True)
    (up / "README.md").write_text(
        "# demo\n\n```python\n>>> import demo\n>>> demo.shout('hello')\n'HELLO!'\n```\n",
        encoding="utf-8")
    (up / "tests" / "test_demo.py").write_text(
        "import demo\n\n\n"
        "def test_a():\n"
        "    assert demo.shout('world') == 'WORLD!'\n"
        "    assert True, 'unrelated assertion message'\n",
        encoding="utf-8")

    mined = mine_evidence_literals(up, import_module_names=["demo"])
    assert "hello" in mined                    # README 优先
    assert "world" in mined                    # 上游测试作次级来源
    assert "unrelated assertion message" not in mined   # 不提入口的行不挖


def test_evidence_mining_survives_missing_readme(tmp_path: Path):
    """没有 README 也不许炸 —— 挖不到就返回空,由通用边界候选兜底。"""
    from repoproof.adoption.intake.example_proposer import mine_evidence_literals

    up = tmp_path / "bare"
    up.mkdir()
    assert mine_evidence_literals(up) == []


def test_offline_drafter_puts_evidence_first():
    """离线起草:证据候选排在通用模板前面(数量有限时先给能用的)。"""
    from repoproof.adoption.intake.tool_drafter import FakeDrafter

    got = FakeDrafter().propose_example_inputs(
        {"how_many": 3, "capability_goal": "x", "evidence_literals": ["#daa520"]})
    assert got["inputs"][0]["input_text"] == "#daa520"
    assert "证据挖掘" in got["inputs"][0]["why"]
