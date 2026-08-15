"""sidecar 接进 `host-run` 的钉死。

这一段最容易出的错不是"功能不对",而是**报错报得像另一件事**。三处实测事故
全是这个形状:

- oracle 拿不到 sidecar 环境 → 三条隐藏用例全红,看起来像被测方不行;
- 取件时机晚于会话销毁 → 报 host=None,看起来像交付不存在;
- profile 定义 import 不到 → 报"未登记的 profile",看起来像配置写错了。

所以钉的重点是**归因不许混**。

- W1 **in-process 任务的会话环境一字不变**。反例:新增能力顺手改了所有任务
  的 env → 既有发次与历史不可比,而没人会注意到。
- W2 **agent 与 oracle 都拿不到台账路径与密钥**。反例:漏出去 → U1 的全部
  意义没了(谁都能伪造回执)。
- W3 **取件在会话销毁之前**。反例:放最外层 finally → clean replay 已经把
  会话清了,永远取不到。
- W4 **取件失败 ≠ 采纳不成立**,分开报。反例:混成一个 U4 红 → harness 的
  毛病记成被测方的失败。
- W5 **采纳不通过走 missing_external**,不对 verdict 做手术。反例:自己改
  verdict → gate 的结论与它自己的 reasons 对不上。
- W6 **profile 惰性加载是白名单**,不扫目录。反例:扫目录 → 放个文件进去就
  凭空多出一个"对外承诺的名字"。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HG = (REPO / "src" / "repoproof" / "runner" / "host_guided.py").read_text(encoding="utf-8")
SS = (REPO / "src" / "repoproof" / "runner"
      / "sidecar_session.py").read_text(encoding="utf-8")


def test_w1_inprocess_sessions_are_untouched():
    """W1:`extra_env` 缺省 None,in-process 任务的会话环境一字不变。"""
    assert "extra_env: dict[str, str] | None = None" in HG
    assert "**(extra_env or {})," in HG
    # 只有 sidecar 拓扑才起会话
    assert 'if _rt.topology == "sidecar":' in HG


def test_w2_neither_agent_nor_oracle_gets_the_key_or_ledger():
    """W2:交给 agent / oracle 的环境里没有台账路径与密钥。"""
    import sys

    sys.path.insert(0, str(REPO / "src"))
    from repoproof.execution.upstream_sidecar import SidecarHandle

    h = SidecarHandle(None, "http://127.0.0.1:1", "tok",       # type: ignore[arg-type]
                      Path("/x/ledger.jsonl"), "rt-x")
    blob = json.dumps(h.agent_env())
    for bad in ("ledger", "LEDGER", "key", "KEY", "/x/"):
        assert bad not in blob, f"agent 环境里漏了 {bad!r}"
    # oracle 走的是同一份 agent_env
    assert "**self._sidecar_env_for_oracle()," in HG
    assert "sess.agent_env()" in HG


def test_w3_delivery_is_extracted_before_the_session_dies():
    """W3:取件必须在 `backend.destroy(s.id); s = None` 之前。

    实测踩过:原本放最外层 finally,而 clean replay 会先销毁会话,
    等到 finally 时 host 目录早没了 —— 报 host=None,看起来像交付不存在。"""
    extract_at = HG.index("delivery_snapshot = self._extract_sidecar_delivery(s)")
    destroy_at = HG.index("                    backend.destroy(s.id)\n                    s = None")
    assert extract_at < destroy_at, "取件排在会话销毁之后了 —— 永远取不到"

    # S3:还要在**宿主回归之前**。`_run_regression` 跑的是 agent 可写的
    # `tests/`,而每一次 exec 都带着 sidecar 令牌 —— 于是有个窗口:API 只
    # 返回占位串骗过 oracle,再由 `tests/` 里一个必过的测试在这窗口内调
    # sidecar 把工件补写出来,U1–U4 全绿。取件绑在 oracle 的观察窗口上,
    # 那条路才断:oracle 看见什么,采纳就判什么。
    oracle_at = HG.index("cap_run = self._run_oracle(s, oracle_snap)")
    regression_at = HG.index("reg_run = self._run_regression(s)")
    assert oracle_at < extract_at < regression_at, (
        "取件没夹在 oracle 与宿主回归之间 —— `tests/` 里补写工件的窗口又开了")


def test_w4_extraction_failure_is_not_adoption_failure():
    """W4:取件失败/无取件器/核验器出错,三种各有各的 reason。"""
    for reason in ("NO_DELIVERY_EXTRACTED", "NO_DELIVERY_EXTRACTOR",
                   "RECEIPT_VERIFIER_ERROR"):
        assert reason in HG, f"少了 {reason} —— 会被含糊成 U4 红"
    assert "这不是 U4 红" in SS or "取件失败" in HG


def test_w4b_no_delivery_is_reported_as_extraction_failure():
    """W4 的行为面:`verify(..., delivery=None)` 必须报**取件失败**,
    不是采纳失败。

    变异闸门 M56c 抓到的逃逸:原钉死只查 `host_guided.py` 里有没有那个字符串,
    而这条分支在 `sidecar_session.py` 里 —— 把它的 reason 改成
    RECEIPT_VERIFICATION_FAILED,没人看得见。而那正是"harness 的毛病记成
    被测方的失败"的具体形态。"""
    import sys

    sys.path.insert(0, str(REPO / "src"))
    from repoproof.runner import sidecar_session as ss

    class _S:
        """替身:没有上游故障(S1 之后,verify 会先问这一条)。"""

        def upstream_failures_on_expected_items(self):
            return []

    got = ss.verify(_S(), task_id="whatever", delivery=None)   # type: ignore[arg-type]
    assert got["ok"] is False
    assert got["reason"] == "NO_DELIVERY_EXTRACTED", (
        f"取件失败被报成了 {got['reason']!r} —— harness 的毛病记成被测方的失败")
    assert got.get("attribution") == "harness"
    assert "取件失败" in got["detail"] or "无从判断" in got["detail"]


