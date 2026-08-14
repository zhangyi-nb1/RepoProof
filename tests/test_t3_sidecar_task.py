"""T3-SIDECAR v1 任务包的钉死 —— F0:先证明这道题的判据不是墙也不是筛子。

矩阵在 `scripts/t3_sidecar_conformance.py`(零模型,真 sidecar + 真浏览器)。

- S1 **正控必须过**。反例:判据成墙 —— 模型再好也过不了,而红的原因与"模型
  不行"长得一模一样。
- S2 **每个负控红在它自己那一处**。
- S3 **nc2(调了但不用结果)只红在 U4** —— 这道题的考题。
- S4 **nc3(一次调用充抵所有项)必须红在 U3 **和** U4**。实测踩过:通用的
  集合成员式采纳判据只让它红在 U3,U4 反而绿。逐项对应的谓词才挡得住。
- S5 **谱系与既有 T3 分开**:task_family / adoption_shape / task_id 都不同,
  但上游同源同 commit(换的是拓扑不是上游,这样两支才可对照)。
- S6 **采纳判定不在 oracle 里**:密钥与台账在 harness 手上,塞进会话就作废。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
TASK = REPO / "benchmarks" / "v2" / "tasks" / "t3_sidecar_v1"
MATRIX = REPO / "docs" / "evidence" / "t3_sidecar_conformance" / "matrix.json"


def _m() -> dict:
    if not MATRIX.is_file():
        pytest.skip("矩阵未落盘 —— 跑 scripts/t3_sidecar_conformance.py")
    return json.loads(MATRIX.read_text(encoding="utf-8"))


def _contract() -> dict:
    return yaml.safe_load((TASK / "contract.yaml").read_text(encoding="utf-8"))


def test_s1_positive_control_passes():
    pos = next(r for r in _m()["rows"] if r["control"] == "positive")
    assert pos["actual"] == "PASS", f"正控红了 —— 判据成墙:{pos['actual_red']}"


def test_s2_every_negative_reds_where_declared():
    m = _m()
    assert m["ok"] is True and m["problems"] == []
    for r in m["rows"]:
        if r["expect"] == "FAIL":
            assert sorted(r["actual_red"]) == sorted(r["expect_red"]), r["control"]


def test_s3_ignoring_the_result_reds_only_on_adoption():
    r = next(x for x in _m()["rows"] if x["control"] == "nc2_ignores_result")
    assert r["actual_red"] == ["U4.adoption"], r["actual_red"]


def test_s4_one_call_for_all_reds_on_both_coverage_and_adoption():
    """S4:实测踩过的那条。

    通用的 `digest_equality_predicate` 判的是"交付项的摘要**在**回执 output
    的集合里" —— 集合成员,不是逐项对应。于是只调一次拿到 A 的结果、当作
    A 和 B 一起交,两项都落在集合里,U4 照绿(当时只有 U3 报红)。
    逐项对应的谓词(按 request_nonce 配对)才挡得住。"""
    r = next(x for x in _m()["rows"] if x["control"] == "nc3_one_call_for_all")
    assert set(r["actual_red"]) == {"U3.coverage", "U4.adoption"}, (
        f"{r['actual_red']} —— 采纳谓词可能又退回集合成员式了")


def test_s4b_the_adoption_predicate_is_per_unit_not_set_membership():
    import ast

    f = REPO / "scripts" / "verify_task_receipts.py"
    src = f.read_text(encoding="utf-8")
    assert "_per_unit_adoption" in src and "binding.request_nonce" in src

    # 断言它**没被使用**,而不是"名字没出现" —— 文档里当然要提它,
    # 提到就报红的判据会逼人把解释删掉,那比判据本身更坏。
    tree = ast.parse(src)
    imported = {a.name for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) for a in n.names}
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "digest_equality_predicate" not in (imported | called), (
        "又用回通用的集合成员式谓词了 —— 那挡不住'一次调用充抵所有项'")


def test_s5_lineage_is_separate_from_t3_inproc():
    side = _contract()
    inproc = yaml.safe_load(
        (REPO / "benchmarks" / "v2" / "tasks" / "t3_browser_use_v6"
         / "contract.yaml").read_text(encoding="utf-8"))
    assert side["task_family"] == "T3-SIDECAR"
    assert inproc["task_family"] == "T3-INPROC"
    assert side["adoption_shape"] == "SIDECAR_RPC_ADOPTION"
    assert side["adoption_shape"] != inproc["adoption_shape"]
    assert side["task_id"] != inproc["task_id"]
    assert "v7" not in side["task_id"], "不叫 T3v7 —— 能力定义变了,不是同一题的下一版"
    # 上游同源同 commit:换的是拓扑不是上游
    assert side["source_repo"]["resolved_commit"] == \
           inproc["source_repo"]["resolved_commit"]
    assert side["runtime_profile"] == "rt-sidecar-browser-v1"


def test_s6_receipt_verification_is_harness_side_not_in_the_oracle():
    """S6:采纳判定必须在 harness 侧。

    反例:塞进 oracle —— oracle 跑在会话里,要验签名就得把密钥递进去,
    而递进去之后"agent 伪造不了回执"这条性质当场作废。"""
    c = _contract()
    assert c["acceptance"]["receipt_verification"] == "scripts/verify_task_receipts.py"
    oracle_dir = TASK / "oracle"
    for f in oracle_dir.glob("*.py"):
        src = f.read_text(encoding="utf-8")
        assert "REPOPROOF_RECEIPT_KEY" not in src and "verify_receipts" not in src, (
            f"{f.name} 里出现了回执验证 —— 那会把密钥带进会话")


def test_controls_are_all_present():
    want = {"positive", "nc1_no_sidecar", "nc2_ignores_result",
            "nc3_one_call_for_all", "nc4_wrong_symbol"}
    got = {p.name for p in (TASK / "controls").iterdir() if p.is_dir()}
    assert want <= got, sorted(want - got)
    for n in want:
        assert (TASK / "controls" / n / "page_facts.py").is_file()


def test_budgets_are_tighter_than_t3_inproc():
    """额度是难度的一部分,不是可以顺手复制的样板。

    这道题去掉了依赖解析与浏览器安装(T3-INPROC 里最吃轮次的部分),
    照抄它的额度会让本题宽松得测不出东西。"""
    side, inproc = _contract()["budgets"], yaml.safe_load(
        (REPO / "benchmarks" / "v2" / "tasks" / "t3_browser_use_v6"
         / "contract.yaml").read_text(encoding="utf-8"))["budgets"]
    assert side["semantics"] == inproc["semantics"] == "per_round"
    assert side["max_model_calls"] < inproc["max_model_calls"]
    assert side["max_commands"] < inproc["max_commands"]


@pytest.mark.slow
def test_matrix_is_fresh():
    """真重跑一遍(~20s)。**默认就跑。**"""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "t3_sidecar_conformance", REPO / "scripts" / "t3_sidecar_conformance.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    before = {r["control"]: r["actual_red"] for r in _m()["rows"]}
    assert mod.main() == 0
    fresh = json.loads(MATRIX.read_text(encoding="utf-8"))
    assert {r["control"]: r["actual_red"] for r in fresh["rows"]} == before
