"""Upstream Provenance 最小版(Phase 0 ⑤,RFC-009 §三.4,源方案 §22 思想)。

底线:适配改动中必须存在对目标库的**真实 import**——零 import 即
语义替代嫌疑(UPSTREAM_CAPABILITY_REIMPLEMENTED,历史实例:bm25 335
行手写重实现)。本最小版只钉这条底线;T1/T2 冻结版按任务追加
实例化/调用级检查(如 Enforcer()/FastApiMCP() 真实调用)。

已知边界(如实):基于行首正则,docstring 内行首的 `import x` 会
误计——最小版接受该噪声(它只会放宽而不会收紧"零 import 报警",
不产生假阴性遮蔽)。
"""

from __future__ import annotations

import re
from pathlib import Path

FAILURE_TYPE = "UPSTREAM_CAPABILITY_REIMPLEMENTED"


def _import_pattern(module: str) -> re.Pattern[str]:
    m = re.escape(module)
    return re.compile(rf"^\s*(?:import\s+{m}(?:[.\s,]|$)|from\s+{m}(?:[.\s])\s*)")


def check_upstream_provenance(
    root: str | Path,
    changed_files: list[str],
    import_module: str,
    *,
    max_file_bytes: int = 2_000_000,
) -> dict:
    """→ {ok, imports: [{file, line, stmt}], reason}。

    只审 changed_files 中的 .py(适配的交付物);其余类型忽略。"""
    rootp = Path(root).expanduser().resolve()
    pat = _import_pattern(import_module)
    hits: list[dict] = []
    for rel in changed_files:
        p = rootp / rel
        if p.suffix != ".py" or not p.is_file():
            continue
        try:
            if p.stat().st_size > max_file_bytes:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if pat.match(line):
                hits.append({"file": rel, "line": i, "stmt": line.strip()[:120]})
    if hits:
        return {"ok": True, "imports": hits, "reason": ""}
    return {
        "ok": False,
        "imports": [],
        "reason": (f"{FAILURE_TYPE}: 改动文件中未发现对目标库 "
                   f"`{import_module}` 的真实 import——疑似自行重写近似实现"),
    }