def test_w4c_upstream_failure_is_reported_before_extraction(monkeypatch):
    """S1:**上游自己崩了**要报成 harness 侧故障,且排在取件判定之前。

    顺序不能反:上游崩了的那几项,被测方本来就拿不到结果,交付自然也缺 ——
    先判"取不到交付"就会把我们浏览器崩了记成它没交东西。更糟的是模型看见
    502/400 会**合理地**改走自抓,终点归成"重实现",**归因完全反了**。"""
    import sys

    sys.path.insert(0, str(REPO / "src"))
    from repoproof.runner import sidecar_session as ss

    class _S:
        def upstream_failures_on_expected_items(self):
            return [{"error": "UpstreamExecutionError: worker 失败",
                     "request_nonce": "a", "input_digest": "d"}]

    got = ss.verify(_S(), task_id="whatever", delivery=None)   # type: ignore[arg-type]
    assert got["reason"] == "UPSTREAM_EXECUTION_ERROR", (
        f"上游崩了却报成 {got['reason']!r} —— 归因反了")
    assert got.get("attribution") == "harness"


def test_w5_adoption_failure_is_attributed_to_the_agent_not_blocked():
    """W5(2026-08-15 按 S2 改写):**采纳不成立 = 被测方失败,不是 BLOCKED。**

    原来一律走 `missing_external` → 短路成 BLOCKED,与"profile 没登记"
    "宿主基线不健康"同桶。而这道题存在的全部理由就是把"没真用上游"判成
    被测方失败 —— 一判出来就被塞进"不算模型失败、可重跑"的那格,等于白判。

    现在按归因分流:harness 侧的四种(取件器缺失 / 取不到交付 / 核验器出错 /
    上游崩了)仍走 missing_external(那些**确实**不是被测方的错);
    U2/U3/U4 判红并进 capability 侧,带 attribution=agent 与 taxonomy 类型。
    """
    assert "_HARNESS_SIDE_RECEIPT_REASONS" in HG
    assert 'verifier="AdoptionVerifier"' in HG
    assert '"attribution": "agent"' in HG
    assert "_adoption_failure_type" in HG
    assert "gate.verdict =" not in HG, "对 verdict 做了手术 —— 会与 reasons 对不上"

    # 四种 harness 侧原因一个都不能少 —— 少一个就会被误记成被测方失败
    import re

    block = re.search(r"_HARNESS_SIDE_RECEIPT_REASONS = frozenset\(\{(.*?)\}\)",
                      HG, re.S).group(1)
    for r in ("NO_DELIVERY_EXTRACTOR", "NO_DELIVERY_EXTRACTED",
              "RECEIPT_VERIFIER_ERROR", "UPSTREAM_EXECUTION_ERROR"):
        assert r in block, f"{r} 不在 harness 侧原因集里 —— 会被记成被测方失败"


