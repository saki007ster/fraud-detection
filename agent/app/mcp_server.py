"""
MCP Server — tool registry and dispatcher.

Exposes five internal tools with strict schema validation and logging:
  1. get_transaction_features(transaction_id)
  2. score_risk(features)
  3. check_policy(action, context)
  4. write_audit_event(event)
  5. create_case(decision)

Each tool call is logged for auditability.  Agents can only call tools
in their allowlist (enforced by the orchestrator, not here).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from .audit_logger import AuditLogger
from .schemas import (
    AgentDecisionOut,
    AgentEventLog,
    CaseRecord,
    DatasetSource,
    DecisionAction,
    PolicyCheckResult,
    RiskLevel,
)

logger = logging.getLogger(__name__)


class MCPServer:
    """Tool registry and dispatcher for agent tools."""

    def __init__(self, audit_logger: AuditLogger) -> None:
        self._tools: Dict[str, Callable] = {}
        self._audit = audit_logger
        self._cases: Dict[str, CaseRecord] = {}  # in-memory store (prod: database)
        self._feature_store: Dict[str, Dict[str, float]] = {}  # in-memory (prod: Delta/API)

        # Register built-in tools
        self.register("get_transaction_features", self._get_transaction_features)
        self.register("score_risk", self._score_risk)
        self.register("check_policy", self._check_policy)
        self.register("write_audit_event", self._write_audit_event)
        self.register("create_case", self._create_case)

    def register(self, name: str, fn: Callable) -> None:
        """Register a tool function."""
        self._tools[name] = fn
        logger.debug("Registered MCP tool: %s", name)

    def call(self, name: str, **kwargs: Any) -> Any:
        """Dispatch a tool call with logging."""
        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name}")

        start = time.monotonic()
        result = self._tools[name](**kwargs)
        latency = (time.monotonic() - start) * 1000

        logger.debug("Tool %s completed in %.1fms", name, latency)
        return result

    def load_features(self, features_map: Dict[str, Dict[str, float]]) -> None:
        """Bulk-load features into the in-memory feature store."""
        self._feature_store.update(features_map)
        logger.info("Loaded %d transaction features into MCP store", len(features_map))

    # ── Tool implementations ─────────────────────────────────────

    def _get_transaction_features(
        self, transaction_id: str
    ) -> Dict[str, float]:
        """Retrieve pre-computed features for a transaction.

        In production: queries the gold Delta table via Databricks SQL or
        a feature serving endpoint.
        """
        features = self._feature_store.get(transaction_id, {})
        if not features:
            logger.warning("No features found for transaction_id=%s", transaction_id)
        return features

    def _score_risk(self, features: Dict[str, float]) -> float:
        """Score risk from a feature vector using the rules model.

        This delegates to the RiskScoringAgent's logic.
        """
        from .agents.risk_scoring import score_risk

        # Build a minimal transaction dict from features
        tx = {"amount": features.get("amount", features.get("Amount", 0.0))}
        risk_score, _, _ = score_risk(tx, features)
        return risk_score

    def _check_policy(
        self, action: str, context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Run policy checks.

        `context` must contain transaction data and customer context.
        """
        from .policy import run_all_policies

        transaction = context.get("transaction", {})
        customer_ctx = context.get("customer_context", {})
        results = run_all_policies(transaction, customer_ctx)
        return [r.model_dump(mode="json") for r in results]

    def _write_audit_event(self, event: Dict[str, Any]) -> str:
        """Write an audit event to storage."""
        audit_event = AgentEventLog(**event)
        return self._audit.write_event(audit_event)

    def _create_case(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """Create an escalation case from an agent decision."""
        case = CaseRecord(**decision)
        self._cases[case.case_id] = case
        logger.info("Created case %s for transaction %s", case.case_id, case.transaction_id)
        return case.model_dump(mode="json")

    @property
    def tool_names(self) -> List[str]:
        return list(self._tools.keys())
