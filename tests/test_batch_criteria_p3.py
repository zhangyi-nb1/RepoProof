"""P3(denied 不跨轮继承)单轮判定的钉死 —— 批 15 误报的处方。

实录反例(批 15,E1-S2PRIME-ABLATION2-20260817,序 4):r2/r3 本轮
denied=0 而 policy_violations=1,来源是**本轮自产**的 upstream 就地改动
(`repair.round.end` 的 fatal_violations=["upstream"],verification 时点
检出,非 denied 来源)。旧启发式 `pol == d or pol == 0` 解释不了这个
形态,把它误报为跨轮继承,整批合议被拖成"未通过"——而 P3 要防的事
(denied 计数跨轮漏进下一轮)在全部 11 轮里都没有发生(轨迹级复核)。

修法不是放宽:真继承的形状(denied=0、pol>0、本轮 fatal 解释不了)
必须照抓 —— 本文件同时钉住两边。

新符号刻意不在模块级导入(LESSONS #34:红的粒度必须与钉死的粒度一致)。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _p3():
    spec = importlib.util.spec_from_file_location(
        "bc", REPO / "scripts" / "batch_criteria.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.p3_round_ok


def test_own_round_fatal_explains_violations() -> None:
    """批 15 序 4 r2/r3 的形态:denied=0、pol=1、本轮 fatal=["upstream"]
    —— 本轮自己解释得了,不是继承,不许报警。"""
    p3 = _p3()
    assert p3(0, 1, ["upstream"]) is True
    # 序 4 r1 的形态:denied=2、pol=0、fatal=["patch_lines"](patch 预算
    # 破线不计入 policy_violations)—— 零违规恒过
    assert p3(2, 0, ["patch_lines"]) is True


def test_true_inheritance_shape_still_caught() -> None:
    """P3 存在的意义:denied=0、pol>0、本轮 fatal 解释不了 —— 这才是
    "上一轮的 denied 漏进了本轮"的形状,必须照抓。"""
    p3 = _p3()
    assert p3(0, 1, []) is False
    assert p3(0, 1, None) is False
    assert p3(0, 3, ["upstream"]) is False, "违规数超出本轮 fatal 能解释的部分仍是继承嫌疑"


def test_zero_and_own_denied_pass_unchanged() -> None:
    """旧行为不变的两翼:零违规恒过;pol == denied 记的是本轮自己的
    (该不该计入由 Q1 追究,不归 P3)。"""
    p3 = _p3()
    assert p3(0, 0, []) is True
    assert p3(4, 0, []) is True
    assert p3(2, 2, []) is True