def test_w5b_adoption_failure_types_map_to_the_contract_taxonomy():
    """S2 的另一半:红掉的谓词要映射成契约已声明的失败类型。

    映射不上等于归因说不清,而预注册的 Q3 明写"出现说不清的,该发作废"。"""
    import sys

    sys.path.insert(0, str(REPO / "src"))
    import yaml

    from repoproof.runner.host_guided import HostGuidedRunner

    declared = set(yaml.safe_load(
        (REPO / "benchmarks" / "v2" / "tasks" / "t3_sidecar_v1"
         / "contract.yaml").read_text(encoding="utf-8"))["failure_taxonomy_expected"])
    f = HostGuidedRunner._adoption_failure_type
    cases = {
        "U2.symbol": "WRONG_UPSTREAM_SYMBOL",
        "U3.coverage": "SYMBOLIC_INVOCATION_ONLY",
        "U4.adoption": "UPSTREAM_CALLED_BUT_RESULT_UNUSED",
    }
    for check, want in cases.items():
        got = f(None, {"findings": [{"check": check, "ok": False}]})
        assert got == want, f"{check} → {got},期望 {want}"
        assert got in declared, f"{got} 不在契约的 failure_taxonomy_expected 里"
    both = f(None, {"findings": [{"check": "U3.coverage", "ok": False},
                                 {"check": "U4.adoption", "ok": False}]})
    assert both == "UPSTREAM_CAPABILITY_REIMPLEMENTED" and both in declared


def test_w6_lazy_profile_registration_is_a_whitelist():
    """W6:惰性加载按白名单,不扫目录。"""
    src = (REPO / "src" / "repoproof" / "execution"
           / "runtime_profiles.py").read_text(encoding="utf-8")
    assert "_LAZY_DEFS" in src
    assert "rglob" not in src and "iterdir" not in src, (
        "扫目录了 —— 放个文件进去就凭空多出一个对外承诺的名字")


def test_w7_item_count_must_be_at_least_two():
    """U3 的分母 <2 时抓不住'一次调用充抵所有项' —— 起会话就该拒绝。"""
    import sys

    sys.path.insert(0, str(REPO / "src"))
    from repoproof.execution.runtime_profiles import profile
    from repoproof.runner import sidecar_session as ss

    with pytest.raises(ValueError, match="至少 2"):
        ss.start(profile=profile("rt-inprocess-v1"), run_id="x",
                 run_dir=Path("/tmp"), item_count=1)


