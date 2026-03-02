# Schema Reference — Fraud Detection Platform

All schemas are defined as Pydantic v2 models in [`agent/app/schemas.py`](../agent/app/schemas.py).
This document provides a human-readable reference.

---

## Conventions

- **`trace_id`** — UUID4 string that travels end-to-end from ingest through agent decision to audit log.
- **`schema_version`** — Semantic version (`"1.0.0"`) enabling backward-compatible evolution.
- **PII fields** — Marked with `pii: true` in JSON Schema metadata. The audit pipeline **must** hash or strip these before long-term storage.
- **Timestamps** — UTC ISO-8601 (`datetime`). All defaults use `datetime.utcnow`.

---

## Enums

| Enum | Values | Usage |
|---|---|---|
| `RiskLevel` | `low`, `medium`, `high`, `critical` | Risk bucketing |
| `DecisionAction` | `approve`, `flag`, `block`, `escalate` | Agent verdict |
| `DatasetSource` | `kaggle`, `synthetic`, `live` | Traceability |
| `ScenarioType` | `card_testing`, `account_takeover`, `merchant_fraud`, `velocity_attack`, `legitimate` | Synthetic labels |
| `CaseStatus` | `open`, `under_review`, `resolved_fraud`, `resolved_legit`, `closed` | Case lifecycle |
| `PolicyVerdict` | `pass`, `fail`, `warn` | Policy check output |

---

## TransactionIn

Inbound transaction payload submitted for analysis.

| Field | Type | Required | PII | Description |
|---|---|---|---|---|
| `schema_version` | `str` | — | — | Default `"1.0.0"` |
| `trace_id` | `str` | — | — | Auto-generated UUID4 |
| `transaction_id` | `str` | ✅ | — | Unique transaction ID |
| `customer_id` | `str` | ✅ | ⚠️ | Pseudonymised customer ID |
| `merchant_id` | `str` | ✅ | — | Pseudonymised merchant ID |
| `amount` | `float` | ✅ | — | ≥ 0, original currency |
| `currency` | `str` | — | — | ISO-4217, default `EUR` |
| `country` | `str` | ✅ | — | ISO-3166 code |
| `channel` | `str` | — | — | `online` / `pos` / `atm` |
| `device_id` | `str?` | — | ⚠️ | Device fingerprint |
| `timestamp` | `datetime` | — | — | UTC |
| `dataset_source` | `DatasetSource` | — | — | Default `live` |
| `scenario_type` | `ScenarioType?` | — | — | Synthetic-data only |
| `label` | `int?` | — | — | `1`=fraud, `0`=legit, `None`=live |
| `features` | `Dict[str,float]?` | — | — | Pre-computed feature vector |

---

## AgentDecisionOut

Final combined verdict returned by the orchestrator.

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | `str` | — | Default `"1.0.0"` |
| `trace_id` | `str` | ✅ | Must match inbound trace_id |
| `transaction_id` | `str` | ✅ | |
| `decision` | `DecisionAction` | ✅ | `approve` / `flag` / `block` / `escalate` |
| `risk_score` | `float` | ✅ | 0.0–1.0 normalised |
| `risk_level` | `RiskLevel` | ✅ | |
| `reasons` | `List[str]` | — | Human-readable explanations |
| `policy_results` | `List[PolicyCheckResult]` | — | Individual checks |
| `llm_used` | `bool` | — | Default `false` |
| `model_version` | `str` | — | Default `"rules-v1"` |
| `latency_ms` | `float` | — | Total processing time |
| `decided_at` | `datetime` | — | UTC |

---

## AgentEventLog

Immutable audit record per agent action.

| Field | Type | Required | PII | Description |
|---|---|---|---|---|
| `schema_version` | `str` | — | — | |
| `trace_id` | `str` | ✅ | — | |
| `event_id` | `str` | — | — | Auto-generated UUID4 |
| `transaction_id` | `str` | ✅ | — | |
| `dataset_source` | `DatasetSource` | — | — | |
| `agent_name` | `str` | ✅ | — | Which agent acted |
| `action` | `str` | ✅ | — | Tool name or decision |
| `decision` | `DecisionAction?` | — | — | |
| `risk_score` | `float?` | — | — | 0.0–1.0 |
| `reasons` | `List[str]` | — | ❌ | Must not contain PII |
| `scenario_type` | `ScenarioType?` | — | — | |
| `model_version` | `str` | — | — | |
| `policy_result` | `PolicyVerdict?` | — | — | |
| `llm_used` | `bool` | — | — | |
| `prompt_hash` | `str?` | — | — | SHA-256 of LLM prompt |
| `latency_ms` | `float` | — | — | |
| `timestamp` | `datetime` | — | — | |
| `metadata` | `Dict[str,Any]` | — | — | Extensible key-value bag |

> **PII Redaction**: Raw prompts are **never** stored. Only the SHA-256 hash is persisted. The `reasons` list must be reviewed to ensure no customer names or card numbers leak through.

---

## PolicyCheckResult

Output of a single compliance / policy evaluation.

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | `str` | — | |
| `trace_id` | `str` | — | Auto-generated |
| `policy_name` | `str` | ✅ | e.g. `"velocity_24h"` |
| `verdict` | `PolicyVerdict` | ✅ | `pass` / `fail` / `warn` |
| `details` | `str` | — | Explanation |
| `threshold` | `float?` | — | Rule threshold |
| `observed_value` | `float?` | — | Actual value |
| `evaluated_at` | `datetime` | — | UTC |

---

## CaseRecord

Escalation case for human review.

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | `str` | — | |
| `trace_id` | `str` | ✅ | |
| `case_id` | `str` | — | Auto-generated UUID4 |
| `transaction_id` | `str` | ✅ | |
| `decision` | `DecisionAction` | ✅ | |
| `risk_score` | `float` | ✅ | 0.0–1.0 |
| `risk_level` | `RiskLevel` | ✅ | |
| `reasons` | `List[str]` | — | |
| `policy_results` | `List[PolicyCheckResult]` | — | |
| `status` | `CaseStatus` | — | Default `open` |
| `assigned_to` | `str?` | — | Analyst user ID |
| `resolution_notes` | `str?` | — | |
| `created_at` | `datetime` | — | |
| `updated_at` | `datetime` | — | |

### Lifecycle

```
OPEN → UNDER_REVIEW → RESOLVED_FRAUD / RESOLVED_LEGIT → CLOSED
```
