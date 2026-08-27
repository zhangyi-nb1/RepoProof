"""输出比对的**唯一判据源**(harness 判据面,不是便利函数)。

来由(LESSONS #57,2026-08-28 用户实测):同一个事实被两处判定、用了两把
尺子 —— 合同自己的能力测试比 `_norm`(去首尾/行尾空白),fresh-input 抽查
比裸字节。金标准文件不以换行结尾、工具 stdout 带 `\\n`:工具通过了全部
能力测试,却被抽查判死并自动撤回。**比合同更严不是更严谨,是换了一把
尺子** —— 那样"通过合同"推不出"通过抽查",而人只能靠猜。

所以判据必须只有一份实现,两处共用。会话 venv 里装不了 repoproof(它只装
被测工具的依赖),因此生成的验收测试**内联本模块源码**(见
`canonical_source()`),而不是各写一份 —— 一物一名,想漂移也漂移不了。

═══════════════════════════════════════════════════════════════════
放宽的边界:**只沿合同已经声明的语义放宽,一步都不多**
═══════════════════════════════════════════════════════════════════

合同声明 `text`  → 行尾/首尾空白与 CRLF 属**呈现噪声**,不改变文本内容;
合同声明 JSON 族 → 键序与缩进属**序列化噪声**,不改变数据。

**明确不做**(每一条都会把错的判成对的,门槛就是这样被悄悄拆掉的):

- 不做大小写不敏感 —— `Navy` 与 `navy` 是不同的字符串;
- 不做数值容差 —— `128` 与 `127.9` 不是同一个值;
- 不把 `1` 与 `1.0` 视为相同 —— 用规范化 JSON 文本比较,类型差异照旧暴露;
- 不做"包含即通过" —— 少一个字段、多一个字段都必须红;
- 不做 Unicode 规范化 —— 看起来一样的字符可能真的不是一个字符;
- 合同声明 JSON 而实际输出解析不出来 → **判不符**(那是合同违约,
  不是格式噪声),不许回落到文本比较去"救"它。

人可以不精确;判据不可以。用户少打一个换行不该毁掉一个好工具,但
用户写错一个数值必须当场红。
"""

from __future__ import annotations

import inspect
import json

_JSON_ROOTS = frozenset({"json", "object", "array"})


def _normalize_text(value: str) -> str:
    """文本呈现噪声:CRLF、行尾空白、首尾空白。内容一个字符不动。"""
    unified = value.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in unified.strip().splitlines())


def _canonical_json(value: str) -> str | None:
    """→ 规范化 JSON 文本;解析不出返回 None。

    用 `sort_keys=True` 的规范文本而不是对象比较:键序/缩进被抹平,而
    `1` 与 `1.0`、`"1"` 与 `1` 仍然不同 —— 正好是"抹掉序列化噪声、保留
    一切语义"的那条线。
    """
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def compare_output(actual: str, expected: str, *, root_type: str = "text") -> tuple[bool, str]:
    """→ (是否相符, 判据模式)。模式取值:exact / text / json / json_lines。

    `root_type` 来自**冻结合同**的输出声明 —— 判据跟着合同走,不跟着
    调用方的心情走。
    """
    if actual == expected:
        return True, "exact"

    kind = (root_type or "text").strip().lower()
    if kind in _JSON_ROOTS:
        a, e = _canonical_json(actual), _canonical_json(expected)
        # 期望值解析不出 → 说明人写的期望本身不满足合同,判不符并如实说明;
        # 实际输出解析不出 → 合同违约。两种都不许回落到文本比较去救。
        return (a is not None and e is not None and a == e), "json"

    if kind == "json_lines":
        a_lines = [_canonical_json(x) for x in _normalize_text(actual).splitlines()]
        e_lines = [_canonical_json(x) for x in _normalize_text(expected).splitlines()]
        ok = (a_lines == e_lines and all(x is not None for x in a_lines)
              and bool(a_lines))
        return ok, "json_lines"

    return _normalize_text(actual) == _normalize_text(expected), "text"


def _strip_docstring(src: str) -> str:
    """去掉函数体里的 docstring —— 生成件**不能带三引号**。

    装配器用 `split('"'*3)[2]` 之类的三引号计数来切公开段/held 段
    (tool_assembler),内联源码里多一个 docstring 就会把切分点顶掉,
    表现为莫名其妙的 `ValueError: substring not found`(2026-08-28 自测
    当场撞出)。生成件的可读性由调用处的注释承担,不靠内联 docstring。
    """
    out, skipping = [], False
    for line in src.splitlines():
        stripped = line.strip()
        if skipping:
            if stripped.endswith('"""') and stripped != '"""' or stripped == '"""':
                skipping = False
            continue
        if stripped.startswith('"""'):
            # 单行 docstring 直接丢;多行的进入跳过态
            if not (stripped.endswith('"""') and len(stripped) > 3):
                skipping = True
            continue
        out.append(line)
    return "\n".join(out)


def canonical_source() -> str:
    """本模块可内联的源码 —— 给生成的验收测试用(会话里装不了 repoproof)。

    内联的是**同一份源码**,不是"照着写一份":照着写的那份迟早跟本体分家,
    而分家的两把尺子正是 LESSONS #57 的病根。
    """
    parts = [
        "import json as _json",
        f"_JSON_ROOTS = {sorted(_JSON_ROOTS)!r}",
        inspect.getsource(_normalize_text),
        inspect.getsource(_canonical_json).replace("json.loads", "_json.loads")
                                          .replace("json.dumps", "_json.dumps"),
        inspect.getsource(compare_output),
    ]
    return "\n\n".join(_strip_docstring(p).strip("\n") for p in parts) + "\n"
