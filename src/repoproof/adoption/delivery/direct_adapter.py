"""DIRECT_WRAP · 受信模板直连适配器(RFC-013 路由的确定性快路径,Gate 3)。

定位(指导 §6 Gate 3):证明 RepoProof 会选择最低风险执行方式 —— 已有
清晰 Python callable 的仓库不调 Coding Agent,由受信模板生成 impl.py,
**在装配期写进骨架**;此后走与 AGENT_ADAPT 完全相同的合同、held-out、
provenance、import-hook、policy、clean replay 与 completion gate。零适配
diff + 全门通过 = 既有 `PASS_DIRECT` 语义自然成立,gate 零改动。

可信边界:
  - 模板只接受 `DirectAdapterSpec` 的白名单字段;不接受任意 shell 命令
    或用户模板代码;
  - adapter 必须真 import 并调用 pinned 上游(弱档 provenance 与
    import-hook min_calls 照常执法 —— 模板"重新实现能力"会被既有
    控制矩阵与回执层当场杀);
  - DIRECT_WRAP 失败不自动切 AGENT_ADAPT(owner=HARNESS/CONTRACT/
    UPSTREAM);换路线必须重新生成并确认 Capability Plan。
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, field_validator

from repoproof.adoption.planning.capability_plan import CapabilityPlanV1

_RE_LOCATOR = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")

InputMode = Literal["path", "text"]
OutputMode = Literal["text", "json"]


class DirectAdapterError(RuntimeError):
    pass


class DirectAdapterSpec(BaseModel):
    """最小机械映射:callable + 输入/输出映射 + 异常语义。全字段白名单。"""

    locator: str                       # package.module:function
    input_mode: InputMode = "text"     # path=传文件路径;text=读文本传入
    output_mode: OutputMode = "text"   # text=str(result);json=固定 serializer
    upstream_exceptions: list[str] = []  # 视为用户输入错误的上游异常名(点路径)

    @field_validator("locator")
    @classmethod
    def _valid_locator(cls, v: str) -> str:
        if not _RE_LOCATOR.match(v):
            raise ValueError(f"非法 locator:{v!r}(须为 pkg.mod:func)")
        return v

    @field_validator("upstream_exceptions")
    @classmethod
    def _valid_excs(cls, v: list[str]) -> list[str]:
        for name in v:
            if not re.match(r"^[A-Za-z_][\w.]*$", name):
                raise ValueError(f"非法异常名:{name!r}")
        return v


def derive_adapter_spec(plan: CapabilityPlanV1) -> DirectAdapterSpec:
    """从已确认的 DIRECT_WRAP 计划推导 spec(确定性,不猜)。"""
    if plan.implementation_route != "DIRECT_WRAP":
        raise DirectAdapterError(
            f"计划路线是 {plan.implementation_route},不是 DIRECT_WRAP")
    picked = [s for s in plan.detected_surfaces
              if s.kind == "python_callable" and s.confidence == "HIGH"
              and not s.exclusion_reason]
    if len(picked) != 1:
        raise DirectAdapterError(
            f"DIRECT_WRAP 需要恰一个选中 callable,实得 {len(picked)}")
    s = picked[0]
    sig = s.signature or ""
    # 输入模式:参数注解/名称含 path/file → 传路径;否则读文本传入
    head = sig.split(",")[0] if sig else ""
    input_mode: InputMode = ("path" if re.search(
        r"(?:\bPath\b|path|file)", head, re.IGNORECASE) else "text")
    return DirectAdapterSpec(locator=s.locator, input_mode=input_mode,
                             output_mode="text")


_TEMPLATE = '''"""能力位 · DIRECT_WRAP 受信模板生成(route=DIRECT_WRAP,零 Agent)。

由 CapabilityPlan(用户已确认)确定性编译;真调 pinned 上游
`{module}.{func}`;本文件不是手写代码,重新生成必逐字节一致。
"""
from pathlib import Path

import {module}


class UserInputError(ValueError):
    """输入内容级错误(格式坏/不可解析)。"""


_USER_ERRORS = ({user_errors})


def extract(input_path: Path) -> str:
    try:
        arg = {arg_expr}
    except (UnicodeDecodeError, OSError) as e:
        raise UserInputError(str(e)) from e
    try:
        result = {module}.{func}(arg)
    except _USER_ERRORS as e:
        raise UserInputError(str(e)) from e
    return {render_expr}
'''


def compile_direct_adapter(spec: DirectAdapterSpec) -> str:
    """spec → impl.py 源码。同 spec 重复编译逐字节一致(受信模板纪律)。"""
    module, func = spec.locator.split(":", 1)
    arg_expr = ("str(input_path)" if spec.input_mode == "path"
                else 'input_path.read_text(encoding="utf-8")')
    if spec.output_mode == "json":
        render_expr = ('__import__("json").dumps(result, ensure_ascii=False, '
                       "sort_keys=True, default=str)")
    else:
        render_expr = ('result if isinstance(result, str) else str(result)')
    # 上游异常映射:名字来自 spec 白名单;解析失败按内部错误兜底(exit 2),
    # 不静默吞 —— getattr 链在 import 后求值,指错名会在 S0 当场炸红。
    exc_terms = ["ValueError"]
    for name in spec.upstream_exceptions:
        if "." in name:
            first, rest = name.split(".", 1)
            base = module if first == module.split(".")[0] else first
            exc_terms.append(
                "getattr(__import__({m!r}, fromlist=['_']), {r!r}, ValueError)"
                .format(m=base, r=rest.split(".")[-1]))
        else:
            exc_terms.append(f"getattr({module}, {name!r}, ValueError)")
    user_errors = ", ".join(dict.fromkeys(exc_terms))
    if "," not in user_errors:
        user_errors += ","
    return _TEMPLATE.format(module=module, func=func, arg_expr=arg_expr,
                            render_expr=render_expr, user_errors=user_errors)
