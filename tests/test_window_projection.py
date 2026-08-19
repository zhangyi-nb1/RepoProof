"""S2' 滑动窗口投影的钉死(EXECUTOR-UPGRADE-PLAN §3-S2')。

S2 原设计(折叠"重复项")实测判别力为 0 —— 基线六发里重复命令 0 条。
S2' 换靶子:折的是**旧的读取型结果**,这是有损投影,故判据全部重写。

**冻结判据**(先写判据与反例;措辞此后不改):

- W1 **只折读取型**:只有 `sed/cat/head/tail/grep/rg/ls/find/wc/nl/awk/
  git diff|show|log|status` 这类**读取**命令的结果可折。执行型
  (`pytest`/`pip install`/`python -m`/`make`/`npm`)**一律不折**。
  反例:折掉唯一一次 pytest 失败输出 → 模型失去修复依据,这正是"token 降
  但失败增"的产生机制;而且重跑 pytest 要 95 秒(宿主套件实测),代价与
  重跑一次 `sed -n` 完全不是一回事。
  依据(基线六发实测):工具正文 1,092,488 字符里读取型占 **70%**、
  执行型 25% —— 只折读取型仍拿得到绝大部分收益。

- W2 **窗口保底**:最近 `WINDOW` 条读取型结果的正文**原样保留**。
  反例:窗口太小 → 模型看不到它刚读过的代码,只能再读一遍,省下的 token
  被多出来的命令吃回去,还多花一轮。

- W3 **最后一次永不折**:任何命令的最近一次结果都不折(与 S2 的 D3 同源)。

- W4 **存根必须可重跑**:存根带被折消息序号**与原命令**。读取型命令重跑
  必然拿到内容(文件若已变,拿到的是当前版本 —— 那正是模型需要的)。
  反例:存根只说"已折叠"不给命令 = 丢了还不告诉你怎么找回。

- W5 **只动模型视图,不动历史**:入参逐字节不变(与 S2 的 D1 同源)。
  agent 历史与 trace 是证据,投影只服务当次请求。

- W6 **有损性必须显式**:manifest 要标 `lossy: true` 并给出折叠条数与
  省下字符。反例:把有损投影混在"确定性 prune"里不做区分 —— 后来者会
  以为它和 S2 一样零风险,在批报里少写一条诚实边界。

**窗口取值的依据**(基线六发实测,读取型正文 764,319 字符):

    保留最近 4 条 → 折 108 条,省 82%
    保留最近 6 条 → 折  88 条,省 71%
    保留最近 8 条 → 折  68 条,省 55%      ← 默认值,留足工作集
    保留最近 12 条 → 折 33 条,省 30%

默认取 8:省 55% 已足够验证方向,同时给模型留 8 条读取结果的工作集。
**这是实验起点不是最优值**,消融批可调;调了要记进预注册。
"""

from __future__ import annotations

import copy

from repoproof.agents.context_projector import WINDOW_READS, project_window


def _tool(content: str, cmd: str) -> dict:
    return {"role": "tool", "content": content, "extra": {"command": cmd}}


def _asst(cmd: str) -> dict:
    return {"role": "assistant", "content": None,
            "extra": {"actions": [{"command": cmd}]}}


def _hist(*pairs: tuple[str, str]) -> list[dict]:
    msgs: list[dict] = [{"role": "system", "content": "sys"},
                        {"role": "user", "content": "task"}]
    for cmd, out in pairs:
        msgs += [_asst(cmd), _tool(out, cmd)]
    return msgs


def _reads(n: int, size: int = 3000) -> list[tuple[str, str]]:
    return [(f"sed -n '1,50p' f{i}.py", f"body{i}" + "x" * size) for i in range(n)]


def _folded(out: list[dict]) -> list[dict]:
    return [m for m in out if m.get("extra", {}).get("projection") == "folded"]


def test_exec_type_results_are_never_folded():
    """W1:pytest / pip 的结果一律不折 —— 重跑要 95 秒,且它是修复依据。"""
    msgs = _hist(*_reads(WINDOW_READS + 3),
                 (".venv/bin/python -m pytest public_tests/ -q", "FAILED " + "y" * 9000))

    out, mf = project_window(msgs)
    bodies = [m["content"] for m in out if m["role"] == "tool"]

    assert bodies[-1].startswith("FAILED"), "pytest 结果被折了 —— 模型失去修复依据"
    assert all(f["command"].startswith("sed") for f in mf["folded"]), (
        f"折到了非读取型命令:{[f['command'] for f in mf['folded']]}")


