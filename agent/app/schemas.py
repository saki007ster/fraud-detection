"""
Pydantic schema contracts for the fraud-detection platform.

Design decisions
─────────────────
• Every model carries `trace_id` (UUID4) and `schema_version` (semver str)
  so downstream consumers can evolve safely.
• PII fields are annotated with `pii=True` in Field metadata.  The audit
  pipeline MUST strip / hash these before writing to long-term storage.
• Enums use `str` mixin for JSON-friendly serialisation.
• All timestamps are UTC ISO-8601.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class _BaseSchema(BaseModel):
    """Shared base with protected_namespaces disabled so we can use `model_version`."""
    model_config = ConfigDict(protected_namespaces=())


# ── Controlled vocabularies ──────────────────────────────────────────

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DecisionAction(str, Enum):
    APPROVE = "approve"
    FLAG = "flag"
    BLOCK = "block"
    ESCALATE = "escalate"


class DatasetSource(str, Enum):
    KAGGLE = "kaggle"
    SYNTHETIC = "synthetic"
    LIVE = "live"


class ScenarioType(str, Enum):
    CARD_TESTING = "card_testing"
    ACCOUNT_TAKEOVER = "account_takeover"
    MERCHANT_FRAUD = "merchant_fraud"
    VELOCITY_ATTACK = "velocity_attack"
    LEGITIMATE = "legitimate"


class CaseStatus(str, Enum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    RESOLVED_FRAUD = "resolved_fraud"
    RESOLVED_LEGIT = "resolved_legit"
    CLOSED = "closed"


class PolicyVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


# ── Schema models ────────────────────────────────────────────────────

class TransactionIn(_BaseSchema):
    """Inbound transaction payload submitted for analysis.

    PII notes
    ---------
    `customer_id`, `merchant_id`, `device_id` are pseudonymised identifiers.
    The raw card-number / name are NEVER accepted by this schema.
    `country` is kept for geo-risk rules but may be generalised to region
    before long-term storage.
    """

    schema_version: str = Field(default="1.0.0", description="Semantic version of this schema")
    trace_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="End-to-end trace identifier (UUID4)",
    )

    transaction_id: str = Field(..., description="Unique transaction identifier")
    customer_id: str = Field(..., description="Pseudonymised customer ID", json_schema_extra={"pii": True})
    merchant_id: str = Field(..., description="Pseudonymised merchant ID")
    amount: float = Field(..., ge=0, description="Transaction amount in original currency")
    currency: str = Field(default="EUR", max_length=3, description="ISO-4217 currency code")
    country: str = Field(..., max_length=3, description="ISO-3166 alpha-2/3 country code")
    channel: str = Field(default="online", description="Transaction channel: online | pos | atm")
    device_id: Optional[str] = Field(default=None, description="Device fingerprint", json_schema_extra={"pii": True})
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Transaction timestamp (UTC ISO-8601)",
    )
    dataset_source: DatasetSource = Field(
        default=DatasetSource.LIVE,
        description="Origin dataset for evaluation traceability",
    )
    scenario_type: Optional[ScenarioType] = Field(
        default=None,
        description="Ground-truth scenario label (present only for synthetic data)",
    )
    label: Optional[int] = Field(
        default=None,
        ge=0,
        le=1,
        description="Ground-truth fraud label (1=fraud, 0=legit). None for live traffic.",
    )

    # Feature vector – populated by the gold pipeline or passed directly
    features: Optional[Dict[str, float]] = Field(
        default=None,
        description="Pre-computed feature vector (V1…V28, normalised_amount, etc.)",
    )


class PolicyCheckResult(_BaseSchema):
    """Output of a single compliance / policy evaluation.

    Each check is independent; the ComplianceAgent may run many checks
    and aggregate the results.
    """

    schema_version: str = Field(default="1.0.0")
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    policy_name: str = Field(..., description="Human-readable policy name, e.g. 'velocity_24h'")
    verdict: PolicyVerdict = Field(..., description="Pass / fail / warn")
    details: str = Field(default="", description="Free-text explanation of the check outcome")
    threshold: Optional[float] = Field(default=None, description="Threshold value used")
    observed_value: Optional[float] = Field(default=None, description="Actual observed value")
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentDecisionOut(_BaseSchema):
    """Final combined verdict returned by the orchestrator.

    This is the response payload for POST /analyze-transaction.
    """

    schema_version: str = Field(default="1.0.0")
    trace_id: str = Field(..., description="Must match the inbound trace_id")

    transaction_id: str = Field(...)
    decision: DecisionAction = Field(...)
    risk_score: float = Field(..., ge=0.0, le=1.0, description="Normalised risk score")
    risk_level: RiskLevel = Field(...)
    reasons: List[str] = Field(default_factory=list, description="Human-readable reason strings")

    policy_results: List[PolicyCheckResult] = Field(
        default_factory=list,
        description="Individual policy check outputs",
    )

    llm_used: bool = Field(default=False, description="Whether an LLM call was made")
    model_version: str = Field(default="rules-v1", description="Scoring model/version tag")
    latency_ms: float = Field(default=0.0, ge=0, description="Total processing latency")
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentEventLog(_BaseSchema):
    """Immutable audit record written for every agent action.

    PII notes
    ---------
    • `transaction_id` is a pseudonymised key — safe to store.
    • Raw prompts are NOT stored; only `prompt_hash` is persisted.
    • `reasons` must not contain customer names or card numbers.
    """

    schema_version: str = Field(default="1.0.0")
    trace_id: str = Field(...)
    event_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique event identifier",
    )

    transaction_id: str = Field(...)
    dataset_source: DatasetSource = Field(default=DatasetSource.LIVE)
    agent_name: str = Field(..., description="Agent that produced this event")
    action: str = Field(..., description="Action taken by the agent (tool name or decision)")

    decision: Optional[DecisionAction] = Field(default=None)
    risk_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    reasons: List[str] = Field(default_factory=list)
    scenario_type: Optional[ScenarioType] = Field(default=None)

    model_version: str = Field(default="rules-v1")
    policy_result: Optional[PolicyVerdict] = Field(default=None)

    llm_used: bool = Field(default=False)
    prompt_hash: Optional[str] = Field(
        default=None,
        description="SHA-256 of the LLM prompt (privacy-safe reference)",
    )

    latency_ms: float = Field(default=0.0, ge=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible key-value bag for future fields",
    )


class CaseRecord(_BaseSchema):
    """Escalation case created when a transaction requires human review.

    Lifecycle: OPEN → UNDER_REVIEW → RESOLVED_FRAUD / RESOLVED_LEGIT → CLOSED
    """

    schema_version: str = Field(default="1.0.0")
    trace_id: str = Field(...)
    case_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique case identifier",
    )

    transaction_id: str = Field(...)
    decision: DecisionAction = Field(...)
    risk_score: float = Field(..., ge=0.0, le=1.0)
    risk_level: RiskLevel = Field(...)
    reasons: List[str] = Field(default_factory=list)
    policy_results: List[PolicyCheckResult] = Field(default_factory=list)

    status: CaseStatus = Field(default=CaseStatus.OPEN)
    assigned_to: Optional[str] = Field(default=None, description="Analyst user ID")
    resolution_notes: Optional[str] = Field(default=None)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
