"""
TriageAgent — cheap rules + heuristics to decide if further analysis is needed.

The triage agent is the first stage in the pipeline.  It produces a
`triage_score` ∈ [0, 1] based on simple heuristics:
  - Amount outliers
  - Time-of-day risk
  - Feature-based quick signals (if available)

If triage_score < 0.3  → APPROVE directly
If triage_score ≥ 0.7  → needs deeper analysis (possibly LLM)
Otherwise             → rules-only scoring, no LLM
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

from ..schemas import DecisionAction

logger = logging.getLogger(__name__)


def triage(
    transaction: Dict[str, Any],
    features: Dict[str, float] | None = None,
) -> Tuple[float, DecisionAction | None, str]:
    """Evaluate a transaction with cheap heuristics.

    Returns:
        (triage_score, early_decision_or_None, reason)
    """
    score = 0.0
    reasons = []

    amount = transaction.get("amount", 0.0)
    hour = transaction.get("hour_of_day")
    channel = transaction.get("channel", "online")

    # ── Amount signals ───────────────────────────────────────────
    if amount > 5000:
        score += 0.35
        reasons.append(f"Very high amount: ${amount:.2f}")
    elif amount > 2000:
        score += 0.2
        reasons.append(f"High amount: ${amount:.2f}")
    elif amount < 1.0 and amount > 0:
        score += 0.15
        reasons.append(f"Micro-charge: ${amount:.2f} (card testing signal)")

    # Negative amount = refund
    if amount < 0:
        score += 0.1
        reasons.append("Refund transaction")

    # ── Time-of-day risk ─────────────────────────────────────────
    if hour is not None:
        if 0 <= hour <= 5:
            score += 0.15
            reasons.append(f"Late-night transaction (hour={hour})")

    # ── Channel risk ─────────────────────────────────────────────
    if channel == "atm":
        score += 0.05
    elif channel == "online":
        score += 0.02

    # ── Feature-based signals (V-columns from Kaggle, if present) ─
    if features:
        # V14 and V17 are empirically strong fraud indicators in the Kaggle dataset
        v14 = features.get("V14", 0.0)
        v17 = features.get("V17", 0.0)
        if v14 < -5:
            score += 0.25
            reasons.append(f"V14={v14:.2f} (strong fraud signal)")
        if v17 < -5:
            score += 0.15
            reasons.append(f"V17={v17:.2f} (fraud signal)")

    # Clamp to [0, 1]
    score = min(max(score, 0.0), 1.0)

    # Early decision for low-risk
    if score < 0.3:
        reason = "Low-risk triage: " + ("; ".join(reasons) if reasons else "no risk signals")
        return score, DecisionAction.APPROVE, reason

    reason = "; ".join(reasons) if reasons else "moderate risk signals"
    return score, None, reason
