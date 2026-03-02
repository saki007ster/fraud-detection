# Fraud Detection Platform

> Enterprise-grade, agent-driven financial transaction monitoring built on Azure + Databricks.

[![Terraform](https://img.shields.io/badge/IaC-Terraform-7B42BC)](infra/terraform/)
[![Databricks](https://img.shields.io/badge/Data-Databricks-FF3621)](databricks/)
[![FastAPI](https://img.shields.io/badge/Agent-FastAPI-009688)](agent/)

---

## Architecture Overview

```
┌──────────────┐   CSV/Parquet    ┌─────────────────────────────────────────┐
│  Kaggle Data │ ───────────────► │           ADLS Gen2                     │
│  Synthetic   │                  │  raw/ → bronze/ → silver/ → gold/      │
└──────────────┘                  └──────────────┬──────────────────────────┘
                                                 │  Delta Lake (Databricks)
                                                 ▼
                                  ┌──────────────────────────┐
                                  │   Databricks Workspace   │
                                  │  • Medallion pipelines   │
                                  │  • Baseline ML model     │
                                  │  • Agent replay eval     │
                                  └──────────┬───────────────┘
                                             │ gold features
                                             ▼
                                  ┌──────────────────────────┐
                                  │   Agent Service (FastAPI) │
                                  │  ┌─────────────────────┐ │
                                  │  │   MCP Orchestrator   │ │
                                  │  │  ┌────┐ ┌────┐      │ │
                                  │  │  │Tri.│ │Risk│      │ │
                                  │  │  └────┘ └────┘      │ │
                                  │  │  ┌────┐ ┌─────┐    │ │
                                  │  │  │Comp│ │Invst│    │ │
                                  │  │  └────┘ └─────┘    │ │
                                  │  └─────────────────────┘ │
                                  └──────────┬───────────────┘
                                             │ audit events (JSONL)
                                             ▼
                                  ┌──────────────────────────┐
                                  │  ADLS logs/ container    │
                                  │  → Databricks analytics  │
                                  └──────────────────────────┘
```

See [docs/architecture.md](docs/architecture.md) for full data-flow diagrams.

---

## Demo Flow

1. **Ingest** — Kaggle credit-card fraud CSV lands in ADLS `raw/`.
2. **Pipeline** — Databricks notebooks transform raw → bronze → silver → gold Delta tables.
3. **Baseline** — Spark ML logistic regression evaluates precision/recall against labeled data.
4. **Synthetic** — Generator produces tagged fraud scenarios (card-testing, ATO, velocity, merchant fraud).
5. **Agent Analysis** — FastAPI service with MCP orchestrator analyses transactions via specialist agents.
6. **Audit** — Every agent action is logged to ADLS as JSONL; consumed back into Databricks for evaluation.
7. **Verification** — Replay harness compares agent decisions to ground-truth labels.

---

## Cost Guardrails

| Control | Mechanism |
|---|---|
| **Databricks** | Job clusters only; aggressive auto-terminate (10 min idle). No interactive clusters in prod. |
| **LLM calls** | Gated by triage score threshold — only uncertain cases invoke Azure AI Foundry. Cached by prompt hash. |
| **Storage** | Delta table lifecycle policies; logs compacted weekly. |
| **Compute** | App Service B1/B2 SKU for agent; scale-to-zero where possible. |
| **CI/CD** | Terraform plan on PR; apply only on `main` with environment protection. |

---

## Security Model

- **No raw PII in logs** — customer/card data is pseudonymised at ingest; audit events store hashed IDs only.
- **Key Vault** — All secrets (Foundry API key, Databricks PAT) stored in Azure Key Vault; referenced by managed identity.
- **RBAC** — App Service managed identity has scoped access: Key Vault `secrets/get`, ADLS `logs/` write. Databricks identity scoped to `curated/` + `logs/`.
- **Prompt injection resistance** — System prompt isolation, input sanitisation, no arbitrary tool invocation.
- **OIDC** — GitHub Actions authenticates to Azure via OIDC (no long-lived secrets).

---

## Schemas

All data contracts are defined as Pydantic models in [`agent/app/schemas.py`](agent/app/schemas.py).
Human-readable reference: [docs/schemas.md](docs/schemas.md).

---

## Documentation Guide

We have written comprehensive documentation designed to be beginner-friendly. Start here:

- [Features & Workflow](docs/features.md): How the multi-agent system, cost guardrails, and data pipeline work under the hood.
- [Application Structure](docs/structure.md): The directory layout, what everything does, and our core architectural design principles.
- [Deployment Guide](docs/deployment.md): Step-by-step instructions on taking this project from your laptop and deploying it to Azure and Databricks.
- [Architecture Details](docs/architecture.md): Data flow diagrams, trust boundaries, and exact medallion pipeline schema tables.
- [Data Schemas](docs/schemas.md): Human-readable references for all Pydantic contracts passed between agents.
- [Policies & Guardrails](docs/policies.md): The specific operational limits ensuring LLM safety and predictable cloud billing.

---

## Repository Structure

```
├── agent/             # FastAPI agent service + MCP orchestrator
├── databricks/        # Notebooks, job configs, SQL queries
├── synthetic/         # Synthetic transaction generator
├── infra/terraform/   # Azure infrastructure as code
├── .github/workflows/ # CI/CD pipelines
└── docs/              # Comprehensive explanations and deployment guides
```

---

## License

MIT — see [LICENSE](LICENSE) for details.
