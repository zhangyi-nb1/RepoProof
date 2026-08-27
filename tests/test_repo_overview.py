"""仓库概览(展示件)的钉死 —— 提取、来源标注,以及"不得越界"。

边界(RFC-010 [G1] 人闸的延长线):概览是**展示件**。它可以帮用户看懂
仓库,但不许替用户写下"我要什么能力" —— 那是人闸唯一不可代劳的东西。
所以这里既钉"提取得对",也钉"它没有把自己塞进 draft/判定面"。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from repoproof.adoption.analysis.repo_overview import build_repo_overview
from repoproof.adoption.analysis.repository_analyzer import (
    analyze_repository_dir,
    readme_prose,
)

_MD_README = """# coolkit

[![CI](https://img.shields.io/badge/ci-passing-green)](https://example.invalid/ci)
<img src="logo.png" alt="logo">

coolkit turns widgets into gadgets.

## Install

```bash
pip install coolkit
```

It supports three widget dialects.
"""

_RST_README = """.. -*-restructuredtext-*-

.. image:: https://example.invalid/badge.svg
   :alt: CI status image
   :target: https://example.invalid/actions

``rstkit`` is a module for converting between widget formats.

Support is included for the following formats:

* Named widgets

* Numbered widgets
"""


def test_prose_strips_markdown_badges_and_keeps_sentences():
    prose = readme_prose(_MD_README)
    assert prose.startswith("coolkit")               # 标题的井号被去掉
    assert "shields.io" not in prose                 # 徽章不算介绍
    assert "<img" not in prose                       # HTML 壳不算介绍
    assert "pip install coolkit" not in prose        # 代码块归 quickstart
    assert "three widget dialects" in prose


def test_prose_strips_rst_directives_and_fields():
    """RST 的 `.. image::` / `:alt:` 会占满开头(webcolors 实测),
    不滤掉的话"这个仓库是干什么的"第一行就是一句机器噪声。"""
    prose = readme_prose(_RST_README)
    assert prose.startswith("``rstkit`` is a module")
    for noise in ("restructuredtext", ".. image", ":alt:", ":target:", "badge.svg"):
        assert noise not in prose, prose[:200]


def test_prose_is_bounded():
    huge = "\n\n".join(f"paragraph {i} " + "x" * 200 for i in range(50))
    assert len(readme_prose(huge)) <= 1200


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "coolkit"
    (root / "coolkit").mkdir(parents=True)
    (root / "coolkit" / "__init__.py").write_text(
        '__all__ = ["convert"]\n\n\ndef convert(path: str) -> str:\n    return path\n',
        encoding="utf-8")
    (root / "README.md").write_text(_MD_README, encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "coolkit"\nversion = "1.0.0"\n'
        'license = {text = "MIT"}\nrequires-python = ">=3.10"\n', encoding="utf-8")
    (root / "LICENSE").write_text("MIT License\n\nCopyright (c) 2026 t\n", encoding="utf-8")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "v1"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    return root


def test_overview_carries_evidence_for_every_fact(tmp_path: Path):
    """每条事实都要说得出出处 —— 说不出出处的介绍没有资格出现在用户面前。"""
    report = analyze_repository_dir(_repo(tmp_path), url="https://example.invalid/coolkit")
    ov = build_repo_overview(report)

    assert ov["headline"].startswith("coolkit turns widgets")
    assert ov["prose_source"] == "README 原文摘录(未经模型改写)"
    assert ov["facts"], ov
    for f in ov["facts"]:
        assert f["label"] and f["value"]
        assert f["provenance"], f          # 每条都带来源档位
    labels = {f["label"] for f in ov["facts"]}
    assert {"许可证", "Python 版本", "运行期依赖"} <= labels
    assert any(s["value"] == "convert" for s in ov["surfaces"]), ov["surfaces"]


def test_overview_never_writes_the_users_capability(tmp_path: Path):
    """**负控**:概览不得携带 capability/goal 字段。

    只要它没有这个字段,UI 就不可能"顺手"把模型对仓库的理解填成用户的
    能力描述 —— 这条边界在数据形状上就断掉,不靠人记得别那么写。
    """
    report = analyze_repository_dir(_repo(tmp_path), url="https://example.invalid/coolkit")
    ov = build_repo_overview(report)
    for forbidden in ("capability_goal", "goal", "capability", "statement"):
        assert forbidden not in ov, f"概览不该产出 {forbidden}(那是用户的话)"
