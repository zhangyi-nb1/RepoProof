"""公开合同测试 — agent 可运行自测(由用户样例确定性编译;验收强度=用户样例级)"""
from user_capability import run


def test_example_1():
    out = str(run('I ❤️ Python'))
    assert out == 'I :red_heart: Python', f"期望 'I :red_heart: Python',实际: {out[:200]}"


def test_example_2():
    out = str(run('会议 👍 顺利'))
    assert out == '会议 :thumbs_up: 顺利', f"期望 '会议 :thumbs_up: 顺利',实际: {out[:200]}"


def test_example_3():
    out = str(run('no emoji here'))
    assert out == 'no emoji here', f"期望 'no emoji here',实际: {out[:200]}"


def test_example_4():
    out = str(run('🚀🚀 launch'))
    assert out == ':rocket::rocket: launch', f"期望 ':rocket::rocket: launch',实际: {out[:200]}"


def test_example_5():
    out = str(run('混合 text 🎉 done'))
    assert out == '混合 text :party_popper: done', f"期望 '混合 text :party_popper: done',实际: {out[:200]}"

