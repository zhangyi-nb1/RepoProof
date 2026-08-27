"""上游 pin 的**单一来源**:钉版树声明什么版本,全链就用哪一版。

来由(2026-08-28,webcolors 连跑四发白跑):`reference.lock.txt` 在人务
清单里标着"(可选)",而它缺席时整条链会**在三个地方各自静默降级**:

1. `confirm_tool_draft` 传 `reference_lock=""` → 装配器不写
   `controls/<task>/reference/requirements.lock.txt`;
2. 备轮 `pip download` 拿不到上游 pin → wheelhouse 里没有上游本体;
3. positive 彩排的预装步读不到那份 controls 锁 → 会话 venv 不装上游。

于是 `import <上游>` 在会话里必炸,却要等三轮修复耗尽,才以
`DEPENDENCY_ERROR` 的形式浮出来 —— 病因与症状隔了十万八千里。

修法不是在三处各打一个补丁,而是**让那份锁一定存在**:草稿束没写就从
钉版树自己声明的版本派生。用树里的版本、不是 PyPI 的最新版 —— pin 的
语义是"就这一版",去解析最新版等于把钉版偷偷放开。

派生不出来时返回空串:调用方各自决定是拒发(备轮)还是照旧留空
(装配)——本模块只负责"说出事实",不替人做判定。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


def normalize_dist_name(name: str) -> str:
    """PEP 503 归一化(`Foo_Bar.baz` 与 `foo-bar-baz` 是同一个分发)。"""
    return re.sub(r"[-_.]+", "-", (name or "").strip()).lower()


def upstream_version(upstream_dir: Path) -> str:
    """从钉版上游树读**它自己声明的**版本;读不出返回空串。

    顺序:pyproject(PEP 621 / poetry)→ setup.cfg → *.egg-info/PKG-INFO。
    动态版本(`dynamic = ["version"]`)读不出属正常 —— 那种仓库必须由人
    在 `reference.lock.txt` 里写死,本函数不猜。
    """
    root = Path(upstream_dir)
    py = root / "pyproject.toml"
    if py.is_file():
        try:
            data = tomllib.loads(py.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        v = ((data.get("project") or {}).get("version")
             or ((data.get("tool") or {}).get("poetry") or {}).get("version"))
        if isinstance(v, str) and v.strip():
            return v.strip()
    cfg = root / "setup.cfg"
    if cfg.is_file():
        m = re.search(r"^\s*version\s*=\s*(\S+)\s*$",
                      cfg.read_text(encoding="utf-8", errors="replace"),
                      re.MULTILINE)
        if m:
            return m.group(1).strip()
    for info in sorted(root.glob("*.egg-info/PKG-INFO")):
        m = re.search(r"^Version:\s*(\S+)\s*$",
                      info.read_text(encoding="utf-8", errors="replace"),
                      re.MULTILINE)
        if m:
            return m.group(1).strip()
    return ""


def pinned_upstream_dir(project_root: Path, resolved_commit: str) -> Path:
    """钉版树落点(与 tool_pipeline.ensure_pinned_upstream 同一约定)。"""
    return Path(project_root) / "upstream-cache" / f"upstream-{resolved_commit[:12]}"


def derive_reference_lock(project_root: Path, *, distribution: str,
                          resolved_commit: str) -> str:
    """→ `"<dist>==<版本>\\n"`(带来源注释);派生不出时返回空串。"""
    if not distribution or not resolved_commit:
        return ""
    version = upstream_version(pinned_upstream_dir(project_root, resolved_commit))
    if not version:
        return ""
    return (f"# 由钉版上游树声明版本派生(commit {resolved_commit[:12]});\n"
            f"# 草稿束写了 reference.lock.txt 时以你写的为准。\n"
            f"{distribution}=={version}\n")
