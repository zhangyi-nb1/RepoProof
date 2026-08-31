"""Anonymous controls for generic Product delivery-risk admission."""

from __future__ import annotations

import pytest

from repoproof.adoption.admission.intent_risk_policy import (
    classify_product_intent_risk,
)


@pytest.mark.parametrize(
    ("goal", "reason_code"),
    [
        (
            "登录我的私人账号并发布一条真实内容。",
            "UNSUPPORTED_CREDENTIALLED_EXTERNAL_SIDE_EFFECT",
        ),
        (
            "Download the latest records from the online API.",
            "UNSUPPORTED_RUNTIME_NETWORK_REQUIRED",
        ),
        (
            "从在线 API 下载最新记录并生成本地报告。",
            "UNSUPPORTED_RUNTIME_NETWORK_REQUIRED",
        ),
        (
            "Use browser automation to complete this workflow.",
            "UNSUPPORTED_BROWSER_REQUIRED",
        ),
        (
            "Run continuously as a long-running daemon.",
            "UNSUPPORTED_LONG_RUNNING_LIFECYCLE",
        ),
        (
            "持续监控本地实验目录，有新文件就生成摘要。",
            "UNSUPPORTED_LONG_RUNNING_LIFECYCLE",
        ),
        ("This analysis must use CUDA on a GPU.", "UNSUPPORTED_GPU_RUNTIME"),
        (
            "Deploy the generated tool to a cloud service.",
            "UNSUPPORTED_REMOTE_SERVICE_RUNTIME",
        ),
        (
            "把生成的报告上传到云盘，之后允许我删除。",
            "UNSUPPORTED_REVERSIBLE_EXTERNAL_SIDE_EFFECT",
        ),
    ],
)
def test_explicit_unsupported_delivery_dimensions_have_stable_reasons(
    goal: str, reason_code: str
) -> None:
    result = classify_product_intent_risk(goal)

    assert result.supported is False
    assert reason_code in result.reason_codes


def test_local_offline_workspace_intent_is_not_rejected_by_keyword_guessing() -> None:
    result = classify_product_intent_risk(
        "读取本地保存的网页和付款记录，生成一个离线可打开的资料目录。"
    )

    assert result.supported is True
    assert result.reason_codes == ()


def test_local_sensitive_data_remains_supported_when_processing_is_offline() -> None:
    result = classify_product_intent_risk(
        "读取本地保存的银行流水，离线生成一个新的核对工作区。"
    )

    assert result.supported is True
    assert result.reason_codes == ()
