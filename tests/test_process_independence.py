"""评审独立性四件套的钉死(PROCESS-INDEPENDENCE-PLAN §5 P0/P1)。

护的对象不是功能,是**流程的不可绕性**:闸门数字只能出自脚本、错数字
必红、红绿证据必须在场、变异登记簿不得过期。检查器自己也要被检查——
这里就是那层检查。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load(script: str):
    spec = importlib.util.spec_from_file_location(script[:-3], REPO / "scripts" / script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- gate_report

def test_gate_report_computes_from_ledger_only(tmp_path: Path) -> None:
    """闸门数字 = count_passes(runs ⋈ adjudications),三道扣除全部生效。"""
    from repoproof.persistence.bench_records import EXPLORATORY_BATCH, append_run

    gr = _load("gate_report.py")
    append_run(tmp_path, {"run_id": "a", "task_id": "t1-x", "model": "gpt-5.6",
                          "verdict": "PASS_ADAPTED"})
    append_run(tmp_path, {"run_id": "b", "task_id": "t1-x", "model": "fake-scripted",
                          "verdict": "PASS_ADAPTED"})                    # 冒烟
    append_run(tmp_path, {"run_id": "c", "task_id": "t1-x", "model": "gpt-5.5",
                          "verdict": "PASS_ADAPTED", "batch": EXPLORATORY_BATCH})
    data = gr.compute(tmp_path)
    t1 = data["stages"]["T1"]
    assert (t1["total"], t1["passes"], t1["smoke"], t1["exploratory"]) == (3, 1, 1, 1)
    assert data["gate_met"]["T1"] is True and data["gate_met"]["T4"] is False
    assert gr.render(data) == gr.render(gr.compute(tmp_path)), "输出必须确定性"


def test_gate_report_check_detects_tamper_and_staleness(tmp_path: Path, monkeypatch) -> None:
    from repoproof.persistence.bench_records import append_run

    gr = _load("gate_report.py")
    gate_json = tmp_path / "v2_gate.json"
    monkeypatch.setattr(gr, "GATE_JSON", gate_json)

    assert gr.check(tmp_path), "json 缺失必须报错"
    gate_json.write_text(gr.render(gr.compute(tmp_path)), encoding="utf-8")
    assert gr.check(tmp_path) == [], "新鲜一致 → 通过"
    # 手改 json(篡改)或台账新增(过期)都必须红
    gate_json.write_text(gate_json.read_text(encoding="utf-8").replace(
        '"passes": 0', '"passes": 9', 1), encoding="utf-8")
    assert gr.check(tmp_path), "手改数字必须被查出"
    gate_json.write_text(gr.render(gr.compute(tmp_path)), encoding="utf-8")
    append_run(tmp_path, {"run_id": "new", "task_id": "t1-x", "model": "gpt-5.6",
                          "verdict": "FAIL"})
    assert gr.check(tmp_path), "台账动了、json 没再生成 → 过期必须被查出"


def test_committed_v2_gate_json_is_fresh() -> None:
    """棘轮:runs.jsonl 变动后必须重跑 gate_report --write 并一起提交。

    本测试红 = 有人往台账里加了发次但没再生成事实文件。修法一行:
    `.venv/bin/python scripts/gate_report.py --write`,复核 diff 后提交。
    """
    gr = _load("gate_report.py")
    assert gr.check(REPO) == []


# ---------------------------------------------------------------- 公开声明

def test_wrong_gate_numbers_in_prose_go_red() -> None:
    """验收判据(PLAN §5-P0-2 原文):把 LESSONS #30 修复前的错数字写进
    当前态文档,检查必须变红。"""
    cpc = _load("check_public_claims.py")
    passes = {"T1": 2, "T2": 2, "T3": 1, "T4": 0}
    # 修复前的错声明(T1 实为 2):两种常见写法都必须命中
    assert cpc.find_v2_gate_violations("闸门:T1 3 / T2 2 / T3 1", passes, "X.md")
    assert cpc.find_v2_gate_violations("追溯审计:T1 3 个 PASS", passes, "X.md")
    # 正确声明与干扰句不得误伤
    assert not cpc.find_v2_gate_violations("T1 2 / T2 2 / T3 1(诚实数)", passes, "X.md")
    assert not cpc.find_v2_gate_violations(
        "T3 v5 oracle 8/8 PASS;T1 11 runs / 2 gate PASS", passes, "X.md")
    assert not cpc.find_v2_gate_violations("T4 0 个 PASS(阶段未开)", passes, "X.md")


def test_public_claims_checker_passes_on_current_repo() -> None:
    cpc = _load("check_public_claims.py")
    assert cpc.check() == []


# ---------------------------------------------------------------- 变异登记簿

def test_mutation_registry_not_stale() -> None:
    """每条变异的旧串必须在目标源文件中**恰好出现一次**——重构后登记簿
    过期时,这里先红,而不是等到跑闸门才发现 STALE。"""
    mg = _load("mutation_gate.py")
    problems: list[str] = []
    for m in [mg.CANARY, *mg.MUTATIONS]:
        text = (REPO / m["file"]).read_text(encoding="utf-8")
        n = text.count(m["old"])
        if n != 1:
            problems.append(f"{m['id']}: 旧串出现 {n} 次(要求 1)")
        for c in m["catchers"]:
            if not (REPO / c).exists():
                problems.append(f"{m['id']}: catcher 不存在 {c}")
    assert not problems, problems


def test_mutation_registry_shape() -> None:
    mg = _load("mutation_gate.py")
    ids = [m["id"] for m in mg.MUTATIONS]
    assert len(ids) == len(set(ids)), "变异 id 不得重复"
    assert len(mg.MUTATIONS) >= 55, "登记簿只增不减:历史缺陷的变异体不得静默移除"
    for m in mg.MUTATIONS:
        assert m["lesson"].strip(), f"{m['id']} 必须注明对应教训"
        assert m["old"] != m["new"], f"{m['id']} 旧串新串相同 = 没变异"


# ---------------------------------------------------------------- 红绿留痕

def test_redgreen_evidence_for_attribution_fix_is_valid() -> None:
    """6c305dc(归因修复)的 6 个钉死必须有红绿双证据:base 上全红、
    fix 上全绿。只有绿的钉死不算数(PLAN §5-P0-3)。"""
    matches = list((REPO / "docs" / "evidence" / "redgreen").glob("6c305dc*.txt"))
    assert matches, "红绿证据缺失 —— 跑 scripts/redgreen.py --fix 6c305dc <nodes>"
    text = matches[0].read_text(encoding="utf-8")
    assert "VERDICT: VALID" in text
    assert text.count(": failed") >= 6, "RED 段必须逐节点 failed"
    assert text.count(": passed") >= 6, "GREEN 段必须逐节点 passed"


# exit 4 两义性(LESSONS #34 首咬):红绿工具首次遇到"新文件 import 新符号"
# 型修复就判假阴性 —— base 上 ImportError(最强的红)与节点名打错同为 exit 4。
# 判定抽成纯函数 judge(),四条边界直接钉死;放宽必须是"两条机器条件"而
# 不是"exit 4 一律算红"(后者等于把守卫拆了)。
_IMPORT_ERR = [("tests.test_x", "ImportError: cannot import name 'ROLLBACK'")]


def _judge(**kw):
    rg = _load("redgreen.py")
    base = dict(names=["test_a"], red_exit=4, red_results={},
                green_results={"test_a": "passed"}, red_collect=_IMPORT_ERR,
                files=["tests/test_x.py"])
    base.update(kw)
    return rg.judge(**base)


def test_import_error_collection_counts_as_red() -> None:
    """特性不存在→模块 import 不进去,是最强的红,不得判 INVALID。"""
    assert _judge() == []


def test_typo_node_name_still_cannot_fake_red() -> None:
    """守卫本意保住:名字打错时绿段查无此名 → 仍判不是红。"""
    problems = _judge(green_results={})
    assert any("没有绿" in p for p in problems)
    assert any("exit=4" in p for p in problems)


def test_unrelated_collection_crash_is_not_red() -> None:
    """收集错误不是符号缺失类(如 conftest 语法错)→ 不算红,环境坏了
    不等于缺陷被抓住。"""
    problems = _judge(red_collect=[("tests.test_x", "SyntaxError: invalid syntax")])
    assert any("exit=4" in p for p in problems)


def test_collection_error_must_belong_to_the_tested_file() -> None:
    """别的文件收集炸了不能替本文件作证。"""
    problems = _judge(red_collect=[("tests.test_other", "ImportError: boom")])
    assert any("exit=4" in p for p in problems)


def test_base_pass_is_never_red() -> None:
    """base 上 passed = 钉死抓不住任何东西(与 exit 4 无关)。"""
    problems = _judge(red_exit=0, red_results={"test_a": "passed"}, red_collect=[])
    assert any("没有红" in p for p in problems)


def test_verify_integrity_entrypoint_exists() -> None:
    sh = REPO / "scripts" / "verify_integrity.sh"
    assert sh.exists()
    text = sh.read_text(encoding="utf-8")
    for must in ("gate_report.py --check", "check_public_claims.py", "mutation_gate.py"):
        assert must in text, f"一键入口缺环节:{must}"


def test_evidence_json_records_capture_rate() -> None:
    """变异闸门跑过至少一次,且最近一次捕获率 100%(ESCAPED/STALE 清零)。"""
    ev_dir = REPO / "docs" / "evidence" / "mutation_gate"
    files = sorted(ev_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    assert files, "变异闸门从未跑过 —— .venv/bin/python scripts/mutation_gate.py"
    latest = json.loads(files[-1].read_text(encoding="utf-8"))
    assert latest["escaped"] == [] and latest["stale"] == [], (
        f"最近一次变异闸门未达 100%:{latest['escaped']} {latest['stale']}")
    assert latest["caught"] == latest["mutations"]


# --------------------------------------------------- 批次判据核对器(自身负控)

def _fake_batch(tmp_path, *, denied: int, policy_violations: int, batch="B"):
    """造一份最小批次证据(台账 + trace + record),用于位置无关地验判定逻辑。"""
    import json
    (tmp_path / "benchmarks" / "v2").mkdir(parents=True)
    (tmp_path / "benchmarks" / "v2" / "runs.jsonl").write_text(json.dumps(
        {"run_id": "r-1", "run_order": "1", "task_id": "t", "model": "m",
         "verdict": "FAIL", "batch": batch, "rollback_count": 0}) + "\n", encoding="utf-8")
    rd = tmp_path / "runs" / "r-1"
    (rd / "repair" / "round-1").mkdir(parents=True)
    (rd / "trace.jsonl").write_text(json.dumps(
        {"event": "repair.round.end",
         "payload": {"round": 1, "public_passed": 21, "fatal_violations": [],
                     "denied_this_round": denied}}) + "\n", encoding="utf-8")
    (rd / "repair" / "round-1" / "record.json").write_text(json.dumps(
        {"public_passed": 21, "public_failed": 2, "regression_failed": 0,
         "policy_violations": policy_violations, "changed_files": ["adapter.py"],
         "diff_lines": 10, "failure_packets": [
             {"type": "POLICY_VIOLATION",
              "summary": f"{denied} command(s) were DENIED by the policy guard"}]}),
        encoding="utf-8")
    (rd / "report.json").write_text(json.dumps(
        {"repair": {"best_round": 1, "rolled_back_rounds": []}}), encoding="utf-8")
    return batch


def test_batch_criteria_detects_the_prefix_defects(tmp_path, monkeypatch) -> None:
    """检查器必须能**查出缺陷**,不只是盖章:同一份证据,只把
    policy_violations 从 0 改成 1(=修复前语义),Q1 必须由通过翻成未通过。

    **位置无关**(LESSONS #32):证据由本测注入,不读真仓库的 runs/——
    否则在 worktree/CI/别人的 clone 里必然假红(变异闸门基线守卫实测抓到)。"""
    bc = _load("batch_criteria.py")
    monkeypatch.setattr(bc, "REPO", tmp_path)
    monkeypatch.setattr(bc, "LEDGER", tmp_path / "benchmarks" / "v2" / "runs.jsonl")

    _fake_batch(tmp_path, denied=1, policy_violations=1)      # 修复前
    bad = bc.adjudicate("B")
    assert bad["criteria"]["Q1 denied 不计入排序"]["verdict"] == bc.FAIL
    assert bad["overall"] == bc.FAIL

    import shutil
    shutil.rmtree(tmp_path / "runs")
    shutil.rmtree(tmp_path / "benchmarks")
    _fake_batch(tmp_path, denied=1, policy_violations=0)      # 修复后
    good = bc.adjudicate("B")
    assert good["criteria"]["Q1 denied 不计入排序"]["verdict"] == bc.PASS
    assert good["criteria"]["P2 违规包携带真值"]["verdict"] == bc.PASS
    assert good["overall"] == bc.PASS


def test_batch_criteria_marks_untriggered_as_vacuous(tmp_path, monkeypatch) -> None:
    """未触发的判据必须记「未被检验」,既不算通过也不算失败——
    "不许拿没发生的事当成功"(批 6 P1 先例)。零 denied 的批次里
    Q1 必须是 vacuous 而非 PASS。"""
    bc = _load("batch_criteria.py")
    monkeypatch.setattr(bc, "REPO", tmp_path)
    monkeypatch.setattr(bc, "LEDGER", tmp_path / "benchmarks" / "v2" / "runs.jsonl")
    _fake_batch(tmp_path, denied=0, policy_violations=0)
    out = bc.adjudicate("B")
    assert out["criteria"]["Q1 denied 不计入排序"]["verdict"] == bc.VACUOUS
    assert out["criteria"]["Q4 tampered 仍计入排序"]["verdict"] == bc.VACUOUS
    assert out["overall"] == bc.PASS, "vacuous 不使整体失败,但也不算通过"


def test_batch_criteria_unknown_batch_is_empty_not_green() -> None:
    """不存在的批次不得静默返回全绿(否则打错批次名=自动通过)。"""
    bc = _load("batch_criteria.py")
    out = bc.adjudicate("NO-SUCH-BATCH")
    assert out["runs"] == 0
    assert all(c["verdict"] == bc.VACUOUS for c in out["criteria"].values())
