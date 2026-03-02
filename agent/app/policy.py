"""
Policy engine — evaluates compliance rules against transaction context.

Policies implemented:
  1. velocity_24h    — Max transactions per customer in 24h window
  2. geo_mismatch    — Country differs from customer's usual country
  3. device_mismatch — Device ID differs from customer's known device
  4. amount_threshold — Single transaction above configurable limit

Each policy returns a PolicyCheckResult with pass/fail/warn verdict.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .schemas import PolicyCheckResult, PolicyVerdict

logger = logging.getLogger(__name__)

# ── Default thresholds ───────────────────────────────────────────────

DEFAULT_THRESHOLDS = {
    "velocity_24h_max": 10,
    "amount_high_threshold": 2000.0,
    "amount_critical_threshold": 5000.0,
}


# ── Individual policy checks ────────────────────────────────────────

def check_velocity(
    transaction: Dict[str, Any],
    context: Dict[str, Any],
    thresholds: Dict[str, Any] = DEFAULT_THRESHOLDS,
) -> PolicyCheckResult:
    """Check if customer exceeded transaction velocity limit.

    `context` should contain `tx_count_24h` — the number of transactions
    by this customer in the last 24 hours.
    """
    tx_count = context.get("tx_count_24h", 0)
    limit = thresholds.get("velocity_24h_max", 10)

    if tx_count > limit:
        verdict = PolicyVerdict.FAIL
        details = f"Customer has {tx_count} transactions in 24h (limit: {limit})"
    elif tx_count > limit * 0.7:
        verdict = PolicyVerdict.WARN
        details = f"Customer nearing velocity limit: {tx_count}/{limit} in 24h"
    else:
        verdict = PolicyVerdict.PASS
        details = f"Velocity OK: {tx_count}/{limit} in 24h"

    return PolicyCheckResult(
        trace_id=transaction.get("trace_id", ""),
        policy_name="velocity_24h",
        verdict=verdict,
        details=details,
        threshold=float(limit),
        observed_value=float(tx_count),
    )


def check_geo_mismatch(
    transaction: Dict[str, Any],
    context: Dict[str, Any],
) -> PolicyCheckResult:
    """Check if transaction country mismatches customer's usual country."""
    tx_country = transaction.get("country", "")
    usual_countries = context.get("usual_countries", [])

    if not usual_countries:
        return PolicyCheckResult(
            trace_id=transaction.get("trace_id", ""),
            policy_name="geo_mismatch",
            verdict=PolicyVerdict.WARN,
            details="No country history available — cannot evaluate geo risk",
        )

    if tx_country not in usual_countries:
        return PolicyCheckResult(
            trace_id=transaction.get("trace_id", ""),
            policy_name="geo_mismatch",
            verdict=PolicyVerdict.FAIL,
            details=f"Country {tx_country} not in usual countries {usual_countries}",
        )

    return PolicyCheckResult(
        trace_id=transaction.get("trace_id", ""),
        policy_name="geo_mismatch",
        verdict=PolicyVerdict.PASS,
        details=f"Country {tx_country} matches usual pattern",
    )


def check_device_mismatch(
    transaction: Dict[str, Any],
    context: Dict[str, Any],
) -> PolicyCheckResult:
    """Check if device_id is known for this customer."""
    device_id = transaction.get("device_id", "")
    known_devices = context.get("known_devices", [])

    if not device_id:
        return PolicyCheckResult(
            trace_id=transaction.get("trace_id", ""),
            policy_name="device_mismatch",
            verdict=PolicyVerdict.WARN,
            details="No device_id provided",
        )

    if not known_devices:
        return PolicyCheckResult(
            trace_id=transaction.get("trace_id", ""),
            policy_name="device_mismatch",
            verdict=PolicyVerdict.WARN,
            details="No device history available",
        )

    if device_id not in known_devices:
        return PolicyCheckResult(
            trace_id=transaction.get("trace_id", ""),
            policy_name="device_mismatch",
            verdict=PolicyVerdict.FAIL,
            details=f"Device {device_id[:12]}... not in known devices",
        )

    return PolicyCheckResult(
        trace_id=transaction.get("trace_id", ""),
        policy_name="device_mismatch",
        verdict=PolicyVerdict.PASS,
        details="Device matches known profile",
    )


def check_amount_threshold(
    transaction: Dict[str, Any],
    thresholds: Dict[str, Any] = DEFAULT_THRESHOLDS,
) -> PolicyCheckResult:
    """Check if transaction amount exceeds risk thresholds."""
    amount = transaction.get("amount", 0.0)
    high = thresholds.get("amount_high_threshold", 2000.0)
    critical = thresholds.get("amount_critical_threshold", 5000.0)

    if amount >= critical:
        verdict = PolicyVerdict.FAIL
        details = f"Amount ${amount:.2f} exceeds critical threshold ${critical:.2f}"
    elif amount >= high:
        verdict = PolicyVerdict.WARN
        details = f"Amount ${amount:.2f} exceeds high threshold ${high:.2f}"
    else:
        verdict = PolicyVerdict.PASS
        details = f"Amount ${amount:.2f} within normal range"

    return PolicyCheckResult(
        trace_id=transaction.get("trace_id", ""),
        policy_name="amount_threshold",
        verdict=verdict,
        details=details,
        threshold=high,
        observed_value=amount,
    )


# ── Aggregate runner ─────────────────────────────────────────────────

def run_all_policies(
    transaction: Dict[str, Any],
    context: Dict[str, Any],
    thresholds: Dict[str, Any] | None = None,
) -> List[PolicyCheckResult]:
    """Run all policy checks and return a list of results."""
    t = thresholds or DEFAULT_THRESHOLDS

    results = [
        check_velocity(transaction, context, t),
        check_geo_mismatch(transaction, context),
        check_device_mismatch(transaction, context),
        check_amount_threshold(transaction, t),
    ]

    failed = [r for r in results if r.verdict == PolicyVerdict.FAIL]
    if failed:
        logger.info(
            "Policy checks: %d/%d FAILED for trace=%s",
            len(failed),
            len(results),
            transaction.get("trace_id", "?"),
        )

    return results
