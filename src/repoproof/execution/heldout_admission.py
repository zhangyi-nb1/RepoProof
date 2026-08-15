"""Held-out 任务的**准入判据** —— 出题之前先证明这道题量得到东西。

## 为什么要有它

2026-08-15/16 两轮实测把一件事钉死了:**"挖空之后上游测试红了多少条"是个
坏指标**。全仓 111 个函数逐个挖空扫过一遍,红得最多的那个(541/554)是
`utils.py::PrefixedMappingProxy.__getitem__` —— 三行字典查找。

    红的数量量的是"什么都不做",不是"写错了"。

真正该问的是:**一个只读交付树 + 依赖源码、不看隐藏 oracle、不迭代的攻击者,
一发能打多少分?** 打得越高,这道题剩下的信息量越少。

H2-SEAM-REIMPL v1 就死在这:五个候选 seam 的强攻单发成绩是
554 / 548 / 546 / 542 / 539(满分 554)—— 全部 ≥97%,而当时按"红了多少条"
看,它们的红数是 541/420/362/83/77,**看着都很健康**。

## 这道闸门做什么

不判"这道题好不好",只判**它有没有被这样量过**,以及量出来的数字是否越线。

- 没量过 → 不许当 held-out。**沉默不是通过。**
- 量过且强攻单发 ≥ `MAX_BLIND_ATTACK_RATIO` → 判死,理由写进结论。

## 它挡不住什么(如实写在这儿)

它只看一个数。攻击者写得烂,分数自然低,题就"合格"了 —— 所以记录里必须
带上攻击者是怎么做的(`method`),复核的人才能判那一发攻击算不算数。
判据挡不住敷衍,只挡得住**没人量过**。
"""

from __future__ import annotations

from dataclasses import dataclass

# 强攻单发的上限。超过这条线,题目剩下的可测面已经小到没有意义。
#
# **0.95 不是拍的,是按实测地板定的。** 汇总建议的是 0.98,而它自己的数据
# 就否掉了这个值:五个候选的盲攻成绩是
#
#     blueprint 554/554 = 100.0%      response  548/554 = 98.9%
#     pagination 546/554 = 98.6%      plugins   542/554 = 97.8%
#     etag       539/554 = 97.3%
#
# 0.98 只杀得掉前三个 —— 而 plugins 正是被判死的 v1 本体,etag 净剩的 15 条
# 全是三句 warning 的**英文措辞**。**这个形态实测出来的地板是 97.3%**,
# 线必须画在地板之下,否则它只是把最烂的几个挡掉,放过同样没意义的那两个。
#
# 0.95 同时给真难题留了 5% 余量(554 条里 27 条以上的头寸)。这条线是钉死
# A2 的现场数据定的,不是感觉 —— 改它要有新的实测,不是新的直觉。
MAX_BLIND_ATTACK_RATIO = 0.95

# 净剩必须是**行为**,不是散文/常量/措辞。etag 那 15 条残值全是字符串比对 ——
# 判据要是只看条数,它会被当成"最好的候选"。
_PROSE_RESIDUALS = frozenset({"wording", "prose", "message_text", "docstring"})


@dataclass(frozen=True)
class BlindAttack:
    """一发**盲攻**的记录。

    盲攻 = 只读交付树 + 依赖源码,**不读隐藏 oracle、不读原实现、不迭代**。
    "不迭代"很要紧:允许迭代的话攻击者就是在跑公开面调参,量的是公开面
    带宽而不是先验可推导性。
    """

    total: int                  # 隐藏 oracle 的总条数
    passed: int                 # 盲攻一发拿到多少条
    method: str                 # 怎么攻的 —— 没有这句,分数无从复核
    residual_kinds: frozenset[str] = frozenset()   # 净剩那几条考的是什么

    @property
    def ratio(self) -> float:
        return self.passed / self.total if self.total else 1.0


@dataclass(frozen=True)
class AdmissionVerdict:
    ok: bool
    reasons: tuple[str, ...]


def judge(attack: BlindAttack | None) -> AdmissionVerdict:
    """判一道候选 held-out 题能不能开跑。

    `attack is None` = **没量过**。这时一律不许 —— 沉默不是通过,而"还没量"
    与"量了没问题"在台账里长得一模一样,那正是这套判据要拆开的两件事。
    """
    if attack is None:
        return AdmissionVerdict(False, (
            "没有盲攻记录 —— **沉默不是通过**。held-out 资格要求先证明这道题"
            "量得到东西:一个只读交付树+依赖、不看隐藏 oracle、不迭代的攻击者"
            "一发能打多少分。没量过就开跑,等于把'不知道'记成'没问题'。",))

    reasons: list[str] = []
    if not attack.method.strip():
        reasons.append("盲攻没写清怎么攻的 —— 分数无从复核,判据挡不住敷衍,"
                       "所以 method 必填")
    if attack.total <= 0:
        reasons.append("隐藏 oracle 条数 ≤ 0 —— 分母都没有,分数没有意义")
    elif attack.ratio >= MAX_BLIND_ATTACK_RATIO:
        reasons.append(
            f"盲攻单发 {attack.passed}/{attack.total} = {attack.ratio:.1%},"
            f"越过 {MAX_BLIND_ATTACK_RATIO:.0%} 线 —— 这道题剩下的可测面已经"
            "小到没有意义。(参照:H2 v1 的五个候选是 97.3%–100%,而按'挖空红"
            "了多少条'看它们的红数是 541/420/362/83/77,**看着都很健康**。)")

    residual = attack.residual_kinds - _PROSE_RESIDUALS
    if attack.residual_kinds and not residual:
        reasons.append(
            f"净剩考的全是散文类({sorted(attack.residual_kinds)})—— "
            "字符串措辞不是能力。实录:etag 那个候选净剩 15 条,条数是五个候选里"
            "最多的,但全是三句 warning 的英文措辞比对,换成真值即满分。")
    return AdmissionVerdict(not reasons, tuple(reasons))
