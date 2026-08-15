"""Held-out 准入判据的钉死 —— 出题之前先证明这道题量得到东西。

2026-08-15/16 两轮实测把一件事钉死了:**"挖空之后红了多少条"是个坏指标。**
全仓 111 个函数逐个挖空,红得最多的那个(541/554)是三行字典查找。
红的数量量的是"什么都不做",不是"写错了"。

真正该问的是盲攻单发能打多少分。H2 v1 的五个候选实测 97.3%–100%,
而按旧指标它们的红数是 541/420/362/83/77 —— **看着都很健康**。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from repoproof.execution.heldout_admission import (  # noqa: E402
    MAX_BLIND_ATTACK_RATIO,
    BlindAttack,
    judge,
)

M = "只读交付树 + 轮仓依赖源码,不读隐藏 oracle、不读原实现、不迭代,一发"


def test_a1_silence_is_not_a_pass():
    """A1:**没量过 ≠ 没问题。**

    这是整道判据存在的理由。"还没量"与"量了没问题"在台账里长得一模一样,
    而一道没被量过的 held-out 题,它的分数是什么意思谁也说不清。
    """
    v = judge(None)
    assert not v.ok
    assert any("沉默不是通过" in r for r in v.reasons)


def test_a2_the_five_real_candidates_all_die():
    """A2(**现场数据**):H2 v1 的五个候选,这道判据必须一个不剩地判死。

    这是它的判别力证明 —— 拿真实测出来的数字喂它。当时按"挖空红了多少条"
    看,这五个的红数是 541/420/362/83/77,健康得很。
    """
    measured = {                       # (盲攻拿到, 满分) —— 全是实跑数字
        "blueprint": (554, 554),
        "response": (548, 554),
        "pagination": (546, 554),
        "plugins(v1)": (542, 554),
        "etag": (539, 554),
    }
    for name, (got, total) in measured.items():
        v = judge(BlindAttack(total=total, passed=got, method=M))
        assert not v.ok, f"{name}({got}/{total})竟然过了 —— 判据没有判别力"

    # 阈值必须画在**这个形态的实测地板之下**。汇总建议 0.98,而它自己的数据
    # 里 plugins(97.8%)与 etag(97.3%)都在线下 —— 0.98 只杀得掉三个,
    # 而漏掉的那两个一个是被判死的 v1 本体,一个净剩全是英文措辞。
    assert MAX_BLIND_ATTACK_RATIO < 539 / 554, (
        f"阈值 {MAX_BLIND_ATTACK_RATIO} 高于实测地板 {539 / 554:.4f} —— "
        "它会放过和 v1 一样没意义的候选")


def test_a3_a_genuinely_hard_task_still_passes():
    """A3(**误杀侧**):一道真的难的题必须过得去。

    只有负控的判据是墙。判据挡的是"没量过"与"量出来没意义",
    不是"这题我不喜欢"(LESSONS #44:可满足性只能靠正控验)。
    """
    v = judge(BlindAttack(total=554, passed=300, method=M,
                          residual_kinds=frozenset({"behaviour", "algorithm"})))
    assert v.ok, v.reasons
    # 边界:恰好在线上要判死,线下一点点要放过
    n = 554
    just_over = int(n * MAX_BLIND_ATTACK_RATIO) + 1
    assert not judge(BlindAttack(total=n, passed=just_over, method=M)).ok
    assert judge(BlindAttack(total=n, passed=int(n * 0.90), method=M)).ok


def test_a4_the_method_must_be_written_down():
    """A4:攻击方法必填 —— 分数无从复核的话,判据挡不住敷衍。

    判据只看一个数,攻击者写得烂分数自然低,题就"合格"了。挡不住这个,
    但至少要让复核的人看得见那一发是怎么攻的。这条边界写在模块 docstring 里。
    """
    assert not judge(BlindAttack(total=554, passed=300, method="")).ok
    assert not judge(BlindAttack(total=554, passed=300, method="   ")).ok
    src = (REPO / "src" / "repoproof" / "execution"
           / "heldout_admission.py").read_text(encoding="utf-8")
    assert "挡不住敷衍" in src, "判据自己的盲区没写出来"


def test_a5_the_threshold_is_justified_not_picked():
    """A5:阈值要有出处。凭空的数字日后没人敢动,也没人敢信。"""
    src = (REPO / "src" / "repoproof" / "execution"
           / "heldout_admission.py").read_text(encoding="utf-8")
    assert "不是拍的,是按实测地板定的" in src, "阈值没有说明出处"
    assert "97.3%" in src and "etag" in src, "阈值没有挂上实测数据"
    # 它必须明说自己**否掉了汇总的建议值**,以及凭什么 —— 不写的话,
    # 下一个人只会看到两个不一样的数字,不知道哪个是想清楚过的
    assert "0.98" in src and "否掉了这个值" in src
    assert 0.9 <= MAX_BLIND_ATTACK_RATIO < 1.0
