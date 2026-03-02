"""
InvestigationAgent — LLM-powered analysis for uncertain / high-risk cases.

Only called when:
  1. Triage score ≥ 0.7 AND at least one policy check failed.
  2. LLM call budget has not been exhausted.

Uses a fixed system prompt (injection-resistant) and structured input.
Raw prompts are NEVER stored — only the SHA-256 hash.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from ..llm_client import LLMClient
from ..schemas import DecisionAction, PolicyCheckResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a financial fraud analyst AI.  You receive structured transaction data
and policy check results.  Provide a concise fraud risk assessment.

Rules:
- Respond ONLY with valid JSON matching this schema:
  {"decision": "approve|flag|block|escalate", "confidence": 0.0-1.0, "reasoning": "..."}
- Do NOT include any personal data in your response.
- Base your decision on the provided evidence only.
- If uncertain, choose "escalate".
"""


def investigate(
    transaction: Dict[str, Any],
    risk_score: float,
    policy_results: List[PolicyCheckResult],
    llm_client: LLMClient,
) -> Dict[str, Any]:
    """Run LLM investigation on a flagged transaction.

    Returns:
        {
            "decision": DecisionAction,
            "reasoning": str,
            "confidence": float,
            "llm_used": bool,
            "prompt_hash": str | None,
            "latency_ms": float,
        }
    """
    # Build structured user prompt (no PII — only IDs and features)
    user_prompt = json.dumps(
        {
            "transaction_id": transaction.get("transaction_id", ""),
            "amount": transaction.get("amount", 0),
            "country": transaction.get("country", ""),
            "channel": transaction.get("channel", ""),
            "risk_score": risk_score,
            "policy_failures": [
                {"policy": r.policy_name, "verdict": r.verdict.value, "details": r.details}
                for r in policy_results
                if r.verdict != "pass"
            ],
        },
        indent=2,
    )

    # Check if we should actually call the LLM
    if not llm_client.should_call(risk_score):
        logger.info("LLM call skipped (score=%.2f, budget=%d)", risk_score, llm_client.call_count)
        return {
            "decision": DecisionAction.ESCALATE,
            "reasoning": "LLM call gated — escalating to human review",
            "confidence": 0.0,
            "llm_used": False,
            "prompt_hash": None,
            "latency_ms": 0.0,
        }

    # Call LLM
    result = llm_client.call(SYSTEM_PROMPT, user_prompt)

    # Parse structured response
    decision, reasoning, confidence = _parse_llm_response(result["response"])

    return {
        "decision": decision,
        "reasoning": reasoning,
        "confidence": confidence,
        "llm_used": not result["cached"],  # cached = no actual API call
        "prompt_hash": result["prompt_hash"],
        "latency_ms": result["latency_ms"],
    }


def _parse_llm_response(
    response: str,
) -> tuple[DecisionAction, str, float]:
    """Parse the structured JSON response from the LLM.

    Falls back to ESCALATE if parsing fails (defensive).
    """
    try:
        data = json.loads(response)
        decision_str = data.get("decision", "escalate").lower()
        decision_map = {
            "approve": DecisionAction.APPROVE,
            "flag": DecisionAction.FLAG,
            "block": DecisionAction.BLOCK,
            "escalate": DecisionAction.ESCALATE,
        }
        decision = decision_map.get(decision_str, DecisionAction.ESCALATE)
        reasoning = data.get("reasoning", "No reasoning provided")
        confidence = float(data.get("confidence", 0.0))
        return decision, reasoning, confidence
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("Failed to parse LLM response: %s", exc)
        return (
            DecisionAction.ESCALATE,
            f"LLM response parse failed — escalating. Raw: {response[:200]}",
            0.0,
        )