def test_read_then_exec_chain_is_never_folded():
    """W1 的**要害情形**:`sed -n … && pytest` 这种链。

    首段是读取型,白名单会放行 —— 只有执行型否决拦得住它。而这正是真实
    数据里最常见的形态(基线六发里大量 `sed -n … && .venv/bin/python -m
    pytest`)。链的输出里含着测试结果,折了就是折修复依据。

    2026-08-14 变异闸门 M46a 逃逸后补:原先的两条 W1 用例只测独立执行型
    命令,而那种情形**光靠读取型白名单就排除了**,执行型否决从未被考到 ——
    钉死测的是代码顺带处理的情况,不是判据真正管的情况。"""
    # 链必须放在**窗口之外**(最前面):放在末尾会落进窗口保底,
    # 于是"不折"是窗口给的、不是执行型否决给的 —— 用例就考不到 W1。
    chain = "sed -n '1,50p' a.py && .venv/bin/python -m pytest public_tests/ -q"
    msgs = _hist((chain, "FAILED " + "y" * 9000), *_reads(WINDOW_READS + 3))

    out, mf = project_window(msgs)
    bodies = [m["content"] for m in out if m["role"] == "tool"]

    assert bodies[0].startswith("FAILED"), (
        "窗口外、读取型开头的链被折了 —— 测试结果丢了(执行型否决失效)")
    assert all("pytest" not in f["command"] for f in mf["folded"]), (
        f"折到了含 pytest 的链:{[f['command'] for f in mf['folded']]}")


def test_pip_install_results_are_never_folded():
    """W1 的另一面:pip 安装输出同样不折(依赖冲突的证据在里面)。"""
    msgs = _hist((".venv/bin/pip install foo", "ERROR: conflict " + "z" * 9000),
                 *_reads(WINDOW_READS + 3))

    out, _ = project_window(msgs)
    bodies = [m["content"] for m in out if m["role"] == "tool"]

    assert bodies[0].startswith("ERROR: conflict"), "pip 输出被折了"


def test_window_keeps_the_most_recent_reads_verbatim():
    """W2:最近 WINDOW 条读取型结果原样保留。"""
    msgs = _hist(*_reads(WINDOW_READS + 5))

    out, _ = project_window(msgs)
    tools = [m for m in out if m["role"] == "tool"]

    for m in tools[-WINDOW_READS:]:
        assert m.get("extra", {}).get("projection") != "folded", "窗口内的结果被折了"


def test_older_reads_beyond_the_window_are_folded():
    """W2 的另一面:超出窗口的旧读取结果必须被折 —— 否则机制没生效。"""
    msgs = _hist(*_reads(WINDOW_READS + 5))

    out, mf = project_window(msgs)

    assert len(_folded(out)) == 5, f"应折 5 条,实折 {len(_folded(out))}"
    assert mf["saved_chars"] > 0


def test_nothing_folded_when_within_the_window():
    """不到窗口就一条不折 —— 不给短会话平白加噪。"""
    msgs = _hist(*_reads(WINDOW_READS))

    out, mf = project_window(msgs)

    assert not _folded(out) and mf["folded_messages"] == 0


def test_stub_carries_the_command_for_rerun():
    """W4:存根带序号与原命令,读取型重跑必然拿到内容。"""
    msgs = _hist(*_reads(WINDOW_READS + 1))

    out, _ = project_window(msgs)
    stub = _folded(out)[0]
    idx = [i for i, m in enumerate(out)
           if m.get("extra", {}).get("projection") == "folded"][0]

    assert f"#{idx}" in stub["content"], "存根缺被折消息序号"
    assert "sed -n" in stub["content"], "存根缺原命令 —— 模型不知道重跑什么"


def test_projection_does_not_mutate_history():
    """W5:入参逐字节不变 —— agent 历史与 trace 是证据。"""
    msgs = _hist(*_reads(WINDOW_READS + 3))
    before = copy.deepcopy(msgs)

    project_window(msgs)

    assert msgs == before, "原地改了入参,证据被投影污染"


