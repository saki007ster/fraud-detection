# Agent Policies & Guardrails — Fraud Detection Platform

This document defines the security policies, cost controls, and operational guardrails
for the MCP-based agent system.

---

## 1. Agent Role & Scope Matrix

| Agent | Allowed Tools | Data Access | Can Invoke LLM? |
|---|---|---|---|
| **TriageAgent** | `get_transaction_features`, `write_audit_event` | Gold features (read) | ❌ |
| **RiskScoringAgent** | `get_transaction_features`, `score_risk`, `write_audit_event` | Gold features (read) | ❌ |
| **ComplianceAgent** | `check_policy`, `write_audit_event` | Gold features (read), Policy config (read) | ❌ |
| **InvestigationAgent** | `get_transaction_features`, `score_risk`, `check_policy`, `create_case`, `write_audit_event` | Gold features (read), Cases (write) | ✅ (gated) |
| **Orchestrator** | All tools | All scoped data | ❌ (delegates) |

### Data Field Restrictions

- **No PII by default**: Agents receive pseudonymised IDs only.
- `customer_id` and `device_id` are hashed before agent access in production.
- Raw card numbers, names, and addresses are **never** passed to any agent.

---

## 2. LLM Call Gating

LLM calls (Azure AI Foundry) are expensive and introduce latency. They are gated as follows:

```
IF triage_score < 0.3           → APPROVE (no LLM)
ELIF triage_score < 0.7         → rules-only scoring (no LLM)
ELIF triage_score >= 0.7        → InvestigationAgent may call LLM
  AND any policy check == FAIL
```

### Cost Controls

| Control | Value | Rationale |
|---|---|---|
| Max LLM calls per batch | 50 | Prevent runaway costs during replay eval |
| Max tokens per call | 1024 | Sufficient for structured analysis |
| Cache TTL | 1 hour | Repeated patterns get cached response |
| Cache key | SHA-256(model + system_prompt + user_prompt) | Privacy-safe, deterministic |
| Daily budget alert | $10 | Azure budget alert on AI Foundry resource |

### Prompt Storage Policy

- **Raw prompts are never persisted** to any log or database.
- Only `prompt_hash` (SHA-256) is stored in `AgentEventLog`.
- To replay a prompt for debugging, re-generate it from the transaction features + template.

---

## 3. Tool Permission Model

Each MCP tool has a strict interface schema and access control:

### `get_transaction_features(transaction_id: str) → Dict[str, float]`
- **Who can call**: TriageAgent, RiskScoringAgent, InvestigationAgent
- **Returns**: Feature vector from gold table (no PII fields)
- **Rate limit**: 100 calls/sec

### `score_risk(features: Dict[str, float]) → float`
- **Who can call**: RiskScoringAgent, InvestigationAgent
- **Returns**: Normalised risk score [0.0, 1.0]
- **Validation**: Input must match expected feature schema

### `check_policy(action: str, context: Dict) → PolicyCheckResult`
- **Who can call**: ComplianceAgent, InvestigationAgent
- **Policies**: velocity_24h, geo_mismatch, device_mismatch, amount_threshold
- **Returns**: Structured `PolicyCheckResult`

### `write_audit_event(event: AgentEventLog) → str`
- **Who can call**: All agents
- **Side effect**: Appends JSONL to ADLS `logs/` container
- **Validation**: Event must conform to `AgentEventLog` schema

### `create_case(decision: AgentDecisionOut) → CaseRecord`
- **Who can call**: InvestigationAgent, Orchestrator
- **Side effect**: Creates case record; returns `case_id`

---

## 4. Prompt Injection Mitigations

| Layer | Mitigation |
|---|---|
| **System prompt isolation** | System prompt is fixed and not influenced by user/transaction data. |
| **Input sanitisation** | Transaction fields are type-checked via Pydantic before reaching any agent. |
| **No arbitrary tools** | Agents can only call tools in their allowlist (see §1). |
| **Output validation** | All agent outputs are validated against Pydantic schemas before returning. |
| **No dynamic code execution** | Agents do not execute arbitrary code or eval() expressions. |
| **Content filtering** | Azure AI Foundry content safety filters are enabled. |

---

## 5. Operational Policies

### Databricks

- **Job clusters only** — No interactive/all-purpose clusters in production.
- **Auto-terminate** — 10-minute idle timeout on all clusters.
- **Instance pools** — Not used in MVP (cost vs. startup-time tradeoff documented).
- **Unity Catalog** — Recommended for Phase 2 to enforce table-level ACLs.

### Agent Service

- **Health check** — `POST /health` returns 200 with version info; used by App Service health probe.
- **Graceful degradation** — If LLM endpoint is unavailable, InvestigationAgent returns `escalate` decision with `llm_used=false`.
- **Structured logging** — All logs are JSON-formatted; no unstructured print statements.
- **No secrets in environment** — All secrets fetched from Key Vault at startup via managed identity.

### CI/CD

- **Terraform plan on PR** — `terraform plan` runs on every PR; `apply` only on merge to `main`.
- **Environment protection** — `main` branch requires approval for production apply.
- **No long-lived secrets** — OIDC for Azure auth; Databricks PAT (if used) stored in Key Vault.
- **Image scanning** — Container images scanned before push to ACR (Phase 2).

---

## 6. Audit & Compliance

Every agent action produces an `AgentEventLog` record containing:

- `trace_id` (correlates to original transaction)
- `agent_name`, `action`, `decision`
- `llm_used`, `prompt_hash`
- `latency_ms`, `timestamp`

These records are:
1. Written as JSONL to ADLS `logs/` container (append-only).
2. Ingested into Databricks Delta table for analytics.
3. Queryable for compliance reporting (who decided what, when, why).

### Retention

| Data | Retention | Rationale |
|---|---|---|
| Audit logs | 7 years | Financial regulation compliance |
| Raw transaction data | 90 days in hot, then archive | Cost optimisation |
| Gold features | Indefinite | Needed for model retraining |
| Case records | Indefinite | Legal hold potential |
