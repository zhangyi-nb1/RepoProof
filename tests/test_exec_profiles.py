"""执行侧四类 profile 指纹的钉死(EXECUTOR-UPGRADE-PLAN S1)。

**冻结判据**(先写判据与反例,再写实现;措辞此后不改):

- P1 **确定性**:同样的输入,任何时候、任何进程算出来的 hash 逐字节相同。
  不得混入时间戳、绝对路径、dict 插入序、随机数。反例:把 `runs/` 目录名
  或 `datetime.now()` 拌进去 —— 同一配置每次跑出不同指纹,历史发次之间
  再也无法配对。
- P2 **单变量可归因**:改动某一面的任一字段,**只有该面的 hash 变**,其余
  三面不变。这正是拆成四个 hash 而不是一个大 hash 的**全部理由**:一个
  大 hash 只能告诉你"配置变了",拆开才能告诉你"变的是工具面还是上下文面"。
  反例:把 obs_char_cap 同时拌进 tool 与 context 两面 —— 改一个数两面全变,
  消融时无法判断收益来自哪一面。
- P3 **exec_fingerprint 只认发次路径上的代码**:`src/repoproof/**` 变则变;
  `scripts/` `docs/` `tests/` 变则**不变**。反例:用 `git rev-parse HEAD`
  当执行侧指纹 —— 改一个 docs 错别字就让全部历史发次"不可比",而它们其实
  逐字节同源(实测:0d35856..HEAD 只动了 scripts/ 与 docs/,src/ 未变,
  故批 11 的 E0 格子可以在 HEAD 直接补齐)。
- P4 **代际标签由内容推导,不由人手填**:`exec_generation` 必须从 context /
  tool profile 的实际取值推出来。反例:让调用方传一个字符串 "E0" ——
  上了 spill 却忘了改标签,E0 与 E1 的数据就会混进同一个池子,而
  EXECUTOR-UPGRADE-PLAN §2 规则 1 是"E0/E1 永不互比"。

判据只管**指纹本身**;各机制的行为由各自的钉死执法,不在这里。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.agents.profiles import (
    E0,
    exec_fingerprint,
    exec_generation,
    profile_hashes,
)

REPO = Path(__file__).resolve().parents[1]

_TOOL = {"action_protocol": "native", "obs_char_cap": 7600}
_CTX = {"policy": "full-history-resend", "obs_char_cap": 7600}
_BUD = {"max_model_calls": 36, "max_input_tokens_total": 600000, "semantics": "per_round"}


def test_hashes_are_deterministic_across_calls():
    """P1:同样的输入算两次必须逐字节相同(dict 顺序不同也一样)。"""
    a = profile_hashes(tool=_TOOL, context=_CTX, budget=_BUD)
    b = profile_hashes(tool=dict(reversed(list(_TOOL.items()))),
                       context=dict(reversed(list(_CTX.items()))),
                       budget=dict(reversed(list(_BUD.items()))))

    assert a["tool_profile_hash"] == b["tool_profile_hash"]
    assert a["context_profile_hash"] == b["context_profile_hash"]
    assert a["budget_profile_hash"] == b["budget_profile_hash"]


def test_changing_one_face_moves_only_that_hash():
    """P2:拆成四个 hash 的全部理由 —— 改工具面,上下文面与预算面不得动。"""
    base = profile_hashes(tool=_TOOL, context=_CTX, budget=_BUD)
    moved = profile_hashes(tool={**_TOOL, "action_protocol": "textbased"},
                           context=_CTX, budget=_BUD)

    assert moved["tool_profile_hash"] != base["tool_profile_hash"], "工具面没变化 = 没在记账"
    assert moved["context_profile_hash"] == base["context_profile_hash"], (
        "改工具面却把上下文面的 hash 也带动了 —— 消融时无法归因")
    assert moved["budget_profile_hash"] == base["budget_profile_hash"]


def test_changing_budget_moves_only_budget():
    """P2 的另一面:预算改动不得污染工具/上下文指纹。"""
    base = profile_hashes(tool=_TOOL, context=_CTX, budget=_BUD)
    moved = profile_hashes(tool=_TOOL, context=_CTX,
                           budget={**_BUD, "max_model_calls": 45})

    assert moved["budget_profile_hash"] != base["budget_profile_hash"]
    assert moved["tool_profile_hash"] == base["tool_profile_hash"]
    assert moved["context_profile_hash"] == base["context_profile_hash"]


def test_exec_fingerprint_tracks_src_only(tmp_path):
    """P3:src/repoproof 变则变,scripts/docs/tests 变则不变。"""
    src = tmp_path / "src" / "repoproof"
    (src / "agents").mkdir(parents=True)
    (src / "agents" / "a.py").write_text("X = 1\n")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "s.py").write_text("Y = 1\n")

    before = exec_fingerprint(tmp_path)

    (tmp_path / "scripts" / "s.py").write_text("Y = 2\n")          # 不在发次路径上
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "d.md").write_text("typo fixed\n")
    assert exec_fingerprint(tmp_path) == before, (
        "改 scripts/docs 就让指纹变 —— 历史发次会被误判为不可比")

    (src / "agents" / "a.py").write_text("X = 2\n")                # 在发次路径上
    assert exec_fingerprint(tmp_path) != before, "改 src/ 却没反映到指纹"


def test_exec_fingerprint_on_this_repo_is_stable():
    """P1/P3 落到真仓:连算两次必须一致,且是 16 位十六进制。"""
    a, b = exec_fingerprint(REPO), exec_fingerprint(REPO)
    assert a == b and len(a) == 16 and all(c in "0123456789abcdef" for c in a)


def test_generation_is_derived_not_declared():
    """P4:E0 由"全历史重发 + 无 spill + 单 bash 无 editor"推出来。"""
    assert exec_generation(context=_CTX, tool=_TOOL) == E0


def test_turning_on_spill_leaves_e0_automatically():
    """P4 的要害:上了 spill 就**自动**不再是 E0,不靠人记得改标签。"""
    gen = exec_generation(context={**_CTX, "spill_threshold_chars": 8000},
                          tool=_TOOL)

    assert gen != E0, "上了 spill 仍标 E0 —— E0/E1 数据会混进同一个池子"
    assert "S2" in gen, f"代际标签应指明是哪一步带来的,实得 {gen}"


def test_adding_editor_leaves_e0_automatically():
    """P4:多一个工具也不再是 E0(S4 上线时自动生效)。"""
    gen = exec_generation(context=_CTX,
                          tool={**_TOOL, "tools": ["bash", "str_replace_editor"]})

    assert gen != E0
    assert "S4" in gen, f"代际标签应指明是哪一步带来的,实得 {gen}"


def test_profile_hashes_carry_generation_and_fingerprint():
    """出参形状:四个 hash + 指纹 + 代际,一次给全,调用方不必自己拼。"""
    got = profile_hashes(tool=_TOOL, context=_CTX, budget=_BUD, repo=REPO)

    for k in ("tool_profile_hash", "context_profile_hash", "budget_profile_hash",
              "exec_fingerprint", "exec_generation"):
        assert got.get(k), f"缺字段 {k}"
    assert got["exec_generation"] == E0


def test_exec_fields_are_in_the_ledger_allowlist():
    """接线判据:算出来的每个字段都必须在台账允许字段表里。

    反例:字段算对了却没进 REQUIRED_FIELDS —— 记账器把它**静默丢弃**,
    E1 消融时才发现台账里根本没有代际标签,而那时发次已经跑完了。"""
    from repoproof.persistence.bench_records import REQUIRED_FIELDS

    produced = profile_hashes(tool=_TOOL, context=_CTX, budget=_BUD, repo=REPO)
    missing = [k for k in produced if k not in REQUIRED_FIELDS]

    assert not missing, f"这些字段算了但台账不收,会被静默丢弃:{missing}"


def test_preflight_failure_blocks_the_run():
    """S1 复核(**已存在的行为,钉死防回归**):preflight 不 ready 就拒开,
    且 `agent_model_call_count` 必须是 0 —— 一次模型调用都不许发生。

    计划里把"preflight 升格为强制门"列为待办,核盘发现它**早就是**强制门。
    不重做,改为钉死:哪天有人把这段拿掉,这里先红。"""
    src = (REPO / "src" / "repoproof" / "runner" / "host_guided.py").read_text(
        encoding="utf-8")

    assert "pf = run_preflight(provider)" in src, "preflight 调用被移除"
    assert "if not pf.ready:" in src, "preflight 结果不再被检查 —— 强制门失守"
    assert '"blocked": True, "preflight": pf.summary()' in src, "拒开时不再回报 preflight 证据"
    assert '"agent_model_call_count": 0' in src, "拒开时未声明零模型调用"
