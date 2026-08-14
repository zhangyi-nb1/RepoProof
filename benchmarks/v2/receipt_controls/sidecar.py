"""控制矩阵用的上游能力面 —— **只声明能力,不实现 sidecar**。

第 7 步的改动:sidecar 本体已提升进 `src/repoproof/execution/upstream_sidecar.py`。
本文件从"另写一个 sidecar"改成"给出厂的那份声明一个上游"。

这条很要紧:第 6 步的九组负控原本驱动的是这里的一个**平行原型**,于是
矩阵证明的是原型,而出厂要用的那份等于没证过。提升之后,同一套负控直接
打在出厂代码上 —— 证据和被证对象是同一个东西。

上游选 `markdown-it-py`:渲染 Markdown 真的可以被朴素重实现(nc1 就这么
干),输出又足够长,使"摘要相等"这条采纳判据有实质内容。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from repoproof.execution.runtime_profiles import RuntimeProfile, register_profile  # noqa: E402
from repoproof.execution.upstream_sidecar import UpstreamSpec, start_sidecar  # noqa: E402

DISTRIBUTION = "markdown-it-py"
IMPORT_MODULE = "markdown_it"
SYMBOL = "markdown_it.MarkdownIt.render"
PARSE_SYMBOL = "markdown_it.MarkdownIt.parse"
PROFILE_ID = "rt-sidecar-markdown-it-v1"


def _text(payload) -> str:
    return payload.get("text", "") if isinstance(payload, dict) else str(payload)


def _render(payload) -> str:
    import markdown_it

    return markdown_it.MarkdownIt().render(_text(payload))


def _parse(payload) -> str:
    """真实存在的另一个上游方法 —— 负控 nc4 用它:调的是真上游,
    但不是契约要求的那项能力。"""
    import markdown_it

    return json.dumps([t.type for t in markdown_it.MarkdownIt().parse(_text(payload))],
                      ensure_ascii=False)


SPEC = UpstreamSpec(DISTRIBUTION, IMPORT_MODULE,
                    {SYMBOL: _render, PARSE_SYMBOL: _parse})

PROFILE = register_profile(RuntimeProfile(
    id=PROFILE_ID, topology="sidecar", lifecycle="experimental",
    summary="控制矩阵专用:harness 持有 markdown-it-py,adapter 只能经 RPC 请它渲染",
    upstream=SPEC, required_symbols=frozenset({SYMBOL}), default_symbol=SYMBOL))


def _upstream_identity():
    return SPEC.identity()


def serve(ledger_path: Path, key: bytes, run_id: str, run_nonce: str,
          token: str, host: str = "127.0.0.1", port: int = 0):
    """薄封装 —— 起的是**出厂的** sidecar,不是另一份实现。"""
    return start_sidecar(spec=SPEC, ledger_path=ledger_path, key=key, run_id=run_id,
                         run_nonce=run_nonce, token=token, profile_id=PROFILE_ID,
                         default_symbol=SYMBOL, host=host, port=port)
