"""验收(公开样例)(由用户样例确定性编译;验收强度=用户样例级)"""
from user_capability import run


def test_example_1():
    out = str(run('1'))
    assert out == '1 Byte', f"期望 '1 Byte',实际: {out[:200]}"


def test_example_2():
    out = str(run('300'))
    assert out == '300 Bytes', f"期望 '300 Bytes',实际: {out[:200]}"


def test_example_3():
    out = str(run('999'))
    assert out == '999 Bytes', f"期望 '999 Bytes',实际: {out[:200]}"


def test_example_4():
    out = str(run('1000'))
    assert out == '1.0 kB', f"期望 '1.0 kB',实际: {out[:200]}"


def test_example_5():
    out = str(run('5500'))
    assert out == '5.5 kB', f"期望 '5.5 kB',实际: {out[:200]}"


def test_example_6():
    out = str(run('1000000'))
    assert out == '1.0 MB', f"期望 '1.0 MB',实际: {out[:200]}"


from user_capability import run


def test_held_example_1():
    out = str(run('2500000'))
    assert out == '2.5 MB', f"期望 '2.5 MB',实际: {out[:200]}"


def test_held_example_2():
    out = str(run('1000000000'))
    assert out == '1.0 GB', f"期望 '1.0 GB',实际: {out[:200]}"



def test_deterministic():
    v = '1'
    assert str(run(v)) == str(run(v))
