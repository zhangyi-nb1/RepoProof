"""S2′ 处理暴露离线重放的钉死(预注册 S2prime-exposure-replay-prereg-20260814)。

这个量具的产出会直接决定"要不要再花模型额度重跑消融",所以它自己必须先
被钉住。冻结判据(先写判据与反例;措辞此后不改):

- X1 **自证会拒绝出数**。`selfcheck()` 在真投影上必须全过;在被做过手脚的
  投影上必须报出来。反例:自证永远返回空 → 它报的 0 分不清是"真没有"
  还是"我瞎了",而这正是批 14 零激活当时的处境。
- X2 **偏移错位查得出,且不误报末条提交**。反例(漏报):动作数与结果数
  对不上却判可靠 → 覆盖率数字本身是错的;反例(误报):把每轮末尾那条
  `(1 动作, 0 结果)` 的提交算成风险 → 每发都报红,审计失去意义。
- X3 **修前量具只换 `_cmd_of`,窗口规则一字不动**。反例:两边规则不同 →
  算出来的差值不是量具的差值,是两套规则的差值。
- X4 **覆盖率按处理臂算,对照臂不进分母**。反例:把对照臂混进去 → 分母
  被灌水一倍,50% 门槛形同虚设(对照臂本就不该有激活)。
- X5 **抽样只列修前修后不一致的**。反例:一致的也列 → 人工核对被淹没在
  噪声里,而一致的部分再多也说明不了什么。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "replay_projection_exposure", REPO / "scripts" / "replay_projection_exposure.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


RP = _load()


def _msg(role: str, **extra) -> dict:
    return {"role": role, "content": "y" * 400, "extra": extra}


# ------------------------------------------------------------------ X1
def test_selfcheck_passes_on_the_real_projector():
    """X1 正面:真投影上自证必须全过,否则脚本永远出不了数。"""
    assert RP.selfcheck() == []


def test_selfcheck_catches_a_sabotaged_projector(monkeypatch):
    """X1 反面:投影被做过手脚时,自证必须报出来 —— 检查器先证明自己查得出。"""
    monkeypatch.setattr(RP, "project_window",
                        lambda msgs, **kw: (msgs, {"folded_messages": 0}))
    bad = RP.selfcheck()
    assert bad, "投影被换成'什么都不折'了,自证却全过 —— 那它什么都证明不了"
    assert any("链式" in b for b in bad)


def test_selfcheck_catches_an_overeager_projector(monkeypatch):
    """X1 假阳侧:投影变成'什么都折'时也必须报 —— 只查漏不查冒进不算数。"""
    monkeypatch.setattr(RP, "project_window",
                        lambda msgs, **kw: (msgs, {"folded_messages": 99}))
    bad = RP.selfcheck()
    assert any("假阳" in b or "窗口边界" in b for b in bad), (
        f"投影变成'什么都折'却没被自证抓住:{bad}")


# ------------------------------------------------------------------ X2
def _write_traj(d: Path, name: str, msgs: list[dict]) -> None:
    import json

    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps({"messages": msgs}, ensure_ascii=False),
                          encoding="utf-8")


def test_alignment_audit_flags_a_real_misalignment(tmp_path):
    """X2 漏报侧:动作数与结果数对不上,必须判为可能错位。"""
    d = tmp_path / "run1"
    _write_traj(d, "trajectory_round1.json", [
        _msg("assistant", actions=[{"command": "cat a"}, {"command": "cat b"}]),
        _msg("tool"), _msg("tool"), _msg("tool"),        # 2 条动作却 3 条结果
    ])
    got = RP.alignment_audit([d])
    assert got["risky_misalignments"] == 1, got
    assert "不可用" in got["verdict"]


def test_alignment_audit_does_not_flag_trailing_submit(tmp_path):
    """X2 误报侧:每轮末条 `(1 动作, 0 结果)` 的提交不是风险。

    反例:把它算成风险 → 每发都报红,审计失去意义。"""
    d = tmp_path / "run2"
    _write_traj(d, "trajectory_round1.json", [
        _msg("assistant", actions=[{"command": "cat a"}]),
        _msg("tool"),
        _msg("assistant", actions=[{"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"}]),
    ])
    got = RP.alignment_audit([d])
    assert got["risky_misalignments"] == 0, got
    assert got["trailing_submit_no_result"] == 1
    assert got["aligned"] == 1


# ------------------------------------------------------------------ X3
def test_legacy_measurer_differs_only_in_cmd_of():
    """X3:修前量具与修后量具的差别只在 `_cmd_of`,窗口规则同一套。

    构造:链式两命令,前一条 tool 挡住回看。修前必漏,修后必中。"""
    msgs: list[dict] = []
    for _ in range(RP.WINDOW_READS + 3):
        msgs.append(_msg("assistant", actions=[{"command": "pwd"},
                                               {"command": "sed -n '1,50p' a.py"}]))
        msgs.append(_msg("tool"))
        msgs.append(_msg("tool"))
    _, new = RP.project_window(msgs)
    old = RP._project_window_legacy(msgs)
    assert new["folded_messages"] > 0, "修后量具没命中 —— 差值无从谈起"
    assert old["folded_messages"] == 0, "修前量具竟然命中了 —— 那批 14 的零激活就无从解释"

    # 修后量具认出的读取条数确实超过窗口(否则"命中"可能只是窗口太小);
    # 修前量具即便把窗口开到 0 也仍是 0 —— 它一条读取都认不出来。
    from repoproof.agents.context_projector import _cmd_of

    reads_new = [i for i, m in enumerate(msgs)
                 if m.get("role") == "tool" and RP._is_foldable_read(_cmd_of(msgs, i))]
    assert len(reads_new) > RP.WINDOW_READS
    assert RP._project_window_legacy(msgs, window=0)["folded_messages"] == 0


# ------------------------------------------------------------------ X4 / X5
def test_coverage_counts_only_the_treated_arm():
    """X4:对照臂不进分母 —— 它本就不该有激活,混进去等于把门槛砍半。"""
    src = (REPO / "scripts" / "replay_projection_exposure.py").read_text(encoding="utf-8")
    assert 'treated = [r for r in rows if r.get("arm", "").startswith("B")' in src, (
        "覆盖率的分母不再是处理臂 —— 对照臂灌进来会让 50% 门槛形同虚设")
    assert "cov_new = len(nonzero) / len(treated)" in src


def test_sampling_lists_only_the_differences(tmp_path):
    """X5:抽样只列修前修后不一致的条目。"""
    d = tmp_path / "run3"
    _write_traj(d, "trajectory_round1.json", [
        _msg("assistant", actions=[{"command": "cat only.py"}]),
        _msg("tool"),                                   # 修前修后一致
        _msg("assistant", actions=[{"command": "pwd"}, {"command": "cat two.py"}]),
        _msg("tool"), _msg("tool"),                     # 第二条:修前空,修后 cat
    ])
    got = RP.sample_mappings(d, limit=10)
    assert got, "该有不一致的条目"
    assert all(x["cmd_old"] != x["cmd_new"] for x in got), (
        "列出了修前修后相同的条目 —— 人工核对会被噪声淹没")
    assert any("two.py" in x["cmd_new"] for x in got)


# ------------------------------------------------------------------ 接线
def test_committed_evidence_matches_a_fresh_replay():
    """接线钉死:落盘证据必须与现算一致 —— 防止脚本改了而证据没重算。"""
    import json

    p = REPO / "docs" / "evidence" / "projection_exposure" / "replay-E1-S2prime.json"
    if not p.is_file():
        return
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["window_reads"] == RP.WINDOW_READS, (
        "窗口大小变了而证据没重算 —— 跑 scripts/replay_projection_exposure.py")
    assert doc["gate"]["threshold_coverage"] == 0.5
    assert doc["alignment_audit"]["risky_misalignments"] == 0
    # 预注册 X3/X4 的结论:两条都过才有资格进在线消融
    assert doc["gate"]["coverage_passes"] is True
    assert doc["gate"]["every_model_cell_nonzero"] is True
