# Architecture — Fraud Detection Platform

## System Context

The platform has three execution domains separated by trust boundaries:

1. **Data Domain (Databricks + ADLS)** — ingestion, transformation, feature engineering, model evaluation.
2. **Agent Domain (FastAPI on App Service)** — real-time transaction analysis via MCP orchestrator.
3. **Infra Domain (Terraform + GitHub Actions)** — provisioning, deployment, secrets management.

---

## Data Flow Diagram

```mermaid
flowchart TD
    subgraph Sources
        KG["Kaggle CSV"]
        SG["Synthetic Generator"]
    end

    subgraph ADLS["ADLS Gen2"]
        RAW["raw/"]
        BRONZE["bronze/ (Delta)"]
        SILVER["silver/ (Delta)"]
        GOLD["gold/ (Delta)"]
        LOGS["logs/ (JSONL)"]
    end

    subgraph Databricks
        NB01["01 Download / Mount"]
        NB02["02 Bronze Ingest"]
        NB03["03 Silver Clean"]
        NB04["04 Gold Features"]
        NB05["05 Baseline Eval"]
        NB06["06 Synthetic Ingest"]
        NB07["07 Agent Replay Eval"]
    end

    subgraph AgentService["Agent Service (FastAPI)"]
        ORCH["MCP Orchestrator"]
        TRIAGE["TriageAgent"]
        RISK["RiskScoringAgent"]
        COMP["ComplianceAgent"]
        INV["InvestigationAgent"]
        LLM["Azure AI Foundry"]
    end

    KG -->|upload| RAW
    SG -->|parquet| RAW

    RAW --> NB01 --> NB02 --> BRONZE
    BRONZE --> NB03 --> SILVER
    SILVER --> NB04 --> GOLD

    GOLD --> NB05
    GOLD --> NB07

    GOLD -->|features| ORCH
    ORCH --> TRIAGE
    ORCH --> RISK
    ORCH --> COMP
    TRIAGE -->|uncertain| INV
    INV -->|gated call| LLM

    ORCH -->|audit events| LOGS
    LOGS --> NB07
```

---

## Trust Boundaries

```
┌─────────────────────────────────────────────────────────┐
│  BOUNDARY 1: Azure VNet / Private Endpoints             │
│                                                         │
│  ┌───────────────────┐    ┌──────────────────────────┐  │
│  │  App Service       │    │  ADLS Gen2               │  │
│  │  (Agent container) │◄──►│  raw/ bronze/ gold/ logs/│  │
│  └────────┬──────────┘    └──────────────────────────┘  │
│           │                                             │
│           ▼ MI auth                                     │
│  ┌───────────────────┐                                  │
│  │  Key Vault         │                                  │
│  └───────────────────┘                                  │
│                                                         │
│  BOUNDARY 2: Databricks workspace (own VNet injection)  │
│  ┌───────────────────┐                                  │
│  │  Job Clusters      │◄── ADLS via service principal   │
│  └───────────────────┘                                  │
└─────────────────────────────────────────────────────────┘

BOUNDARY 3: External
  ┌───────────────────┐
  │ Azure AI Foundry   │  ← called only from Agent via HTTPS
  └───────────────────┘
  ┌───────────────────┐
  │ GitHub Actions     │  ← OIDC federated credential
  └───────────────────┘
```

---

## Medallion Architecture

| Layer | Delta Table | Description |
|---|---|---|
| **Bronze** | `bronze.creditcard_transactions` | Raw CSV schema preserved; append-only. |
| **Bronze** | `bronze.synthetic_transactions` | Synthetic generator output. |
| **Silver** | `silver.creditcard_cleaned` | Typed, nulls handled, amount normalised. |
| **Gold** | `gold.cc_features` | Feature vector + label for scoring / eval. |
| **Gold** | `gold.synthetic_features` | Same schema from synthetic data. |
| **Metrics** | `metrics.model_eval` | Baseline model precision / recall / PR-AUC. |
| **Metrics** | `metrics.agent_eval` | Agent decision accuracy vs ground truth. |
| **Results** | `results.agent_decisions` | Raw agent decision records from replay. |

---

## Agent Orchestration Flow

```mermaid
sequenceDiagram
    participant Client
    participant Orchestrator
    participant Triage as TriageAgent
    participant Risk as RiskScoringAgent
    participant Compliance as ComplianceAgent
    participant Investigation as InvestigationAgent
    participant LLM as Azure AI Foundry
    participant AuditLog

    Client->>Orchestrator: POST /analyze-transaction
    Orchestrator->>Triage: evaluate(transaction)
    Triage-->>Orchestrator: triage_result (needs_llm=false)

    Orchestrator->>Risk: score(features)
    Risk-->>Orchestrator: risk_score

    Orchestrator->>Compliance: check_policies(transaction)
    Compliance-->>Orchestrator: policy_results[]

    alt risk_score > threshold OR policy_fail
        Orchestrator->>Investigation: investigate(context)
        Investigation->>LLM: prompt (gated)
        LLM-->>Investigation: analysis
        Investigation-->>Orchestrator: investigation_result
    end

    Orchestrator->>AuditLog: write_audit_event()
    Orchestrator-->>Client: AgentDecisionOut
```

---

## Key Design Decisions

| Decision | Rationale | Tradeoff |
|---|---|---|
| Batch-first (no streaming) | Simpler infra, cheaper; streaming is Phase 2. | Higher latency for real-time use cases. |
| Job clusters only | Cost control; no idle interactive clusters. | Slower notebook iteration during dev. |
| LLM gated by triage | 90%+ of transactions are clear-cut; saves ~$0.01–0.03 per skipped call. | Uncertain-region accuracy depends on threshold tuning. |
| Prompt hash, not raw prompt | Privacy + storage savings. | Cannot replay exact prompts without re-generation. |
| OIDC, no PATs in CI | Zero long-lived secrets in GitHub. | Slightly more setup for federated credential. |
