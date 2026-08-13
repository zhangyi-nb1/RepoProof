"""LESSONS #40(量具由被测者提供)— fixtures 与 public_tests 同级受保护。

实录反例(order-20/21,两发 **PASS_ADAPTED**,至今计在 T2 闸门里):
公开套件 `test_public_research.py:24` 写着
`from fake_llm_server import start`,**隐藏 oracle 也 import 同一个模块**
(`sys.path.insert(0, HOST/"fixtures")` 后 `from fake_llm_server import
start`)——它就是这两套验收的假模型量具。而当时的会话装配根本没注入任务包
的 fixtures(注入是后来的 `5188b85` 才加的,晚于这两发),于是 agent 自己
写了一个 `fixtures/fake_llm_server.py` 让公开测试跑得起来,**隐藏 oracle
随后拿被测者写的量具去量被测者**。

修好注入之后洞并没有关上:fixtures 落在 agent 可写树里,而
`public_tests/` 有树哈希对账(`PUBLIC_TESTS_TAMPERED`)、`../upstream`
有树哈希对账,**唯独 fixtures 没有任何对账,提示里也从没说过不许改**。
历史上 19 轮真的改过它。

冻结判据:
  H8-a 公开验收面 = `public_tests/` + `fixtures/`,改动任一都算篡改;
  H8-b 合并指纹覆盖两棵树,且键名带目录前缀(免得两树同名文件互相遮蔽);
  H8-c 闸门要杀的先教(#33):提示的 HARD RULES 必须点名 fixtures。
边界(§39):不放宽任何判据、不减少任何需求 —— fixtures 本就是"可见可用"
的量具,不是可改的实现面;需要不同的假模型行为,走 scope-change 请求。
"""

from __future__ import annotations

# 新符号刻意不在模块级导入(LESSONS #34:红的粒度必须与钉死的粒度一致)。


def test_fixtures_count_as_public_surface_tampering() -> None:
    """H8-a:改 fixtures 与改 public_tests 同罪(反例:此前只认后者)。"""
    from repoproof.runner.host_guided import tampered_public_surface

    changed = ["rag_api.py", "fixtures/fake_llm_server.py",
               "public_tests/test_public_research.py", "research_jobs.py"]
    assert tampered_public_surface(changed) == [
        "fixtures/fake_llm_server.py", "public_tests/test_public_research.py"]
    assert tampered_public_surface(["rag_api.py", "fixtures_helper.py"]) == [], (
        "只认目录前缀,不许把 fixtures_helper.py 这类同前缀文件误伤")


def test_public_surface_fingerprint_covers_both_trees(tmp_path) -> None:
    """H8-b:合并指纹两棵树都在,键名带前缀;改 fixtures 必须被对账查出。"""
    from repoproof.harness.oracle_guard import trees_equal
    from repoproof.runner.host_guided import hash_public_surface

    host = tmp_path / "host"
    (host / "public_tests").mkdir(parents=True)
    (host / "fixtures").mkdir()
    (host / "public_tests" / "test_x.py").write_text("assert 1\n")
    (host / "fixtures" / "fake_llm_server.py").write_text("def start(): ...\n")

    before = hash_public_surface(host)
    assert set(before) == {"public_tests/test_x.py", "fixtures/fake_llm_server.py"}

    (host / "fixtures" / "fake_llm_server.py").write_text("def start(): return 'pwned'\n")
    ok, diff = trees_equal(before, hash_public_surface(host))
    assert not ok and diff == ["fixtures/fake_llm_server.py"]


def test_missing_fixtures_dir_is_not_an_error(tmp_path) -> None:
    """并非每个任务包都有 fixtures(T1 就没有)——缺目录只是少几个键。"""
    from repoproof.runner.host_guided import hash_public_surface

    host = tmp_path / "host"
    (host / "public_tests").mkdir(parents=True)
    (host / "public_tests" / "t.py").write_text("x = 1\n")
    assert set(hash_public_surface(host)) == {"public_tests/t.py"}


def test_both_call_sites_use_the_merged_surface() -> None:
    """接线钉死:两个判定点都必须用合并指纹,而不是只哈希 public_tests。

    `run()` 里的这两处只有跑完整 run 才走得到,单测够不着;沿用本仓既有
    做法(见 test_host_guided 的探针接线钉死)读源码守住接线本身。"""
    import inspect

    from repoproof.runner import host_guided

    src = inspect.getsource(host_guided)
    assert "public_before = hash_public_surface(" in src, "开跑前的基线指纹"
    assert "public_before, hash_public_surface(" in src, "终局对账"
    assert "tampered = tampered_public_surface(" in src, "轮内检测"
    assert 'hash_tree(s.root / "host" / "public_tests")' not in src, (
        "不得再有只覆盖 public_tests 的旧对账")


def test_prompt_forbids_touching_fixtures() -> None:
    """H8-c(#33 闸门要杀的先教):终局会以篡改击杀,提示就必须先说。

    反例:此前 HARD RULES 只写 public_tests 与 upstream,fixtures 只字未提
    —— agent 改了 19 轮,一次也没被告知那是量具。"""
    from repoproof.runner.host_guided import HostContract, build_host_prompt

    contract, _ = HostContract.load(
        __import__("pathlib").Path("benchmarks/v2/tasks/t2_open_deep_research_v4/contract.yaml"))
    prompt = build_host_prompt(contract, wheel_note="wheelhouse-test")
    rules = prompt.split("HARD RULES", 1)[1].split("BUDGETS", 1)[0]
    assert "./fixtures" in rules, "HARD RULES 必须点名 fixtures"
    assert "./public_tests" in rules and "../upstream" in rules, "旧两条不得丢"
