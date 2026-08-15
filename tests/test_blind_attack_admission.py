"""盲攻测量驱动器的钉死(2026-08-16,D5 彩排产物)。

`heldout_admission.judge` 是纯判官;它的输入(total / passed / method /
residual_kinds)从哪来、怎么保证不掺水,由测量驱动器负责。这里冻结的是
**测量本身的判据** —— 彩排的目的就是把这些流程缺陷挡在唯一的网络窗口之外。

判据(冻结):
    B1  分数只出自 junitxml 计数,不读 pytest 退出码;失败节点名单必须
        随分数一起出来(残差分类的原料,不许省);
    B1b 套件出现 skipped ≠ 0 → 拒绝测量 —— oracle 卫生前提(host2 选型时
        "零 skip"是入选理由,量的时候不能自己破);
    B2  基线(未攻击树)不全绿 → 拒绝测量,不产出 ratio —— 基线不绿则
        任何攻击分数无从归因(与变异闸门"基线不绿即 ABORT"同一条纪律);
    B6  ratio 的分母 = **基线** total,不是攻击后 junit 的 total ——
        攻击件把收集期打崩时,攻击后的 junit 节点数会变少,拿它当分母
        等于让被测方决定分母(U3 的老病);
    B3  测量记录必须带 method(空即拒)、failed_nodes、树与文件的 digest ——
        没有这些,分数无从复核;
    B4  子进程环境强制离线:代理指向死端口,pip 禁 index —— 离线是跑出来
        的,不是声称的(browser worker 同一条纪律);
    B5  判决只走 `heldout_admission.judge`,阈值不得在驱动器里复制一份 ——
        复制的那份会在原件改动后静默漂移(M58a 的形状)。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load(script: str):
    spec = importlib.util.spec_from_file_location(script[:-3], REPO / "scripts" / script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_JUNIT_OK = b"""<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="3" failures="0" errors="0" skipped="0">
