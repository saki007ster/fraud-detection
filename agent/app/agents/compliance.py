"""
ComplianceAgent — evaluates policy rules against transaction context.

Wraps the policy engine and aggregates results into a compliance verdict.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from ..policy import run_all_policies
from ..schemas import PolicyCheckResult, PolicyVerdict

logger = logging.getLogger(__name__)


def check_compliance(
    transaction: Dict[str, Any],
    context: Dict[str, Any],
) -> Tuple[List[PolicyCheckResult], bool, str]:
    """Run all compliance policies against a transaction.

    Args:
        transaction: Transaction data dict (must include trace_id, amount, country, device_id).
        context: Customer context (tx_count_24h, usual_countries, known_devices).

    Returns:
        (policy_results, any_failed, summary_reason)
    """
    results = run_all_policies(transaction, context)

    failures = [r for r in results if r.verdict == PolicyVerdict.FAIL]
    warnings = [r for r in results if r.verdict == PolicyVerdict.WARN]

    any_failed = len(failures) > 0

    parts = []
    if failures:
        parts.append(f"{len(failures)} policy FAIL: " + ", ".join(r.policy_name for r in failures))
    if warnings:
        parts.append(f"{len(warnings)} policy WARN: " + ", ".join(r.policy_name for r in warnings))
    if not parts:
        parts.append("All policies passed")

    summary = "; ".join(parts)
    return results, any_failed, summary
