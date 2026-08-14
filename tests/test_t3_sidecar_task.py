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


# ============================================================ 2026-08-15 加固
# 可搬运性审查(LESSONS #43 纪律,跑真实模型之前的强制前置)查出四条 blocking,
# 其中三条同源、由 `_make_per_unit_adoption` 一次重写补上。这里**直接喂谓词**,
# 不只靠矩阵的落盘证据 —— M50a 的教训:两条路互为冗余时,把其中一条掏掉没人
# 看得见。

def _pred(units):
    import importlib.util
    import sys

    f = REPO / "scripts" / "verify_task_receipts.py"
    spec = importlib.util.spec_from_file_location("t3s_vtr", f)
    m = importlib.util.module_from_spec(spec)
    sys.modules["t3s_vtr"] = m
    spec.loader.exec_module(m)
    return m._make_per_unit_adoption(units), m


class _R:
    """最小回执替身 —— 谓词只读这三样。"""

    def __init__(self, nonce, in_dig, out_dig):
        self.binding = type("B", (), {"request_nonce": nonce})()
        self.input = type("P", (), {"digest": in_dig})()
        self.output = type("P", (), {"digest": out_dig})()


def _units():
    _, m = _pred([])
    return [{"request_nonce": "a", "input_digest": m.digest_of(
                 {"text": "http://h/?item=a"}, canon=m.CANON_JSON)},
            {"request_nonce": "b", "input_digest": m.digest_of(
                 {"text": "http://h/?item=b"}, canon=m.CANON_JSON)}]


def _out(m, s):
    return m.digest_of(s, canon=m.CANON_TEXT_SQUASH)


def test_s7_honest_shapes_still_pass():
    """误杀侧:三种诚实形态都必须过。

    含 **oracle 三次提交**(h1/h2/h3 各交一次作业 → 每 nonce ≥3 张回执)——
    审查里明确否掉了"每 nonce 只许一张"的改法,就是因为它会误杀这个形态。"""
    u = _units()
    pred, m = _pred(u)
    recs = [_R("a", u[0]["input_digest"], _out(m, "FACT-A")),
            _R("b", u[1]["input_digest"], _out(m, "FACT-B"))]
    d = [{"request_nonce": "a", "facts": "FACT-A"},
         {"request_nonce": "b", "facts": "FACT-B"}]
    assert pred(recs, d)[0], pred(recs, d)[1]
    assert pred(recs * 3, d)[0], "每 nonce 三张回执被误杀了(oracle 三次提交)"
    tidy = [{"request_nonce": "a", "facts": " FACT-A \n"},
            {"request_nonce": "b", "facts": "FACT-B\n"}]
    assert pred(recs, tidy)[0], "无害的空白整理被误杀了"


def test_s8_laundering_via_forged_input_is_caught():
    """B1:同 nonce 换自造输入再调一次 —— sidecar 不得沦为任意内容的签名机。

    修前实测:U1–U4 十项全绿。"""
    u = _units()
    pred, m = _pred(u)
    recs = [_R("a", u[0]["input_digest"], _out(m, "FACT-A")),
            _R("b", u[1]["input_digest"], _out(m, "FACT-B")),
            _R("a", _out(m, "data:forged"), _out(m, "MINE-A")),
            _R("b", _out(m, "data:forged"), _out(m, "MINE-B"))]
    ok, why = pred(recs, [{"request_nonce": "a", "facts": "MINE-A"},
                          {"request_nonce": "b", "facts": "MINE-B"}])
    assert not ok, "洗白过了 —— U4 又不核 input_digest 了"
    assert "输入对得上" in why or "不是它那张回执" in why


def test_s9_partial_delivery_is_caught():
    """B2:分母必须来自 harness 的清单,不是 len(delivery)。"""
    u = _units()
    pred, m = _pred(u)
    recs = [_R("a", u[0]["input_digest"], _out(m, "FACT-A")),
            _R("b", u[1]["input_digest"], _out(m, "FACT-B"))]
    ok, why = pred(recs, [{"request_nonce": "a", "facts": "FACT-A"}])
    assert not ok, "少交过了 —— 分母又回到被测方那边了"
    assert "漏了" in why


def test_s10_blank_and_malformed_are_caught_and_attributed():
    """B3:空产出不是采纳凭证;`facts` 非字符串**判红不抛**。

    抛出去会被记成 RECEIPT_VERIFIER_ERROR —— 把被测方交的畸形工件写成
    harness 自己坏了,归因完全反了。"""
    u = _units()
    pred, m = _pred(u)
    blank = [_R("a", u[0]["input_digest"], _out(m, "")),
             _R("b", u[1]["input_digest"], _out(m, ""))]
    ok, why = pred(blank, [{"request_nonce": "a", "facts": "  \n"},
                           {"request_nonce": "b", "facts": ""}])
    assert not ok and "为空" in why

    good = [_R("a", u[0]["input_digest"], _out(m, "FACT-A")),
            _R("b", u[1]["input_digest"], _out(m, "FACT-B"))]
    ok2, why2 = pred(good, [{"request_nonce": "a", "facts": {"raw": "x"}},
                            {"request_nonce": "b", "facts": "FACT-B"}])
    assert not ok2 and "形状不合规" in why2