def test_manifest_declares_lossiness():
    """W6:有损性必须显式,不能混在"确定性 prune"里。"""
    msgs = _hist(*_reads(WINDOW_READS + 2))

    _, mf = project_window(msgs)

    assert mf["lossy"] is True, "有损投影没标 lossy —— 后来者会当成零风险"
    # 版号钉死用字面量:分类器语义一变必须换号(v1.1 = cd 剥离 + pwd 入集,
    # 2026-08-20);这里若只 assert 等于常量,版号漂移永远考不出来。
    assert mf["policy"] == "window-v1.1"
    assert mf["window"] == WINDOW_READS


def test_system_and_task_messages_are_never_touched():
    """固定前缀不动:任务契约是最不能省的部分。"""
    msgs = _hist(*_reads(WINDOW_READS + 3))

    out, _ = project_window(msgs)

    assert out[0] == msgs[0] and out[1] == msgs[1]


def test_determinism():
    """同输入投两次结果完全相同。"""
    msgs = _hist(*_reads(WINDOW_READS + 4))

    assert project_window(msgs)[0] == project_window(msgs)[0]


# ---------------------------------------------------------------- v1.1 判据
# E1-DSH 代 2 离线重放(2026-08-20):deepseek-v4-flash 六发里两发零激活
# (025342/060627)—— flash 每条命令都带 `cd /绝对路径 &&/;` 导航前缀,
# 链首段是 cd,v1 白名单永不命中。与批 14 gpt-5.6 链式零激活同构:
# 分类器覆盖缺口。v1.1 只修分类(剥 cd 前缀 + pwd 入集),折叠规则不动。


def test_cd_prefixed_read_chains_are_folded():
    """v1.1:`cd <路径> && sed …` 是读取 —— cd 只是带路,零输出。

    反例(v1 实测):flash 两发 -0%,离线重放 v1.1 后 -18.8%/-24.8%。"""
    ws = "/tmp/sessions/rp-host-agent-x/host"
    msgs = _hist(*[(f"cd {ws} && sed -n '1,50p' f{i}.py", "b" + "x" * 3000)
                   for i in range(WINDOW_READS + 3)])

    out, mf = project_window(msgs)

    assert len(_folded(out)) == 3, (
        f"cd 前缀的读取链没被折(应折 3,实折 {len(_folded(out))})—— "
        "v1 零激活缺口复发")
    assert all(f["command"].startswith("cd ") for f in mf["folded"])


def test_cd_prefixed_exec_chains_are_never_folded():
    """v1.1 的安全边界:cd 剥离不放行执行型 —— 否决作用于整条原始命令。"""
    chain = "cd /tmp/ws/host && .venv/bin/python -m pytest public_tests/ -q"
    msgs = _hist((chain, "FAILED " + "y" * 9000), *_reads(WINDOW_READS + 3))

    out, mf = project_window(msgs)
    bodies = [m["content"] for m in out if m["role"] == "tool"]

    assert bodies[0].startswith("FAILED"), (
        "cd 前缀的 pytest 链被折了 —— 剥离把执行型否决也剥掉了")
    assert all("pytest" not in f["command"] for f in mf["folded"])


def test_fallback_cd_and_semicolon_chains_are_read(  # flash 实录开局形态
):
    """v1.1:`cd X 2>/dev/null || cd ~; pwd; ls -la` 也算读取(pwd 入集)。"""
    msgs = _hist(*[(f"cd /w{i} 2>/dev/null || cd ~; pwd; ls -la", "L" + "x" * 3000)
                   for i in range(WINDOW_READS + 2)])

    out, _ = project_window(msgs)

    assert len(_folded(out)) == 2, "兜底 cd + 分号链的读取没被识别"


def test_quoted_cd_arguments_are_not_stripped():
    """引号一出现就不剥:带引号的 cd 参数超出机械判断的把握,宁可不折。"""
    msgs = _hist(*[(f'cd "/some dir/x{i}" && rm -rf build', "o" + "x" * 3000)
                   for i in range(WINDOW_READS + 3)])

    out, _ = project_window(msgs)

    assert not _folded(out), "带引号的 cd 段被剥了 —— 超出把握范围还在折"