def test_w8_the_real_run_passed_all_four_predicates():
    """接线的现场证明:**真实模型**跑过一次 host-run,四道谓词全过。

    2026-08-15 改:原来取 `runs/` 里最新的那一发,而失败侧矩阵之后最新的
    是负控冒烟(它**本该**红在 U4)—— 于是这条把"负控如期红了"读成"接线
    断了"。取真实模型的最近一发才是它想说的事,而且更强:冒烟是我们自己
    塞的脚本,它绿证明不了接线对模型也成立。
    """
    import json as _json

    ledger = REPO / "benchmarks" / "v2" / "runs.jsonl"
    rows = [_json.loads(x) for x in ledger.read_text(encoding="utf-8").splitlines()
            if x.strip()] if ledger.is_file() else []
    real = [r for r in rows
            if str(r.get("task_id", "")).startswith("t3-sidecar")
            and not str(r.get("model", "")).startswith("fake")
            and str(r.get("verdict", "")).startswith("PASS")]
    if not real:
        pytest.skip("尚未有真实模型的 T3-SIDECAR 通过发次")
    d = Path(REPO / "runs") / str(real[-1]["run_id"])
    if not (d / "report.json").is_file():
        # `runs/` 不进仓,而钉死会跑在临时 worktree 里(变异闸门就是这么跑的)。
        # 台账在树里、run 目录不在 —— 那不是"接线断了",是这里没有那份证据。
        pytest.skip(f"run 目录不在本树里:{d}")
    rep = json.loads((d / "report.json").read_text(encoding="utf-8"))
    rv = rep.get("receipt_verification")
    assert rv is not None, "报告里没有回执核验 —— 接线断了"
    assert rv["ok"] is True, [f for f in rv["findings"] if not f["ok"]]
    checks = {f["check"] for f in rv["findings"]}
    assert {"U1.chain", "U1.signature", "U1.count", "U2.symbol",
            "U2.upstream_identity", "U3.coverage", "U4.adoption"} <= checks
    assert (d / "upstream_receipts.jsonl").is_file(), "台账没落在 run 目录"


def test_w5c_the_routing_decision_itself_is_pinned_by_behavior():
    """S2 的判定**行为**:U2/U3/U4 判红 → 算被测方;四种 harness 原因 → 不算。

    上面那条 W5 读的是源码串,而串钉死挡不住"if 还在、分支反了"(M46a 一类)。
    这条直接喂结论字典,考它把每一种情况分到哪一侧。
    """
    import sys

    sys.path.insert(0, str(REPO / "src"))
    from repoproof.runner.host_guided import HostGuidedRunner

    side = HostGuidedRunner._receipt_failure_side
    # 采纳判红 = 被测方失败。判成 harness 就等于把这道题的结论塞进"可重跑"。
    for reason in ("RECEIPT_VERIFICATION_FAILED", "", "U4"):
        assert side(None, {"ok": False, "reason": reason}) == "agent", (
            f"{reason!r} 被判成 harness 侧 —— 没真用上游会被记成'不算模型失败'")
    # 四种(现为五种)确实不该记到被测方头上的
    for reason in ("NO_DELIVERY_EXTRACTOR", "NO_DELIVERY_EXTRACTED",
                   "RECEIPT_VERIFIER_ERROR", "UPSTREAM_EXECUTION_ERROR",
                   "DELIVERY_SHAPE_INVALID"):
        assert side(None, {"ok": False, "reason": reason}) == "harness", (
            f"{reason!r} 记到了被测方头上 —— harness 的毛病算成它的失败")
    # 显式归因优先(S1 走的就是这条)
    assert side(None, {"ok": False, "reason": "whatever",
                       "attribution": "harness"}) == "harness"