def test_s11_missing_denominator_refuses():
    """清单为空一律判不过 —— 与 U3 缺分母同一条纪律。

    默认放行会让将来某次漏传参数**静默退回**今天这个形状。"""
    pred, _ = _pred([])
    ok, why = pred([], [{"request_nonce": "a", "facts": "x"}])
    assert not ok and "待办清单" in why


def test_s12_agent_env_does_not_leak_the_oracle_items():
    """B4:agent 拿不到 fixture 基址与那批 nonce,oracle 才拿得到。

    拿得到就能预取 oracle 将来下发的全部项、把事实写死进源码,交付代码
    一次 RPC 不发而四道谓词全绿 —— **回执证明的是"会话里有人调过",不是
    "交付代码调了"**。

    查**行为**不查文本:`agent_env` 的文档里正要解释为什么砍掉这两项,
    按字符串查会把解释本身判成泄漏,逼人把解释删掉 —— 那比判据本身更坏。
    """
    import sys

    sys.path.insert(0, str(REPO / "src"))
    from repoproof.runner.sidecar_session import SidecarSession

    class _H:
        def agent_env(self):
            return {"REPOPROOF_SIDECAR_URL": "http://s/", "REPOPROOF_SIDECAR_TOKEN": "tok"}

    class _P:
        default_symbol = "S"

    s = SidecarSession(profile=_P(), ledger=Path("/x"), key=b"", run_nonce="n",  # type: ignore[arg-type]
                       run_id="r", handle=_H(), fixture_url="http://f/",         # type: ignore[arg-type]
                       items=[{"request_nonce": "a", "url": "http://f/?item=a"},
                              {"request_nonce": "b", "url": "http://f/?item=b"}])

    a, o = s.agent_env(), s.oracle_env()
    assert "REPOPROOF_FIXTURE_URL" not in a, "agent 又能看到 fixture 基址了"
    assert "REPOPROOF_ITEM_NONCES" not in a, "agent 又能看到那批 nonce 了"
    assert set(a) == {"REPOPROOF_SIDECAR_URL", "REPOPROOF_SIDECAR_TOKEN",
                      "REPOPROOF_SIDECAR_SYMBOL"}, sorted(a)
    assert "REPOPROOF_FIXTURE_URL" in o and "REPOPROOF_ITEM_NONCES" in o
    assert set(a) < set(o), "oracle 该是 agent 的超集"

    # 砍环境变量只挡住"直接读";还得挡住"猜" —— 项必须能现摇
    before = [i["request_nonce"] for i in s.items]
    s.rotate_items()
    after = [i["request_nonce"] for i in s.items]
    assert len(after) == len(before) and set(after).isdisjoint(before), (
        "rotate_items 没换掉项 —— 预取的字典照样对得上")
    assert all(i["url"].startswith("http://f/?item=") for i in s.items)


def test_s13_stale_artifacts_are_cleaned_before_the_oracle():
    """B5(误杀侧):早轮残留工件必须在 oracle 之前清掉。

    取件器把交付目录下**全部** json 一网打尽,而每轮 `git add -A` 让它们变成
    tracked 文件长久留下。修复循环的全部意义就是允许 round-1 是错的:
    round-1 落坏事实、round-3 改对再落好的,终局取件把两批一起交上去 → U4 红,
    措辞与"调了但没用"一字不差,而最终交付物其实是完美的。"""
    hg = (REPO / "src" / "repoproof" / "runner"
          / "host_guided.py").read_text(encoding="utf-8")
    clean_at = hg.index('s.backend.exec(s.id, ["rm", "-rf", _d]')
    oracle_at = hg.index("cap_run = self._run_oracle(s, oracle_snap)")
    assert clean_at < oracle_at, "清场排到 oracle 之后了 —— 等于没清"
    rotate_at = hg.index("sidecar_sess.rotate_items()")
    assert rotate_at < oracle_at, "换项排到 oracle 之后了 —— oracle 拿到的还是旧项"
    assert "_delivery_dirs" in hg, "清场目录必须由任务包声明,不能扫目录"


def test_s14_contract_states_the_artifact_layout_and_flag():
    """B6/B7:交付落点、开关名、接口形状必须写进契约。

    原先这三样只存在于 harness 侧的取件器与 oracle 里,契约一个字没提,
    而它们决定生死。**用未言明的要求判人,红了也无从预防** —— 那是判据的
    缺陷,不是被测方的。"""
    ids = {r["id"] for r in _contract()["capability"]["requirements"]}
    assert {"R8-artifact-layout", "R9-feature-flag", "R10-api-shape"} <= ids, sorted(ids)
    txt = json.dumps(_contract()["capability"]["requirements"], ensure_ascii=False)
    assert "page_facts_jobs" in txt and "OFFERCLAW_PAGE_FACTS" in txt


def test_s15_public_surface_is_not_empty():
    """B8:公开面不能是空的 —— 否则 agent 三轮零反馈,而失败记录与
    '模型公开面全挂'逐字段同型,台账里分不开。"""
    files = list((TASK / "public_tests").glob("test_*.py"))
    assert files, "public_tests/ 是空的"
    src = "\n".join(f.read_text(encoding="utf-8") for f in files)
    assert src.count("def test_") >= 5, "公开面太薄,给不出有用的反馈"
