"""
FastAPI application — fraud-detection agent service.

Endpoints:
  POST /health               → health check with version + cache stats
  POST /analyze-transaction   → full agent pipeline analysis

The orchestrator routes through:
  1. TriageAgent       → early-exit for low-risk
  2. RiskScoringAgent  → normalised risk score
  3. ComplianceAgent   → policy checks
  4. InvestigationAgent → LLM analysis (only for uncertain/high-risk)
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .audit_logger import AuditLogger
from .cache import ResponseCache
from .llm_client import LLMClient
from .mcp_server import MCPServer
from .schemas import (
    AgentDecisionOut,
    AgentEventLog,
    DatasetSource,
    DecisionAction,
    PolicyCheckResult,
    RiskLevel,
    TransactionIn,
)

# ── Logging setup ────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── Application globals ─────────────────────────────────────────────

VERSION = "0.1.0"
cache = ResponseCache()
audit_logger = AuditLogger(
    adls_connection_string=os.getenv("ADLS_CONNECTION_STRING"),
    local_path=os.getenv("AUDIT_LOG_PATH", "logs/audit_events.jsonl"),
)
llm_client = LLMClient(cache=cache)
mcp = MCPServer(audit_logger=audit_logger)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Agent service starting (version=%s)", VERSION)
    logger.info("MCP tools registered: %s", mcp.tool_names)
    logger.info("LLM endpoint configured: %s", bool(llm_client.endpoint))
    yield
    logger.info("Agent service shutting down")


app = FastAPI(
    title="Fraud Detection Agent",
    version=VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ORIGINS", "*")],
    allow_methods=["POST"],
    allow_headers=["*"],
)


# ── Endpoints ────────────────────────────────────────────────────────


@app.post("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "version": VERSION,
        "llm_configured": bool(llm_client.endpoint),
        "llm_calls": llm_client.call_count,
        "cache_stats": cache.stats,
        "mcp_tools": mcp.tool_names,
    }


@app.post("/analyze-transaction")
async def analyze_transaction(tx: TransactionIn) -> AgentDecisionOut:
    """Full agent pipeline analysis of a single transaction."""
    start = time.monotonic()
    trace_id = tx.trace_id

    try:
        result = _orchestrate(tx)
        result.latency_ms = (time.monotonic() - start) * 1000
        return result
    except Exception as exc:
        logger.exception("Orchestration failed for trace=%s", trace_id)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Orchestrator ─────────────────────────────────────────────────────

def _orchestrate(tx: TransactionIn) -> AgentDecisionOut:
    """Route through specialist agents and produce a final decision."""
    from .agents.compliance import check_compliance
    from .agents.investigation import investigate
    from .agents.risk_scoring import score_risk
    from .agents.triage import triage

    trace_id = tx.trace_id
    tx_dict = tx.model_dump(mode="json")
    features = tx.features or mcp.call("get_transaction_features", transaction_id=tx.transaction_id)

    reasons: list[str] = []
    llm_used = False
    prompt_hash = None
    investigation_latency = 0.0

    # ── Step 1: Triage ──────────────────────────────────────────
    triage_score, early_decision, triage_reason = triage(tx_dict, features)
    reasons.append(f"Triage: {triage_reason}")

    _log_event(
        trace_id=trace_id,
        transaction_id=tx.transaction_id,
        dataset_source=tx.dataset_source,
        agent_name="triage",
        action="evaluate",
        risk_score=triage_score,
        reasons=[triage_reason],
        scenario_type=tx.scenario_type,
    )

    if early_decision is not None and triage_score < 0.3:
        return AgentDecisionOut(
            trace_id=trace_id,
            transaction_id=tx.transaction_id,
            decision=early_decision,
            risk_score=triage_score,
            risk_level=RiskLevel.LOW,
            reasons=reasons,
            model_version="triage-v1",
        )

    # ── Step 2: Risk Scoring ────────────────────────────────────
    risk_score, risk_level, risk_reason = score_risk(tx_dict, features)
    reasons.append(f"Risk: {risk_reason}")

    _log_event(
        trace_id=trace_id,
        transaction_id=tx.transaction_id,
        dataset_source=tx.dataset_source,
        agent_name="risk_scoring",
        action="score",
        risk_score=risk_score,
        reasons=[risk_reason],
    )

    # ── Step 3: Compliance ──────────────────────────────────────
    # Build customer context (in production: fetched from customer profile store)
    customer_context = _build_customer_context(tx)
    policy_results, any_policy_failed, compliance_reason = check_compliance(tx_dict, customer_context)
    reasons.append(f"Compliance: {compliance_reason}")

    _log_event(
        trace_id=trace_id,
        transaction_id=tx.transaction_id,
        dataset_source=tx.dataset_source,
        agent_name="compliance",
        action="check_policies",
        reasons=[compliance_reason],
        policy_result=policy_results[0].verdict if policy_results else None,
    )

    # ── Step 4: Investigation (conditional) ─────────────────────
    if risk_score >= 0.7 and any_policy_failed:
        inv_result = investigate(tx_dict, risk_score, policy_results, llm_client)
        llm_used = inv_result["llm_used"]
        prompt_hash = inv_result.get("prompt_hash")
        investigation_latency = inv_result.get("latency_ms", 0.0)

        if inv_result["reasoning"]:
            reasons.append(f"Investigation: {inv_result['reasoning']}")

        _log_event(
            trace_id=trace_id,
            transaction_id=tx.transaction_id,
            dataset_source=tx.dataset_source,
            agent_name="investigation",
            action="investigate",
            decision=inv_result["decision"],
            risk_score=risk_score,
            reasons=[inv_result["reasoning"]],
            llm_used=llm_used,
            prompt_hash=prompt_hash,
            latency_ms=investigation_latency,
        )

        # Use investigation decision if LLM was actually used
        if llm_used or inv_result["decision"] == DecisionAction.ESCALATE:
            return AgentDecisionOut(
                trace_id=trace_id,
                transaction_id=tx.transaction_id,
                decision=inv_result["decision"],
                risk_score=risk_score,
                risk_level=risk_level,
                reasons=reasons,
                policy_results=policy_results,
                llm_used=llm_used,
                model_version="investigation-v1",
            )

    # ── Final decision (rules-only) ────────────────────────────
    if risk_score >= 0.8 or any_policy_failed:
        decision = DecisionAction.BLOCK if risk_score >= 0.8 else DecisionAction.FLAG
    elif risk_score >= 0.5:
        decision = DecisionAction.FLAG
    else:
        decision = DecisionAction.APPROVE

    return AgentDecisionOut(
        trace_id=trace_id,
        transaction_id=tx.transaction_id,
        decision=decision,
        risk_score=risk_score,
        risk_level=risk_level,
        reasons=reasons,
        policy_results=policy_results,
        llm_used=llm_used,
        model_version="rules-v1",
    )


# ── Helpers ──────────────────────────────────────────────────────────

def _build_customer_context(tx: TransactionIn) -> Dict[str, Any]:
    """Build customer context for policy checks.

    In production, this queries a customer profile store.
    For the MVP, we return minimal context.
    """
    return {
        "tx_count_24h": 1,  # unknown — default safe
        "usual_countries": [],  # unknown — will trigger WARN
        "known_devices": [],  # unknown — will trigger WARN
    }


def _log_event(
    trace_id: str,
    transaction_id: str,
    agent_name: str,
    action: str,
    *,
    dataset_source: DatasetSource | None = None,
    decision: DecisionAction | None = None,
    risk_score: float | None = None,
    reasons: list[str] | None = None,
    scenario_type: Any = None,
    policy_result: Any = None,
    llm_used: bool = False,
    prompt_hash: str | None = None,
    latency_ms: float = 0.0,
) -> None:
    """Convenience wrapper to create and write an audit event."""
    event = AgentEventLog(
        trace_id=trace_id,
        transaction_id=transaction_id,
        dataset_source=dataset_source or DatasetSource.LIVE,
        agent_name=agent_name,
        action=action,
        decision=decision,
        risk_score=risk_score,
        reasons=reasons or [],
        scenario_type=scenario_type,
        policy_result=policy_result,
        llm_used=llm_used,
        prompt_hash=prompt_hash,
        latency_ms=latency_ms,
    )
    audit_logger.write_event(event)
