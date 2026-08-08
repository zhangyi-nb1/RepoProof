"""Phase 3-6 测试(RFC-003..006):Admission 四态 / Plan-only /
Human Gate / Repair Loop。全部零 LLM、零 Docker、零网络。"""

from __future__ import annotations

from pathlib import Path

import pytest

from repoproof.adoption.admission.admission_report import (
    NEED_INFORMATION,
    READY,
    RISK_REVIEW,
    UNSUPPORTED,
    decide,
)
from repoproof.adoption.analysis.host_analyzer import analyze_host_project
from repoproof.adoption.analysis.repository_analyzer import analyze_repository_dir
from repoproof.adoption.intent.intent_parser import parse_intent
from repoproof.adoption.intent.requirement_extractor import extract_requirements
from repoproof.adoption.planning.adoption_plan import build_plan
from repoproof.adoption.planning.human_gate import (
    ACK_TEXT,
    FrozenAdoptionIntent,
    HumanGateError,
    confirm_plan,
    require_confirmed,
)
from repoproof.adoption.planning.plan_validator import PlanInvalid, require_answers, validate_plan
from repoproof.adoption.repair.failure_packet import (
    API_MISMATCH,
    DEPENDENCY_ERROR,
    REGRESSION_FAILURE,
    SCHEMA_ERROR,
    build_failure_packets,
)
from repoproof.adoption.repair.repair_budget import RepairBudget
from repoproof.adoption.repair.repair_loop import (
    STOP_ALL_PUBLIC_PASS,
    STOP_MAX_ROUNDS,
    STOP_SCOPE_CHANGE,
    STOP_STAGNATION,
    RepairLoop,
    RoundResult,
)

