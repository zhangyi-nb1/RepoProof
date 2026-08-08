"""验收(公开样例)(由用户样例确定性编译;验收强度=用户样例级)"""
from user_capability import run


def test_example_1():
    out = str(run('person'))
    assert out == 'people', f"期望 'people',实际: {out[:200]}"


def test_example_2():
    out = str(run('child'))
    assert out == 'children', f"期望 'children',实际: {out[:200]}"


def test_example_3():
    out = str(run('analysis'))
    assert out == 'analyses', f"期望 'analyses',实际: {out[:200]}"


def test_example_4():
    out = str(run('tomato'))
    assert out == 'tomatoes', f"期望 'tomatoes',实际: {out[:200]}"


def test_example_5():
    out = str(run('bus'))
    assert out == 'buses', f"期望 'buses',实际: {out[:200]}"


def test_example_6():
    out = str(run('sheep'))
    assert out == 'sheep', f"期望 'sheep',实际: {out[:200]}"


from user_capability import run


def test_held_example_1():
    out = str(run('matrix'))
    assert out == 'matrices', f"期望 'matrices',实际: {out[:200]}"


def test_held_example_2():
    out = str(run('wolf'))
    assert out == 'wolves', f"期望 'wolves',实际: {out[:200]}"



def test_deterministic():
    v = 'person'
    assert str(run(v)) == str(run(v))