def test_w9_upstream_failures_are_scoped_to_our_own_items():
    """上游故障必须**按 harness 自己算的 input_digest** 圈定范围。

    不圈的话有个现成的钻空子法:拿一个自造的坏输入去打 sidecar,把封存浏览器
    弄崩,于是"上游故障非空"→ 整发次判 BLOCKED(不算模型失败、可重跑)——
    交白卷反而比交错答案划算。故障要落在**我们下发的那几项**上才算数。
    """
    import sys

    sys.path.insert(0, str(REPO / "src"))
    from repoproof.receipts.model import CANON_JSON, digest_of
    from repoproof.runner.sidecar_session import SidecarSession

    class _H:
        def __init__(self, fails):
            self._f = fails

        def upstream_failures(self):
            return self._f

    items = [{"request_nonce": "a", "url": "http://x/?item=a"},
             {"request_nonce": "b", "url": "http://x/?item=b"}]
    mine = digest_of({"text": items[0]["url"]}, canon=CANON_JSON)
    theirs = digest_of({"text": "http://x/?item=made-up"}, canon=CANON_JSON)

    def _s(fails):
        return SidecarSession(profile=None, ledger=None, key=b"", run_nonce="",
                              run_id="", handle=_H(fails), fixture_url="http://x/",
                              items=items)

    assert _s([{"input_digest": theirs, "error": "boom"}]
              ).upstream_failures_on_expected_items() == [], (
        "别人自造的输入把浏览器打崩,也算到我们头上 —— 交白卷就能换 BLOCKED")
    assert len(_s([{"input_digest": mine, "error": "boom"},
                   {"input_digest": theirs, "error": "boom"}]
                  ).upstream_failures_on_expected_items()) == 1


def test_w10_an_upstream_crash_is_recorded_and_does_not_forge_a_receipt(tmp_path):
    """S1 在**真 sidecar 上**的行为:上游崩了要留痕,但**不许**变出一条回执。

    两头都要:
    - 不留痕 → 核验期看不见"我们的浏览器崩了",只看见"它没交东西",
      于是把 harness 的故障判成被测方失败(归因反了);
    - 留痕却顺手 `seq += 1` → 条数对不上,U1.count 会把一次 harness 故障
      读成"有人截了台账尾巴"。
    """
    import sys

    sys.path.insert(0, str(REPO / "src"))
    import urllib.error
    import urllib.request

    from repoproof.execution.upstream_sidecar import (
        UpstreamExecutionError,
        UpstreamSpec,
        start_sidecar,
    )
    from repoproof.receipts.ledger import new_key, new_nonce

    def _boom(_payload):
        raise UpstreamExecutionError("封存浏览器起不来")

    def _bad_input(_payload):
        raise ValueError("入参不对")

    # 上游取谁不重要 —— 这条考的是**故障怎么记**,不是上游是什么。
    # 用 stdlib 的 json:import 得到、身份算得出、目录小。
    spec = UpstreamSpec(distribution="stdlib-json", import_module="json",
                        dispatch={"fake.boom": _boom, "fake.bad": _bad_input})
    h = start_sidecar(spec=spec, ledger_path=tmp_path / "l.jsonl", key=new_key(),
                      run_id="r", run_nonce=new_nonce(), token="tok",
                      profile_id="rt-sidecar-test-v1", default_symbol="fake.boom")
    try:
        def _call(symbol):
            req = urllib.request.Request(
                h.base_url + "/", method="POST",
                data=json.dumps({"symbol": symbol, "input": {"text": "x"},
                                 "request_nonce": "n1"}).encode(),
                headers={"X-Sidecar-Token": h.token,
                         "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())

        code, body = _call("fake.boom")
        assert code == 502 and body.get("harness_side") is True, (
            f"上游崩了报成 {code} —— 与'被测方交了坏入参'混成一件事")
        assert h.receipts_written() == 0, "崩了还变出一条回执 —— U1.count 会读成台账被截"
        fails = h.upstream_failures()
        assert len(fails) == 1 and "UpstreamExecutionError" in fails[0]["error"]

        # 反向:入参错仍是 400,**不**记进 harness 故障清单。
        # 一刀切成 502 等于把"它交了坏入参"也算到我们头上,那是另一种归因反转。
        code, body = _call("fake.bad")
        assert code == 400 and not body.get("harness_side")
        assert len(h.upstream_failures()) == 1, "入参错被算成了 harness 故障"
    finally:
        h.shutdown()