REPO = Path(__file__).resolve().parents[2]
ADOPT = REPO / "src" / "repoproof" / "adoption"


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _good_pair(tmp_path: Path):
    """构造 READY 级 host+repo fixture(git 仓库 + 完整声明)。"""
    import subprocess

    host = tmp_path / "host"
    _write(host, "pyproject.toml",
           '[project]\nname="h"\nrequires-python=">=3.11"\ndependencies=["pyyaml"]\n'
           "[tool.pytest.ini_options]\ntestpaths=[\"tests\"]\n")
    _write(host, "app/ingest.py", "def ingest(x):\n    return x\n")
    _write(host, "tests/test_a.py", "def test_a():\n    assert True\n")

    repo = tmp_path / "repo"
    _write(repo, "pyproject.toml",
           '[build-system]\nrequires=["setuptools"]\n[project]\nname="lib"\n'
           'requires-python=">=3.10"\ndependencies=["pyyaml"]\n')
    _write(repo, "LICENSE", "MIT License")
    _write(repo, "README.md", "# lib\n\n```python\nimport lib\n```\n")
    _write(repo, "lib/__init__.py", '__all__ = ["parse"]\n')
    _write(repo, "tests/test_lib.py", "def test_l():\n    assert True\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "x"], check=True, capture_output=True)
    return analyze_host_project(host), analyze_repository_dir(repo)


# ================= Phase 3: Admission =================


def test_admission_ready(tmp_path: Path) -> None:
    host, repo = _good_pair(tmp_path)
    r = decide(host, repo)
    assert r.status == READY, (r.blockers, r.questions, r.risks)
    assert any("版本可固定" in f for f in r.confirmed_facts)
    assert any("CPU" in f for f in r.confirmed_facts)
    assert r.executes_third_party_code is True and r.next_step


def test_admission_need_information(tmp_path: Path) -> None:
    host, repo = _good_pair(tmp_path)
    (tmp_path / "repo" / "LICENSE").unlink()
    repo2 = analyze_repository_dir(tmp_path / "repo")
    r = decide(host, repo2)
    assert r.status == NEED_INFORMATION
    assert any("许可证" in q for q in r.questions)


def test_admission_unsupported_gpu_and_secret(tmp_path: Path) -> None:
    host, _ = _good_pair(tmp_path)
    gpu = tmp_path / "gpu-repo"
    _write(gpu, "requirements.txt", "torch\n")
    _write(gpu, "svc.py", 'import os\nK = os.environ["API_KEY"]\n')
    r = decide(host, analyze_repository_dir(gpu))
    assert r.status == UNSUPPORTED
    assert any("GPU" in b for b in r.blockers)
    assert any("密钥" in b or "secret" in b.lower() for b in r.blockers)
    assert any("无法固定" in b for b in r.blockers)  # 非 git
    assert r.executes_third_party_code is False


def test_admission_risk_review_external_service(tmp_path: Path) -> None:
    host, repo = _good_pair(tmp_path)
    _write(tmp_path / "repo", "requirements.txt", "redis\n")
    repo2 = analyze_repository_dir(tmp_path / "repo")
    r = decide(host, repo2)
    assert r.status == RISK_REVIEW
    assert any("外部服务" in x for x in r.risks)


def test_admission_priority_unsupported_beats_questions(tmp_path: Path) -> None:
    host, _ = _good_pair(tmp_path)
    bad = tmp_path / "bad"
    _write(bad, "requirements.txt", "torch\n")  # blocker + 无 license(question)
    r = decide(host, analyze_repository_dir(bad))
    assert r.status == UNSUPPORTED  # blocker 优先于 question


# ================= Phase 4: Intent + Plan-only =================


def test_intent_parser_three_way_split() -> None:
    d = parse_intent("我想把 eyeseast/python-frontmatter 仓库的元数据解析加入我的RAG项目,输出为 JSON 字典")
    assert d.target_capability == "文档元数据解析"
    assert any("原文" in c for c in d.confirmed)
    assert any("推断" in a for a in d.assumptions)
    assert d.expected_output == "JSON 字典"
    assert any("依赖" in q for q in d.questions)  # 标准问题必出
    assert "预期输入未明确" in d.unknowns  # 没说就是 UNKNOWN,不编


def test_intent_parser_empty_and_vague() -> None:
    assert parse_intent("").questions
    d = parse_intent("帮我搞一下那个库")
    assert d.target_capability == "" and d.unknowns and len(d.questions) >= 3


def test_requirement_extractor_draft_only() -> None:
    d = parse_intent("加入PDF解析,输出为 markdown,不允许新增依赖")
    reqs = extract_requirements(d)
    assert all(r.status == "DRAFT" for r in reqs)
    assert any(r.id == "input-guard" and r.owner == "HOST_INPUT_GUARD" for r in reqs)
    assert any(r.owner == "ADAPTER" for r in reqs)
    assert any("不允许新增依赖" in r.public_text for r in reqs)


def test_plan_only_builds_and_refuses_non_ready(tmp_path: Path) -> None:
    host, repo = _good_pair(tmp_path)
    adm = decide(host, repo)
    intent = parse_intent("把元数据解析能力接入我的项目,输出为 dict")
    plan = build_plan(intent, host, repo, adm)
    assert "PYTHON_ADAPTER" in plan.recommended  # RFC-008:八策略命名,公开 API 存在时推荐薄适配层
    assert plan.questions  # admission/intent 的开放问题必须传导到计划
    assert any("原有测试" in s for s in plan.success_criteria)
    assert validate_plan(plan) == []
    # 非 READY 拒绝出计划
    gpu = tmp_path / "g"
    _write(gpu, "requirements.txt", "torch\n")
    bad_adm = decide(host, analyze_repository_dir(gpu))
    with pytest.raises(ValueError, match="不能生成采用计划"):
        build_plan(intent, host, analyze_repository_dir(gpu), bad_adm)


def test_plan_layer_is_static_no_tools() -> None:
    """Plan-only 铁律:intent/planning/admission 模块禁 shell/write/docker/git/LLM。"""
    banned = ("subprocess", "os.system", "write_text(", "write_bytes(", "shutil",
              "docker", "litellm", "openai", "urllib", "requests.")
    for sub in ("intent", "planning", "admission"):
        for p in (ADOPT / sub).rglob("*.py"):
            src = p.read_text(encoding="utf-8")
            for b in banned:
                assert b not in src, f"{p.name}: {b}"


# ================= Phase 5: Human Gate =================


def _ready_plan(tmp_path: Path):
    host, repo = _good_pair(tmp_path)
    adm = decide(host, repo)
    plan = build_plan(parse_intent("接入元数据解析,输出为 dict"), host, repo, adm)
    answers = {q: "已确认" for q in plan.questions}
    return plan, adm, answers


def test_human_gate_confirm_roundtrip_and_tamper(tmp_path: Path) -> None:
    plan, adm, answers = _ready_plan(tmp_path)
    intent = confirm_plan(plan, adm, answers=answers, user_ack=ACK_TEXT,
                          confirmed_at="2026-08-08T00:00:00")
    assert isinstance(intent, FrozenAdoptionIntent)
    require_confirmed(intent, plan, adm)  # 通过
    plan.goal = plan.goal + "(偷偷改)"
    with pytest.raises(HumanGateError, match="被修改"):
        require_confirmed(intent, plan, adm)


def test_human_gate_blocks_unconfirmed_execution(tmp_path: Path) -> None:
    plan, adm, _ = _ready_plan(tmp_path)
    with pytest.raises(HumanGateError, match="尚未确认"):
        require_confirmed(None, plan, adm)  # §十五:未确认禁止执行


def test_human_gate_requires_answers_and_exact_ack(tmp_path: Path) -> None:
    plan, adm, answers = _ready_plan(tmp_path)
    with pytest.raises(PlanInvalid):
        require_answers(plan, {})
    with pytest.raises(HumanGateError, match="未回答|不能确认"):
        confirm_plan(plan, adm, answers={}, user_ack=ACK_TEXT, confirmed_at="t")
    with pytest.raises(HumanGateError, match="确认语"):
        confirm_plan(plan, adm, answers=answers, user_ack="好的", confirmed_at="t")


# ================= Phase 6: Repair Loop =================


def _round_seq(results):
    calls = {"n": 0, "packets_seen": [], "best_seen": []}

    def run_round(i, packets, best_snapshot):
        calls["n"] += 1
        calls["packets_seen"].append(list(packets))
        calls["best_seen"].append(best_snapshot)
        return results[i - 1]

    return run_round, calls


def _rr(passed, failed, **kw):
    return RoundResult(adapter_snapshot=f"v{passed}", passed=passed,
                       failed_nodes=failed, **kw)


def test_repair_three_round_limit_and_checkpoints() -> None:
    run_round, calls = _round_seq([
        _rr(3, ["t::a", "t::b"]), _rr(5, ["t::a"]), _rr(6, ["t::a"]),
    ])
    out = RepairLoop(run_round).run()
    assert calls["n"] == 3 and out.rounds_run == 3
    assert out.stop_reason == STOP_MAX_ROUNDS
    assert [c.round_index for c in out.checkpoints] == [1, 2, 3]
    assert out.best_round == 3 and out.final_adapter == "v6"
    # 第二轮起收到的是 FailurePacket 而非原始日志
    assert calls["packets_seen"][1] and calls["packets_seen"][1][0].suggestion


def test_repair_rollback_on_worse_round() -> None:
    run_round, _ = _round_seq([
        _rr(5, ["t::a"]), _rr(2, ["t::a", "t::b", "t::c"]), _rr(5, ["t::a"]),
    ])
    out = RepairLoop(run_round).run()
    assert 2 in out.rolled_back_rounds
    assert out.best_round == 1 and out.final_adapter == "v5"  # 恢复最佳


def test_repair_stagnation_stops_early() -> None:
    run_round, calls = _round_seq([
        _rr(5, ["t::a"]), _rr(5, ["t::a"]), _rr(5, ["t::a"]), _rr(9, []),
    ])
    out = RepairLoop(run_round, budget=RepairBudget(max_rounds=10)).run()
    assert out.stop_reason == STOP_STAGNATION
    assert calls["n"] == 3  # 连续两轮无改善在第 3 轮确认后停;第 4 轮不执行


def test_repair_all_pass_is_not_a_verdict() -> None:
    run_round, _ = _round_seq([_rr(9, [])])
    out = RepairLoop(run_round).run()
    assert out.stop_reason == STOP_ALL_PUBLIC_PASS
    d = out.to_dict()
    assert "verdict" not in d
    assert "PASS" not in str(d["stop_reason"]).upper()  # 停机原因不携带成功语义
    assert "独立验证" in out.note  # 必须继续走隐藏验证链


def test_repair_scope_change_pauses_for_user() -> None:
    run_round, calls = _round_seq([
        _rr(4, ["t::a"], scope_change_request="需要新增大型依赖 numpy"),
        _rr(9, []),
    ])
    out = RepairLoop(run_round, budget=RepairBudget(max_rounds=5)).run()
    assert out.stop_reason == STOP_SCOPE_CHANGE
    assert out.pending_scope_change and "numpy" in out.pending_scope_change
    assert calls["n"] == 1  # 暂停,不自行继续


def test_repair_budget_diff_lines() -> None:
    run_round, _ = _round_seq([
        _rr(4, ["t::a"], diff_lines=500), _rr(9, []),
    ])
    out = RepairLoop(run_round, budget=RepairBudget(max_rounds=5, max_diff_lines=400)).run()
    assert out.stop_reason == "budget_exhausted"


def test_failure_packets_typed_and_no_raw_logs() -> None:
    packets = build_failure_packets(
        ["cap::test_upstream_wrapped", "cap::test_schema_fields",
         "reg::test_regression_loader", "cap::test_import_dep"],
        {"cap::test_upstream_wrapped": "TypeError: unexpected keyword argument",
         "cap::test_schema_fields": "KeyError: missing field doc_id",
         "cap::test_import_dep": "ModuleNotFoundError: No module named 'x'"},
    )
    types = [p.type for p in packets]
    assert types[0] == API_MISMATCH and types[1] == SCHEMA_ERROR
    assert types[2] == REGRESSION_FAILURE and types[3] == DEPENDENCY_ERROR
    for p in packets:
        assert p.suggestion and p.expected and p.summary
        blob = str(p.to_dict())
        assert "pytest" not in blob and "line " not in blob  # 不透传原始日志
    assert packets[2].owner == "HOST"


# ---- 独立检验(F12 等)补充 ----


def test_admission_priority_need_info_beats_risk(tmp_path: Path) -> None:
    host, _ = _good_pair(tmp_path)
    repo_dir = tmp_path / "repo"
    _write(repo_dir, "requirements.txt", "redis\n")  # 风险(外部服务)
    (repo_dir / "LICENSE").unlink()  # question(许可证未知)
    r = decide(host, analyze_repository_dir(repo_dir))
    assert r.status == NEED_INFORMATION  # 信息缺口优先于风险确认


def test_risk_review_flow_with_accepted_risks(tmp_path: Path) -> None:
    """F1: RISK_REVIEW 不是死胡同——接受全部风险后可出计划并确认。"""
    host, repo = _good_pair(tmp_path)
    _write(tmp_path / "repo", "requirements.txt", "redis\n")
    repo2 = analyze_repository_dir(tmp_path / "repo")
    adm = decide(host, repo2)
    assert adm.status == RISK_REVIEW
    intent = parse_intent("接入元数据解析,输出为 dict")
    with pytest.raises(ValueError, match="未接受的风险"):
        build_plan(intent, host, repo2, adm)
    plan = build_plan(intent, host, repo2, adm, accepted_risks=list(adm.risks))
    answers = {q: "已确认" for q in plan.questions}
    frozen = confirm_plan(plan, adm, answers=answers, user_ack=ACK_TEXT,
                          confirmed_at="t", accepted_risks=list(adm.risks))
    assert frozen.accepted_risks == list(adm.risks)
    with pytest.raises(HumanGateError, match="未被接受"):
        confirm_plan(plan, adm, answers=answers, user_ack=ACK_TEXT,
                     confirmed_at="t", accepted_risks=[])


def test_human_gate_detects_admission_tamper(tmp_path: Path) -> None:
    plan, adm, answers = _ready_plan(tmp_path)
    frozen = confirm_plan(plan, adm, answers=answers, user_ack=ACK_TEXT, confirmed_at="t")
    adm.risks.append("偷偷加的风险")
    with pytest.raises(HumanGateError, match="被修改"):
        require_confirmed(frozen, plan, adm)


def test_frozen_intent_is_immutable(tmp_path: Path) -> None:
    plan, adm, answers = _ready_plan(tmp_path)
    frozen = confirm_plan(plan, adm, answers=answers, user_ack=ACK_TEXT, confirmed_at="t")
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        frozen.plan_sha256 = "TAMPERED"  # F7: 冻结对象不可变


def test_repair_wipeout_round_not_mistaken_for_all_green() -> None:
    """F2: 收集崩溃轮(passed=0, failed=[])不得被当成全绿。"""
    run_round, _ = _round_seq([
        _rr(5, ["t::a"]), _rr(0, []), _rr(6, ["t::a"]),
    ])
    out = RepairLoop(run_round).run()
    assert out.stop_reason != STOP_ALL_PUBLIC_PASS
    assert out.best_round == 3 and 2 in out.rolled_back_rounds


def test_repair_restore_passes_best_snapshot_and_packets_from_best() -> None:
    """F3: 回滚后,下一轮收到最佳快照,失败包来自最佳状态。"""
    run_round, calls = _round_seq([
        _rr(5, ["t::best_fail"]), _rr(2, ["t::bad1", "t::bad2"]), _rr(6, ["t::x"]),
    ])
    RepairLoop(run_round).run()
    assert calls["best_seen"][0] is None and calls["best_seen"][1] == "v5"
    assert calls["best_seen"][2] == "v5"  # 劣化轮后仍从最佳继续
    round3_packets = calls["packets_seen"][2]
    assert [p.summary for p in round3_packets] == ["检查项「best fail」未通过"]


def test_repair_token_and_command_budgets() -> None:
    run_round, _ = _round_seq([
        _rr(4, ["t::a"], tokens_used=500_000), _rr(9, []),
    ])
    out = RepairLoop(run_round, budget=RepairBudget(max_rounds=5)).run()
    assert out.stop_reason == "budget_exhausted"
    run_round2, _ = _round_seq([
        _rr(4, ["t::a"], commands_used=999), _rr(9, []),
    ])
    out2 = RepairLoop(run_round2, budget=RepairBudget(max_rounds=5)).run()
    assert out2.stop_reason == "budget_exhausted"


def test_failure_packet_sanitizes_raw_pytest_logs() -> None:
    """F4: 即使调用方塞进原始 pytest 日志,也会被强制清洗。"""
    packets = build_failure_packets(
        ["cap::test_x"],
        {"cap::test_x": 'FAILED tests/x.py::test_x\n  File "/x.py", line 23\n'
                        "assert got == want\npytest summary"},
    )
    blob = str(packets[0].to_dict())
    assert "pytest" not in blob and 'File "' not in blob and "line 2" not in blob
    assert "assert got == want" in packets[0].actual


def test_suggest_answers_deterministic_with_basis() -> None:
    """必答问题推荐答案(用户实测:新手不知怎么答)。零 LLM:推荐只来自
    目标文本/宿主分析/用户样例,且每条必须附依据;无可靠依据的不编造。"""
    from repoproof.adoption.planning.answer_suggestions import suggest_answers

    qs = [
        "你想采用的是哪类能力(解析/检索/转换/其他)?",
        "是否允许为你的项目新增第三方依赖?",
        "预期输出的字段/格式是什么(能给一个例子最好)?",
        "有没有必须保持不变的现有行为?",
    ]
    blank_host = {"host_mode": {"value": "BLANK_PROJECT"}}
    out = suggest_answers(
        qs, goal="为我的项目引入文档元数据解析能力",
        host_report=blank_host, examples_text="a => 1\nb => 2\nc => 3")
    assert out[qs[0]][0] == "文档元数据解析"  # 由目标文本确定性识别
    assert out[qs[1]][0] == "允许" and "空目录" in out[qs[1]][1] or "空白项目" in out[qs[1]][1]
    assert "a => 1" in out[qs[2]][0] and "样例" in out[qs[2]][1]
    assert out[qs[3]][0] == "无"

    # 已有项目 + 探测到测试命令:保持不变 → 现有测试全过
    git_host = {"host_mode": {"value": "GIT_PROJECT"},
                "test_command": {"value": "pytest -q"}}
    out2 = suggest_answers(qs, goal="接入检索排序", host_report=git_host)
    assert "pytest -q" in out2[qs[3]][0]
    assert "样例" in out2[qs[2]][0]  # 未填样例时给格式指导,不编造具体值

    # 完全没有依据的问题:不返回(绝不编造)
    out3 = suggest_answers(["这个能力上线后由谁负责运维?"], goal="x")
    assert out3 == {}


def test_suggestions_generalize_and_guidance_always_exists() -> None:
    """泛化(用户实测):换任务/换情况推荐仍要成立——目标未命中已知类别
    时引用目标原文并如实标注;任意未知问题必有作答格式指导兜底。"""
    from repoproof.adoption.planning.answer_suggestions import (
        answer_guidance,
        suggest_answers,
    )

    q_cap = "你想采用的是哪类能力(解析/检索/转换/其他)?"
    # 任意新能力(不在关键词表):推荐=引用目标原文,依据如实说明可改写
    out = suggest_answers([q_cap], goal="为我的项目引入英文名词复数化能力")
    sug, basis = out[q_cap]
    assert "复数化" in sug and "未匹配到已知类别" in basis

    # 仓库自述可作为第二来源
    out2 = suggest_answers([q_cap], goal="",
                           repo_report={"description": {"value": "BM25 检索排序库"}})
    assert out2[q_cap][0] == "检索排序" and "仓库" in out2[q_cap][1]

    # 任意未知问题:无推荐,但指导永远存在且非空
    weird = "这个能力上线后由谁负责运维?"
    assert suggest_answers([weird], goal="x") == {}
    assert "一句话" in answer_guidance(weird)
    for q in (q_cap, "是否允许为你的项目新增第三方依赖?",
              "预期输出的字段/格式是什么(能给一个例子最好)?",
              "有没有必须保持不变的现有行为?"):
        assert answer_guidance(q)  # 四类标准问题都有专属格式指导


def test_capability_suggestion_never_cuts_mid_sentence() -> None:
    """用户实测:推荐答案显示"输出把每(依据…"——[:40] 硬截断切在句中。
    现在引用目标第一小句(到首个分隔符),永不半句。"""
    from repoproof.adoption.planning.answer_suggestions import suggest_answers

    q = "你想采用的是哪类能力(解析/检索/转换/其他)?"
    goal = "为我的笔记项目引入 emoji 转文字能力:输入含 emoji 的文本,输出把每个 emoji 替换为 :名称: 形式的纯文本"
    sug, basis = suggest_answers([q], goal=goal)[q]
    assert sug == "为我的笔记项目引入 emoji 转文字能力"  # 完整第一句
    assert "第一句" in basis