<testcase classname="tests.test_x" name="test_a"/>
<testcase classname="tests.test_x" name="test_b"/>
<testcase classname="tests.test_x" name="test_c"/>
</testsuite></testsuites>
"""

_JUNIT_ONE_RED = b"""<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="3" failures="1" errors="0" skipped="0">
<testcase classname="tests.test_x" name="test_a"/>
<testcase classname="tests.test_x" name="test_b"><failure message="boom"/></testcase>
<testcase classname="tests.test_x" name="test_c"/>
</testsuite></testsuites>
"""

_JUNIT_SKIPPED = b"""<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="2" failures="0" errors="0" skipped="1">
<testcase classname="tests.test_x" name="test_a"/>
<testcase classname="tests.test_x" name="test_b"><skipped message="nope"/></testcase>
</testsuite></testsuites>
"""


def test_b1_score_comes_from_junit_counts_with_failed_nodes() -> None:
    bam = _load("blind_attack_admission.py")
    s = bam.score_from_junit(_JUNIT_ONE_RED)
    assert (s["total"], s["passed"], s["skipped"]) == (3, 2, 0)
    assert s["failed_nodes"] == ["tests.test_x::test_b"]


def test_b1b_skips_refuse_the_measurement() -> None:
    """oracle 卫生前提:skipped ≠ 0 的一跑不配当分母,也不配当分子。"""
    bam = _load("blind_attack_admission.py")
    s = bam.score_from_junit(_JUNIT_SKIPPED)
    problems = bam.measurement_problems(baseline=s)
    assert any("skip" in p.lower() for p in problems), problems


def test_b2_dirty_baseline_refuses_no_ratio() -> None:
    """基线不全绿 → 拒绝测量。任何攻击分数在脏基线上都无从归因。"""
    bam = _load("blind_attack_admission.py")
    dirty = bam.score_from_junit(_JUNIT_ONE_RED)
    problems = bam.measurement_problems(baseline=dirty)
    assert problems, "脏基线竟然被放行"
    clean = bam.score_from_junit(_JUNIT_OK)
    assert bam.measurement_problems(baseline=clean) == []


_JUNIT_SHRUNK = b"""<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="2" failures="1" errors="0" skipped="0">
<testcase classname="tests.test_x" name="test_a"/>
<testcase classname="tests.test_x" name="test_b"><failure message="boom"/></testcase>
</testsuite></testsuites>
"""


def test_b6_denominator_is_the_baseline_total() -> None:
    """分母 = 基线 total。攻击件打崩收集期时,攻击后 junit 的节点数会缩水,
    拿它当分母等于让被测方决定分母。夹具刻意让攻击后 total(2)≠ 基线
    total(3)—— 两边相等的话这条钉死区分不了分母来源(设计 M66b 时当场
    抓到的弱点,红的粒度必须与钉死的粒度一致)。"""
    bam = _load("blind_attack_admission.py")
    baseline = bam.score_from_junit(_JUNIT_OK)          # total = 3
    attacked = bam.score_from_junit(_JUNIT_SHRUNK)      # total = 2,收集期吃掉一条
    attack = bam.build_attack(baseline=baseline, attacked=attacked,
                              method="m", residual_kinds=frozenset())
    assert (attack.total, attack.passed) == (3, 1)


def test_b3_record_requires_method_and_carries_review_material() -> None:
    bam = _load("blind_attack_admission.py")
    baseline = bam.score_from_junit(_JUNIT_OK)
    attacked = bam.score_from_junit(_JUNIT_ONE_RED)
    rec = bam.build_record(
        candidate="rehearsal-x", baseline=baseline, attacked=attacked,
        method="子代理单发,只读交付树+依赖", residual_kinds=frozenset({"behavior"}),
        digests={"delivery_tree": "sha256:aa", "attacked_file": "sha256:bb"})
    assert rec["verdict"]["ok"] is False or rec["verdict"]["ok"] is True   # 判决在场
    assert rec["failed_nodes"] == ["tests.test_x::test_b"]
    assert rec["digests"]["attacked_file"] == "sha256:bb"
    assert rec["ratio"] == 2 / 3
    try:
        bam.build_record(candidate="x", baseline=baseline, attacked=attacked,
                         method="   ", residual_kinds=frozenset(), digests={})
    except ValueError:
        pass
    else:
        raise AssertionError("method 为空竟然能出记录 —— 分数将无从复核")


def test_b4_subprocess_env_is_forced_offline() -> None:
    """离线是跑出来的,不是声称的:代理指向死端口 + pip 禁 index。"""
    bam = _load("blind_attack_admission.py")
    env = bam.offline_env({"PATH": "/usr/bin", "http_proxy": "http://corp:8080"})
    assert env["http_proxy"] == env["https_proxy"] == "http://127.0.0.1:9"
    assert env["HTTP_PROXY"] == env["HTTPS_PROXY"] == "http://127.0.0.1:9"
    assert env["PIP_NO_INDEX"] == "1"
    assert env["PATH"] == "/usr/bin"          # 其余环境不动


def test_b7_delta_baseline_must_red_exactly_the_delta_set() -> None:
    """delta 形态(post-cutoff 猎取):隐藏 oracle = PR 新增测试。合格基线 =
    旧套件全绿 + **恰好** delta 集全红 —— 这同时就是 FAIL_TO_PASS 的实测
    验证:少红 = 该 delta 在 parent 树上就能过(量不到东西),多红 = 旧套件
    在 parent 树上就有病(尺子不干净)。两个方向都拒绝测量。"""
    bam = _load("blind_attack_admission.py")
    base = bam.score_from_junit(_JUNIT_ONE_RED)         # 红的是 tests.test_x::test_b
    delta = frozenset({"tests.test_x::test_b"})
    assert bam.measurement_problems(baseline=base, delta_nodes=delta) == []
    # 少红:delta 声明了两条,基线只红一条 → parent 树上就能过的"新行为"
    p = bam.measurement_problems(
        baseline=base, delta_nodes=frozenset({"tests.test_x::test_b",
                                              "tests.test_x::test_c"}))
    assert p, "parent 树上就绿的 delta 测试竟被放行"
    # 多红:基线红了 delta 之外的东西 → 旧套件不干净
    p = bam.measurement_problems(baseline=base, delta_nodes=frozenset())
    assert p, "旧套件带红的基线竟被放行"


def test_b8_delta_ratio_is_over_the_delta_set_only() -> None:
    """delta 形态的 ratio 分母 = delta 集大小,分子 = 攻击后 delta 集里转绿的
    条数 —— 旧套件的绿不进分子(那是回归面,不是能力面)。"""
    bam = _load("blind_attack_admission.py")
    base = bam.score_from_junit(_JUNIT_ONE_RED)
    delta = frozenset({"tests.test_x::test_b"})
    attacked = bam.score_from_junit(_JUNIT_OK)          # 攻击后全绿
    attack = bam.build_attack(baseline=base, attacked=attacked,
                              method="m", residual_kinds=frozenset(),
                              delta_nodes=delta)
    assert (attack.total, attack.passed) == (1, 1)
    # 攻击后 delta 仍红 → 分子 0
    attacked2 = bam.score_from_junit(_JUNIT_ONE_RED)
    attack2 = bam.build_attack(baseline=base, attacked=attacked2,
                               method="m", residual_kinds=frozenset(),
                               delta_nodes=delta)
    assert (attack2.total, attack2.passed) == (1, 0)


def test_b9_regression_breakage_is_listed_not_blended() -> None:
    """攻击件砸了旧套件 → 单列 regression_broken,不改 ratio —— 混进分数的话,
    一个把回归面打红的烂攻击会显得'恰好没打满',把判死线搅浑。"""
    bam = _load("blind_attack_admission.py")
    base = bam.score_from_junit(_JUNIT_ONE_RED)         # delta = test_b
    delta = frozenset({"tests.test_x::test_b"})
    junit_attacked = b"""<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="3" failures="1" errors="0" skipped="0">
<testcase classname="tests.test_x" name="test_a"><failure message="broke old"/></testcase>
<testcase classname="tests.test_x" name="test_b"/>
<testcase classname="tests.test_x" name="test_c"/>
</testsuite></testsuites>
"""
    attacked = bam.score_from_junit(junit_attacked)
    rec = bam.build_record(candidate="x", baseline=base, attacked=attacked,
                           method="m", residual_kinds=frozenset(),
                           digests={}, delta_nodes=delta)
    assert rec["ratio"] == 1.0                           # delta 集 1/1
    assert rec["regression_broken"] == ["tests.test_x::test_a"]


def test_b5_verdict_goes_through_the_admission_judge_not_a_copy() -> None:
    """阈值与判决逻辑只有一份 —— 驱动器里复制一份的话,原件改动后复制品
    静默漂移(M58a 的形状:两处各说各话,谁也不知道谁在生效)。"""
    bam = _load("blind_attack_admission.py")
    from repoproof.execution import heldout_admission as ha
    assert bam.judge is ha.judge
    assert bam.BlindAttack is ha.BlindAttack
    src = (REPO / "scripts" / "blind_attack_admission.py").read_text(encoding="utf-8")
    assert "0.95" not in src, "阈值被复制进驱动器 —— 只许 import,不许抄"
