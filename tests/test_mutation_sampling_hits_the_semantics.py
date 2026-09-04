"""判别力探针要改在语义上,不是改在样板上(incident-mutation-sampling-misses-the-semantics-*)。

现象:两个独立仓库上,判官对一份机器生成的 HTML 页面 8 次变异一次都不拒,四次判官修复也
改变不了 0/8——而同一份判官在别的轮次实实在在报出过导航缺链、标题未渲染、页面缺失。真因
在取样:`_text_content_mutations` 自己的文档说它要问"判官有没有重算这个文件的**任何**内容",
做法是取首行、末行与等距行;在语义只占少数行的主题化页面上,等距取样几乎必落在样板行
(meta、CSS 链接、脚本、导航骨架),于是这个问题实际变成了"判官有没有在查样板"。语义判官
按设计就不该对样板敏感,也不该内嵌期望字节;字节保真另有闸门——冻结时的 golden identity
已经逐字节钉死。

不变量:
  I1 输入里出现过的记号所在的行优先被选为变异点;
  I2 一行都不含输入记号时回落到原来的等距取样(不能因此少问);
  I3 变异次数与"截断末行"这一条不变——判别力的强度不降,只是问在语义上。
"""

from __future__ import annotations

from repoproof.verification.workspace_semantic import content_mutations

_BOILERPLATE = "\n".join(
    [
        '<!doctype html><html lang="en">',
        '<meta charset="utf-8">',
        '<link rel="stylesheet" href="/assets/css/theme.css">',
        '<script src="/assets/js/bundle.js"></script>',
        '<nav class="md-header__inner"><div class="md-header__ellipsis"></div></nav>',
        "<h1>Quarterly Reconciliation Notes</h1>",
        '<footer class="md-footer"><small>Built with a static site generator</small></footer>',
        "</html>",
    ]
)


def _mutated_lines(payload: bytes, mutations) -> set[int]:
    original = payload.decode("utf-8").splitlines()
    changed: set[int] = set()
    for _kind, mutated in mutations:
        lines = mutated.decode("utf-8").splitlines()
        for index, line in enumerate(lines):
            if index < len(original) and line != original[index]:
                changed.add(index)
    return changed


def test_lines_carrying_input_tokens_are_preferred() -> None:
    payload = _BOILERPLATE.encode("utf-8")
    mutations = content_mutations(payload, limit=3, input_tokens=("Quarterly", "Reconciliation"))
    touched = _mutated_lines(payload, mutations)
    assert 5 in touched, "承载输入语义的那一行必须被改到"


def test_without_tokens_the_even_sample_is_unchanged() -> None:
    payload = _BOILERPLATE.encode("utf-8")
    assert content_mutations(payload, limit=4) == content_mutations(
        payload, limit=4, input_tokens=()
    )


def test_a_file_with_no_input_tokens_falls_back(caplog) -> None:
    payload = _BOILERPLATE.encode("utf-8")
    fallback = content_mutations(payload, limit=4, input_tokens=("nothing-matches-here",))
    assert fallback == content_mutations(payload, limit=4)


def test_the_probe_strength_is_unchanged() -> None:
    payload = _BOILERPLATE.encode("utf-8")
    with_tokens = content_mutations(payload, limit=5, input_tokens=("Quarterly",))
    without = content_mutations(payload, limit=5)
    assert len(with_tokens) == len(without)
    assert any(kind == "truncate-last-line" for kind, _ in with_tokens)
