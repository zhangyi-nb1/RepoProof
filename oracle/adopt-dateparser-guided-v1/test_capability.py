"""验收(公开样例)(由用户样例确定性编译;验收强度=用户样例级)"""
from user_capability import run


def test_example_1():
    out = str(run('March 5, 2020'))
    assert out == '2020-03-05', f"期望 '2020-03-05',实际: {out[:200]}"


def test_example_2():
    out = str(run('20 Dec 2019'))
    assert out == '2019-12-20', f"期望 '2019-12-20',实际: {out[:200]}"


def test_example_3():
    out = str(run('05/03/2020'))
    assert out == '2020-05-03', f"期望 '2020-05-03',实际: {out[:200]}"


def test_example_4():
    out = str(run('31/12/2021'))
    assert out == '2021-12-31', f"期望 '2021-12-31',实际: {out[:200]}"


def test_example_5():
    out = str(run('December 20th, 2019'))
    assert out == '2019-12-20', f"期望 '2019-12-20',实际: {out[:200]}"


def test_example_6():
    out = str(run('2020年3月5日'))
    assert out == '2020-03-05', f"期望 '2020-03-05',实际: {out[:200]}"


def test_example_7():
    out = str(run('5 mars 2020'))
    assert out == '2020-03-05', f"期望 '2020-03-05',实际: {out[:200]}"


def test_example_8():
    out = str(run('2 января 2018'))
    assert out == '2018-01-02', f"期望 '2018-01-02',实际: {out[:200]}"


from user_capability import run


def test_held_example_1():
    out = str(run('le 5 janvier 2021'))
    assert out == '2021-01-05', f"期望 '2021-01-05',实际: {out[:200]}"


def test_held_example_2():
    out = str(run('hello world'))
    assert out == 'ERROR', f"期望 'ERROR',实际: {out[:200]}"



def test_deterministic():
    v = 'March 5, 2020'
    assert str(run(v)) == str(run(v))
