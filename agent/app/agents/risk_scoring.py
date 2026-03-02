"""
RiskScoringAgent — scores transaction risk using gold features.

Uses a lightweight rules-based scoring model that maps feature signals
to a normalised risk score [0, 1].  In production, this would call a
hosted ML model endpoint (e.g., MLflow serving on Databricks).
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, Tuple

from ..schemas import RiskLevel

logger = logging.getLogger(__name__)


def score_risk(
    transaction: Dict[str, Any],
    features: Dict[str, float] | None = None,
) -> Tuple[float, RiskLevel, str]:
    """Score a transaction's fraud risk.

    Returns:
        (risk_score ∈ [0,1], risk_level, explanation)
    """
    score = 0.0
    signals = []

    amount = transaction.get("amount", 0.0)
    normalised_amount = transaction.get("normalised_amount") or (
        features.get("normalised_amount", 0.0) if features else 0.0
    )

    # ── Amount-based scoring ────────────────────────────────────
    if amount > 5000:
        score += 0.3
        signals.append(f"amount=${amount:.2f} >$5K")
    elif amount > 2000:
        score += 0.15
        signals.append(f"amount=${amount:.2f} >$2K")
    elif 0 < amount < 1.0:
        score += 0.2
        signals.append(f"micro-charge ${amount:.2f}")

    # Normalised amount (z-score): large positive = unusual
    if normalised_amount > 3.0:
        score += 0.2
        signals.append(f"normalised_amount={normalised_amount:.2f} (>3σ)")

    # ── Feature vector signals (Kaggle PCA) ─────────────────────
    if features:
        # Key fraud-discriminating V-features (empirically observed)
        for col, threshold, weight in [
            ("V14", -5.0, 0.25),
            ("V17", -5.0, 0.15),
            ("V12", -5.0, 0.10),
            ("V10", -5.0, 0.10),
            ("V3", -5.0, 0.05),
        ]:
            val = features.get(col)
            if val is not None and val < threshold:
                score += weight
                signals.append(f"{col}={val:.2f}")

    # ── Clamp and classify ──────────────────────────────────────
    score = min(max(score, 0.0), 1.0)

    if score >= 0.8:
        level = RiskLevel.CRITICAL
    elif score >= 0.6:
        level = RiskLevel.HIGH
    elif score >= 0.3:
        level = RiskLevel.MEDIUM
    else:
        level = RiskLevel.LOW

    explanation = f"Risk score {score:.2f} ({level.value}): " + (
        "; ".join(signals) if signals else "no significant signals"
    )

    return score, level, explanation
