"""Typed failure ownership emitted by the Core audit boundary.

Reason codes remain stable diagnostics for operators and the append-only
release ledger.  They are deliberately *not* the product remediation API:
callers consume this metadata instead of reverse-mapping a reason code into an
owner or suggesting an adapter change without enough evidence.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

AuditFailureOwner = Literal[
    "USER_INPUT",
    "HARNESS",
    "CONTRACT",
    "AGENT_ADAPTER",
    "VERIFICATION",
]
AuditFailureStage = Literal[
    "AUDIT_PRECONDITION",
    "AUDIT_INPUT",
    "PACKAGE_VALIDATION",
    "BUILD",
    "ADAPTER_EXECUTION",
    "REFERENCE_COMPARISON",
    "OUTPUT_CONTRACT",
    "SEMANTIC_VERIFICATION",
    "EVIDENCE_PERSISTENCE",
]
AuditFailureClass = Literal[
    "USER_INPUT",
    "HARNESS_ENVIRONMENT",
    "PACKAGE_IDENTITY",
    "REFERENCE_MISMATCH",
    "CONTRACT_ORACLE_CONFLICT",
    "ADAPTER_EXECUTION",
]
AuditRetryPolicy = Literal[
    "RETRY_AFTER_INPUT_CORRECTION",
    "RETRY_AFTER_INPUT_REFRESH",
    "RETRY_AFTER_ENVIRONMENT_REPAIR",
    "RETRY_AFTER_PACKAGE_RESTORE",
    "REVIEW_REQUIRED",
    "NEW_TASK_VERSION_REQUIRED",
]
AuditRecommendedActionCode = Literal[
    "REPAIR_AUDIT_ENVIRONMENT",
    "CORRECT_AUDIT_INPUT",
    "REFRESH_AUDIT_CANDIDATE",
    "RESTORE_OR_REEXPORT_PACKAGE",
    "REPAIR_BUILD_ENVIRONMENT",
    "FIX_ADAPTER_AND_CREATE_NEW_TASK_VERSION",
    "REVIEW_REFERENCE_AND_ADAPTER",
    "REVIEW_CONTRACT_AND_CREATE_NEW_TASK_VERSION",
    "RESTORE_SEMANTIC_VERIFIER_AND_REVIEW",
    "RESTORE_SEMANTIC_VERIFIER_IDENTITY",
    "REVIEW_CONTRACT_ORACLE_AND_CREATE_NEW_TASK_VERSION",
    "CREATE_NEW_TASK_VERSION_AFTER_CONTRACT_REVIEW",
    "CREATE_NEW_TASK_VERSION_AFTER_WITHDRAWAL",
    "REPAIR_AUDIT_EVIDENCE_STORE",
]


class AuditFailureMetadata(BaseModel):
    """Stable remediation facts attached by the audit failure producer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    failure_owner: AuditFailureOwner
    failure_stage: AuditFailureStage
    failure_class: AuditFailureClass
    retry_policy: AuditRetryPolicy
    requires_new_task_version: bool
    recommended_action_code: AuditRecommendedActionCode
    recommended_action: str
    product_stop_code: Literal[
        "STOP_HARNESS_OR_EXTERNAL",
        "STOP_NEEDS_HUMAN",
        "STOP_NON_REPAIRABLE",
    ]

    def as_payload(self) -> dict[str, object]:
        """Return the additive flat payload consumed by CLI/Product Mode."""

        return self.model_dump(mode="json")
