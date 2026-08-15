"""变异归因唯一性的钉死(2026-08-16)。

护的不是功能,是**语料的证明力**:一条变异显示 CAUGHT,必须意味着
"登记簿声明要考的那条判断抓住了它",而不是"随便哪条判断红了"。
M59c / M62d,e / M64c 一天之内三次同型逃逸:合成缺陷被更早的另一条判断
先杀(比例关先于散文关),被考的判断掏掉也看不出差别 —— 语料在替一条
不存在的防线背书,而且每次都靠人在场才发现。这里把它变成机器执法。

判据(冻结):
    E1  没有红 = ESCAPED,声明什么都救不回来;
    E2  有红、有声明、声明的判断一个都没红 = **MISATTRIBUTED**(登记簿
        错误,非通过 —— 要么钉死没隔离好,要么声明写错了,两种都得修);
    E3  有红、声明的判断在红名单里 = CAUGHT,并记下是谁抓的;
    E4  参数化节点按基名匹配(`test_x[3]` 算 `test_x`),但**不做前缀
        猜测**(`test_x_more` 不算 `test_x`);
    E5  有红、没声明 = CAUGHT 但进 `unattributed` 诚实清单(存量补齐用,
        沉默的缺口不许有);
    E6  整文件收集期崩溃 = CAUGHT/COLLAPSE,单列可见 —— 判断没上场不是
        因为别人抢先,是因为全场阵亡,与 MISATTRIBUTED 是两种病;
    E7  退出码红而 junitxml 里一个失败节点都解析不出 = GATE_PLUMBING,
        闸门自身的管道坏了,不得冒充 CAUGHT;
    E8  归因金丝雀(C1:声明一个永不存在的判断)必须恰好判出
        MISATTRIBUTED,否则整个闸门的归因结论自宣无效。

边界(如实声明,与 heldout_admission 同一条纪律):归因粒度到 junitxml
**节点**。同一个测试函数里多条断言的先后遮蔽,这里量不到 —— 那一半仍然
靠"合成缺陷必须只触发被考的那条判断"的设计纪律。
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


# ---------------------------------------------------------------- 分类语义

def test_no_red_is_escaped_regardless_of_declaration() -> None:
    """E1:没有红就是 ESCAPED —— 声明得再对,套件没抓住就是没抓住。"""
    mg = _load("mutation_gate.py")
    outcome, extra = mg.classify_catch(
        exit_code=0, failed=set(), collapsed=False, declared=["test_wanted"])
    assert outcome == "ESCAPED", (outcome, extra)


def test_red_without_the_declared_judge_is_misattributed() -> None:
    """E2:红了、但声明的判断没红 = MISATTRIBUTED,不是 CAUGHT。

    这正是 M59c/M64c 的形状:别的判断先杀了合成缺陷,被考的那条掏掉也
    看不出差别 —— 以前这种情况直接记 CAUGHT,语料发的是假保证。"""
    mg = _load("mutation_gate.py")
    outcome, extra = mg.classify_catch(
        exit_code=1, failed={"test_some_other_gate"}, collapsed=False,
        declared=["test_the_judge_under_exam"])
    assert outcome == "MISATTRIBUTED", (outcome, extra)
    # 修理人需要两样东西:实际红了谁、声明的是谁。都得在场。
    assert extra["failed_nodes"] == ["test_some_other_gate"]
    assert extra["expected_catcher"] == ["test_the_judge_under_exam"]


def test_red_from_the_declared_judge_is_caught_and_attributed() -> None:
    """E3:声明的判断红了 = CAUGHT,且记下抓它的是谁。旁边有别的红不碍事
    (一个缺陷打红多条判断是正常的),要害是**被考的那条真的上场了**。"""
    mg = _load("mutation_gate.py")
    outcome, extra = mg.classify_catch(
        exit_code=1, failed={"test_collateral", "test_the_judge_under_exam"},
        collapsed=False, declared=["test_the_judge_under_exam"])
    assert outcome == "CAUGHT"
    assert extra["attribution"] == "DECLARED"
    assert extra["attributed_to"] == ["test_the_judge_under_exam"]


def test_parametrized_red_matches_base_name_but_prefixes_do_not() -> None:
    """E4:`test_x[3]` 算 `test_x` 抓的;`test_x_more` 不算 —— 前缀猜测
    会把邻居的功劳记到声明头上,那是另一种归因错位。"""
    mg = _load("mutation_gate.py")
    outcome, extra = mg.classify_catch(
        exit_code=1, failed={"test_wanted[case-3]"}, collapsed=False,
        declared=["test_wanted"])
    assert outcome == "CAUGHT" and extra["attributed_to"] == ["test_wanted[case-3]"]
    outcome, _ = mg.classify_catch(
        exit_code=1, failed={"test_wanted_more"}, collapsed=False,
        declared=["test_wanted"])
    assert outcome == "MISATTRIBUTED"


def test_undeclared_entry_is_caught_but_marked_unattributed() -> None:
    """E5:存量条目没声明时照旧算 CAUGHT,但必须打上 UNDECLARED 标 ——
    报表靠它列诚实清单。'还没声明'与'声明并验证过'不许长一个样。"""
    mg = _load("mutation_gate.py")
    outcome, extra = mg.classify_catch(
        exit_code=1, failed={"test_whatever"}, collapsed=False, declared=None)
    assert outcome == "CAUGHT"
    assert extra["attribution"] == "UNDECLARED"


def test_collection_collapse_is_visible_not_misattributed() -> None:
    """E6:整文件收集期崩溃(import 都进不去)时声明的判断没法上场 ——
    这不是归因错位,是全场阵亡。单独打 COLLAPSE 标,报表单列。"""
    mg = _load("mutation_gate.py")
    outcome, extra = mg.classify_catch(
        exit_code=2, failed={"test_bench_records"}, collapsed=True,
        declared=["test_the_judge_under_exam"])
    assert outcome == "CAUGHT"
    assert extra["attribution"] == "COLLAPSE"


def test_red_exit_with_no_parsed_nodes_is_gate_plumbing_not_caught() -> None:
    """E7:pytest 退出码红、junitxml 却解析不出任何失败节点 —— 那是闸门
    自己的管道坏了(xml 没写出来/格式变了),冒充 CAUGHT 等于把测量仪
    故障记成测到了东西。"""
    mg = _load("mutation_gate.py")
    outcome, _ = mg.classify_catch(
        exit_code=1, failed=set(), collapsed=False, declared=["test_x"])
    assert outcome == "GATE_PLUMBING"


# ---------------------------------------------------------------- 归因金丝雀

def test_attribution_canary_verdict_gates_the_run() -> None:
    """E8:C1 结局恰为 MISATTRIBUTED 才放行;其余任何结局都要给出自宣
    无效的理由 —— 抓不出摆好的归因错位,就没资格给 156 条发归因结论。"""
    mg = _load("mutation_gate.py")
    assert mg.attribution_canary_verdict("MISATTRIBUTED") is None
    for wrong in ("CAUGHT", "ESCAPED", "GATE_PLUMBING", "STALE"):
        reason = mg.attribution_canary_verdict(wrong)
        assert reason, f"结局 {wrong} 必须给出自宣无效的理由"


def test_attribution_canary_entry_reuses_c0_and_names_an_impossible_judge() -> None:
    """C1 的构造必须保证它唯一可能的健康结局就是 MISATTRIBUTED:
    变异体复用 C0(已被隔离金丝雀证明必红),声明的判断在 catcher 文件里
    根本不存在(永不可能红)。两条合起来 = 红∩声明恒为空。"""
    mg = _load("mutation_gate.py")
    c0, c1 = mg.CANARY, mg.ATTRIBUTION_CANARY
    assert (c1["file"], c1["old"], c1["new"]) == (c0["file"], c0["old"], c0["new"])
    declared = c1["expected_catcher"]
    assert declared, "C1 必须有声明,否则走不到归因分支"
    for catcher in c1["catchers"]:
        text = (REPO / catcher).read_text(encoding="utf-8")
        for name in declared:
            assert f"def {name}(" not in text, (
                f"C1 声明的 {name} 真实存在于 {catcher} —— 金丝雀失去'必然错位'的构造")


# ---------------------------------------------------------------- 报表派生

def test_report_lists_are_derived_from_results_not_freeform() -> None:
    """misattributed / unattributed / collapsed 三张清单与 attributed 计数
    必须从逐条结果推导 —— 手写汇总正是'散文说不算、代码算了'的入口。"""
    mg = _load("mutation_gate.py")
    results = [
        {"id": "Ma", "outcome": "CAUGHT", "attribution": "DECLARED"},
        {"id": "Mb", "outcome": "CAUGHT", "attribution": "UNDECLARED"},
        {"id": "Mc", "outcome": "MISATTRIBUTED"},
        {"id": "Md", "outcome": "CAUGHT", "attribution": "COLLAPSE"},
        {"id": "Me", "outcome": "ESCAPED"},
    ]
    report = mg.build_report("f" * 40, results, wall_seconds=1.0, mutations_total=5)
    assert report["misattributed"] == ["Mc"]
    assert report["unattributed"] == ["Mb"]
    assert report["collapsed"] == ["Md"]
    assert report["attributed"] == 1
    assert report["escaped"] == ["Me"]
    assert report["caught"] == 3          # CAUGHT 的三种归因形态都算捕获
    assert report["capture_rate"] == "3/5"


# ---------------------------------------------------------------- 登记簿卫生

def test_registry_declarations_are_bare_names_of_real_tests() -> None:
    """声明必须是**裸函数名**且真实存在于该条目的 catcher 文件里 ——
    写错名字的声明会把条目钉进永恒的 MISATTRIBUTED(M58a 的病:一条
    永不可满足的判据,长得跟'还没到时候'一模一样)。这里在静态层先拦。"""
    mg = _load("mutation_gate.py")
    problems: list[str] = []
    for m in mg.MUTATIONS:
        declared = m.get("expected_catcher")
        if declared is None:
            continue
        if not declared:
            problems.append(f"{m['id']}: expected_catcher 为空 —— 要么声明要么别写")
            continue
        texts = [(c, (REPO / c).read_text(encoding="utf-8")) for c in m["catchers"]]
        for name in declared:
            if "::" in name or "/" in name or name.endswith(".py"):
                problems.append(f"{m['id']}: {name!r} 不是裸函数名")
                continue
            if not any(f"def {name}(" in t for _, t in texts):
                problems.append(
                    f"{m['id']}: 声明的 {name} 在 catchers {m['catchers']} 里不存在")
    assert not problems, problems
