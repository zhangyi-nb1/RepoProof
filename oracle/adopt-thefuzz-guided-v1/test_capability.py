"""验收(公开样例)(由用户样例确定性编译;验收强度=用户样例级)"""
from user_capability import run


def test_example_1():
    out = str(run('周合'))
    assert '周会纪要' in out, f"期望包含 '周会纪要',实际: {out[:200]}"


def test_example_2():
    out = str(run('读书'))
    assert '测试驱动' in out, f"期望包含 '测试驱动',实际: {out[:200]}"


def test_example_3():
    out = str(run('咖啡'))
    assert '购物清单' in out, f"期望包含 '购物清单',实际: {out[:200]}"


from user_capability import run


def test_held_example_1():
    out = str(run('kafei'))
    assert '购物清单' in out, f"期望包含 '购物清单',实际: {out[:200]}"



def test_deterministic():
    v = '周合'
    assert str(run(v)) == str(run(v))
