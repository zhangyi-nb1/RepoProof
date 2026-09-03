"""CLI 永远交出结构化结果,不把栈直接甩给调用方(incident-*-cli-payload-*)。

现象:两个独立仓库的旅程都以 `CLI_PAYLOAD_MISSING` 收场——一次是供应商限流异常
(litellm RateLimitError)逃出 `tool add`,一次是 Harness 自己的
`ReferenceWheelhouseMaterializationError` 逃出去。调用方(autopilot / Studio 作业面)
只拿到"没有 payload"这一个信息量为零的码,盘上留不下可诊断的事实。

不变量:
  I1 任何未捕获异常都被投影成 stdout 上的 JSON:ok=false、failure_owner=HARNESS、
     reason_codes 含 `CLI_UNCAUGHT_EXCEPTION` 与由异常类派生的稳定码、带公开消息;
     返回码非零;
  I2 公开消息去凭据、去换行、有界(≤240),绝不出现 token/Bearer/api key 形状;
  I3 argparse 的 SystemExit(--help/参数错)不被吞;正常成功路径逐字节不变;
  I4 万一仍拿不到 payload,消费侧把 stderr 尾部里的异常类投影成第二个码,
     不再只留 CLI_PAYLOAD_MISSING。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repoproof import cli
from repoproof.ui.services import autopilot


def _payload(capsys) -> dict:
    out = capsys.readouterr().out
    start, end = out.find("{"), out.rfind("}")
    assert start >= 0 and end > start, out
    return json.loads(out[start : end + 1])


def _raise(exc: BaseException):
    def _boom(*_args, **_kwargs):
        raise exc

    return _boom


def test_uncaught_exception_becomes_a_named_payload(tmp_path: Path, monkeypatch, capsys) -> None:
    from repoproof.adoption.intake import draft_readiness

    class ReferenceWheelhouseMaterializationError(RuntimeError):
        pass

    monkeypatch.setattr(
        draft_readiness,
        "read_draft_readiness",
        _raise(ReferenceWheelhouseMaterializationError("参考依赖 wheelhouse 建立失败")),
    )
    code = cli.main(["tool", "readiness", "--draft-dir", str(tmp_path)])
    payload = _payload(capsys)
    assert code != 0
    assert payload["ok"] is False and payload["failure_owner"] == "HARNESS"
    assert "CLI_UNCAUGHT_EXCEPTION" in payload["reason_codes"]
    assert "REFERENCE_WHEELHOUSE_MATERIALIZATION_ERROR" in payload["reason_codes"]
    assert payload["exception_type"] == "ReferenceWheelhouseMaterializationError"
    assert "wheelhouse" in payload["error"]


def test_public_message_drops_credentials_and_is_bounded(tmp_path: Path, monkeypatch, capsys) -> None:
    from repoproof.adoption.intake import draft_readiness

    leaky = (
        "POST https://gateway.internal/v1/messages failed\n"
        "headers: {'Authorization': 'Bearer sk-live-9f3a2b7c4d5e6f70', 'x-api-key': 'sk-live-9f3a2b7c4d5e6f70'}\n"
        + "body " * 200
    )
    monkeypatch.setattr(draft_readiness, "read_draft_readiness", _raise(RuntimeError(leaky)))
    cli.main(["tool", "readiness", "--draft-dir", str(tmp_path)])
    message = _payload(capsys)["error"]
    assert "sk-live-9f3a2b7c4d5e6f70" not in message
    assert "Bearer" not in message
    assert "\n" not in message and len(message) <= 240


def test_argparse_exit_is_not_swallowed() -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["--help"])
    assert caught.value.code == 0


def test_ordinary_failure_path_is_unchanged(tmp_path: Path, capsys) -> None:
    code = cli.main(["tool", "readiness", "--draft-dir", str(tmp_path)])
    payload = _payload(capsys)
    assert code == 3 and payload["ok"] is False
    assert "CLI_UNCAUGHT_EXCEPTION" not in (payload.get("reason_codes") or [])
    assert "DRAFT_DOCUMENT_MISSING" in payload["reason_codes"]


def test_consumer_fallback_names_the_exception_class() -> None:
    stderr = (
        'File "/x/y.py", line 3, in f\n'
        "repoproof.adoption.intake.example_proposer.ReferenceWheelhouseMaterializationError: 建立失败\n"
    )
    codes = autopilot.cli_failure_reason_codes(stderr)
    assert codes[0] == "CLI_PAYLOAD_MISSING"
    assert "REFERENCE_WHEELHOUSE_MATERIALIZATION_ERROR" in codes
