"""Runtime Profile —— 上游**以什么拓扑**交到任务手上(A1)。

这不是"换个实现细节",而是**换了一道题**。同一个契约在两种 profile 下问的
不是同一件事:

    rt-inprocess-v1   上游装进 agent 的 venv,由它自己 import 自己调。
                      "有没有用上游"只能从足迹推断 —— 而足迹上的每一样
                      东西(模块名、版本号、工件里的字样)SUT 都能自己供
                      (LESSONS #43 坑五;T3 批 13 实证)。
    rt-sidecar-v1     上游由 harness 持有并运行,agent 只能写 Adapter 经
                      RPC 请它执行。"有没有用上游"变成**执行拓扑约束**:
                      它要用就得来敲门,每次敲门 harness 都在自己的台账上
                      记一张签名回执。

所以两种 profile 的发次**永不互比**,和 E0/E1 一个道理(§2 规则 1)。
`task_shape` 变了,题就变了;把两边的通过数放进同一个分母,等于把"开卷"
和"闭卷"的成绩加起来平均。

**profile 生命周期**沿用 `docs/RUNTIME-MODES.md` 的那套:
experimental → candidate → qualified → default → deprecated。
新 profile 一律从 `experimental` 起步 —— 它得先证明自己不误杀诚实实现
(假阳侧正控)、也确实挡得住洗白(负控矩阵),才谈得上往上走。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from repoproof.execution.upstream_sidecar import UpstreamSpec

Lifecycle = Literal["experimental", "candidate", "qualified", "default", "deprecated"]
Topology = Literal["in_process", "sidecar"]


@dataclass(frozen=True)
class RuntimeProfile:
    """一种上游交付拓扑。

    `id` 会原样进回执的 `runtime.profile_id` 与台账字段,所以它是**对外
    承诺的名字**,改名等于换代 —— 想改行为就发新 id,别就地改语义。
    """

    id: str
    topology: Topology
    lifecycle: Lifecycle
    summary: str
    # sidecar 拓扑才有:上游能力面与契约要求的符号集
    upstream: UpstreamSpec | None = None
    required_symbols: frozenset[str] = field(default_factory=frozenset)
    default_symbol: str = ""

    def __post_init__(self) -> None:
        if self.topology == "sidecar":
            if self.upstream is None:
                raise ValueError(f"{self.id}:sidecar 拓扑必须声明 UpstreamSpec —— "
                                 "不声明就没有可执行的上游,回执无从谈起")
            if not self.required_symbols:
                raise ValueError(f"{self.id}:sidecar 拓扑必须声明 required_symbols —— "
                                 "U2 判的就是'调的是不是契约要的那项能力',"
                                 "要求集为空等于这道判据不存在")
            unknown = self.required_symbols - set(self.upstream.dispatch)
            if unknown:
                raise ValueError(f"{self.id}:要求的符号在上游能力面里没有实现:"
                                 f"{sorted(unknown)}(要求一件做不到的事 = 判据成墙)")
        elif self.upstream is not None:
            raise ValueError(f"{self.id}:in_process 拓扑不该带 UpstreamSpec —— "
                             "上游在 agent 自己的环境里,harness 不执行它")


# ---------------------------------------------------------------- 登记表
#
# **默认 profile 是 in-process**,与既有全部发次一致。新增 sidecar 能力不得
# 改变任何既有任务的行为 —— 这是"任务包在消融期一字不动"(§2 规则 5)的
# 延伸:加一条新路,不动老路。
IN_PROCESS_V1 = RuntimeProfile(
    id="rt-inprocess-v1",
    topology="in_process",
    lifecycle="default",
    summary="上游装进 agent 的 venv,由它自己 import;'是否采用'只能从足迹推断",
)

_REGISTRY: dict[str, RuntimeProfile] = {IN_PROCESS_V1.id: IN_PROCESS_V1}


def register_profile(p: RuntimeProfile) -> RuntimeProfile:
    if p.id in _REGISTRY and _REGISTRY[p.id] != p:
        raise ValueError(f"profile id 已被占用且内容不同:{p.id}。"
                         "id 是对外承诺的名字,改行为请发新 id,别就地改语义")
    _REGISTRY[p.id] = p
    return p


def profile(pid: str) -> RuntimeProfile:
    if pid not in _REGISTRY:
        raise ValueError(f"未登记的 runtime profile:{pid};已登记 {sorted(_REGISTRY)}")
    return _REGISTRY[pid]


def known_profiles() -> dict[str, RuntimeProfile]:
    return dict(_REGISTRY)


def profile_of_contract(contract) -> RuntimeProfile:
    """契约声明的 profile;没声明就是 in-process。

    **缺省必须是老行为**。这里和"缺清单显式失败"不是一回事 —— 那边缺的是
    任务自己该给的事实,这边缺的是一个新增能力的开关,缺省关掉才不会把既有
    发次悄悄换成另一道题。
    """
    pid = getattr(contract, "runtime_profile", "") or IN_PROCESS_V1.id
    return profile(pid)


def generation_suffix(p: RuntimeProfile) -> str:
    """执行代际的 profile 分量 —— 拼进 `exec_generation`。

    sidecar 改变执行拓扑 = 改变被测系统,必须体现在代际标签上,否则两种
    profile 的发次会在分析时被悄悄合池。"""
    return "" if p.topology == "in_process" else f"+{p.id}"
