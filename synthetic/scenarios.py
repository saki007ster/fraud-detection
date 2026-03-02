"""
Fraud scenario definitions for the synthetic transaction generator.

Each scenario is a callable that takes a base transaction context and returns
a list of transactions implementing that fraud pattern.  Every returned
transaction carries `label=1` and a `scenario_type` tag.

Scenarios
─────────
1. card_testing      — Many small charges probing whether a card is active.
2. account_takeover  — New device + geography jump + high-value spend.
3. merchant_fraud    — Merchant with abnormal refund/chargeback behaviour.
4. velocity_attack   — Burst of transactions in a very short window.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List


# ── Helpers ──────────────────────────────────────────────────────────

def _uid() -> str:
    return str(uuid.uuid4())[:12]


def _ts_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class TxRecord:
    """A single generated transaction record."""
    transaction_id: str = field(default_factory=_uid)
    customer_id: str = ""
    merchant_id: str = ""
    amount: float = 0.0
    currency: str = "EUR"
    country: str = "US"
    channel: str = "online"
    device_id: str = ""
    timestamp: datetime = field(default_factory=_ts_now)
    label: int = 0
    scenario_type: str = "legitimate"
    dataset_source: str = "synthetic"

    def to_dict(self) -> Dict[str, Any]:
        d = self.__dict__.copy()
        d["timestamp"] = d["timestamp"].isoformat()
        return d


# ── Scenario implementations ────────────────────────────────────────

def card_testing(
    customer_id: str,
    base_time: datetime,
    *,
    num_probes: int = 10,
    probe_amount_range: tuple = (0.50, 2.00),
    interval_seconds: int = 30,
) -> List[TxRecord]:
    """Many small charges in rapid succession to test if a card is active.

    Pattern: 10–20 micro-charges ($0.50–$2.00) on different merchants
    within a few minutes.
    """
    merchant_pool = [f"merch-test-{i:03d}" for i in range(50)]
    device = f"dev-{_uid()}"
    txns = []
    for i in range(num_probes):
        txns.append(
            TxRecord(
                customer_id=customer_id,
                merchant_id=random.choice(merchant_pool),
                amount=round(random.uniform(*probe_amount_range), 2),
                country=random.choice(["US", "US", "US", "GB"]),  # mostly same country
                channel="online",
                device_id=device,
                timestamp=base_time + timedelta(seconds=i * interval_seconds),
                label=1,
                scenario_type="card_testing",
            )
        )
    return txns


def account_takeover(
    customer_id: str,
    base_time: datetime,
    *,
    normal_country: str = "US",
    normal_device: str | None = None,
    high_amount_range: tuple = (500.0, 5000.0),
    num_txns: int = 3,
) -> List[TxRecord]:
    """New device + geography jump + high-value spend.

    Pattern: The attacker logs in from a new device in a different country
    and makes 2–4 high-value purchases within an hour.
    """
    attack_countries = ["NG", "RU", "BR", "CN"]
    attack_country = random.choice([c for c in attack_countries if c != normal_country])
    attack_device = f"dev-attack-{_uid()}"
    merchants = [f"merch-luxury-{i:03d}" for i in range(20)]

    txns = []
    for i in range(num_txns):
        txns.append(
            TxRecord(
                customer_id=customer_id,
                merchant_id=random.choice(merchants),
                amount=round(random.uniform(*high_amount_range), 2),
                country=attack_country,
                channel="online",
                device_id=attack_device,
                timestamp=base_time + timedelta(minutes=i * random.randint(5, 20)),
                label=1,
                scenario_type="account_takeover",
            )
        )
    return txns


def merchant_fraud(
    merchant_id: str,
    base_time: datetime,
    *,
    num_customers: int = 15,
    refund_ratio: float = 0.6,
    amount_range: tuple = (50.0, 500.0),
) -> List[TxRecord]:
    """Merchant with abnormally high refund/chargeback rate.

    Pattern: A fraudulent merchant processes many charges, then issues
    refunds for a large fraction (>50%) — indicating laundering or
    friendly-fraud collusion.  We model this as a cluster of charges
    on the same merchant from different customers.
    """
    txns = []
    for i in range(num_customers):
        cust = f"cust-victim-{_uid()}"
        amount = round(random.uniform(*amount_range), 2)
        # Original charge
        txns.append(
            TxRecord(
                customer_id=cust,
                merchant_id=merchant_id,
                amount=amount,
                country=random.choice(["US", "GB", "DE", "FR"]),
                channel=random.choice(["online", "pos"]),
                device_id=f"dev-{_uid()}",
                timestamp=base_time + timedelta(hours=i * random.randint(1, 4)),
                label=1,
                scenario_type="merchant_fraud",
            )
        )
        # Refund for a fraction of them
        if random.random() < refund_ratio:
            txns.append(
                TxRecord(
                    customer_id=cust,
                    merchant_id=merchant_id,
                    amount=-amount,  # negative = refund
                    country=txns[-1].country,
                    channel=txns[-1].channel,
                    device_id=txns[-1].device_id,
                    timestamp=txns[-1].timestamp + timedelta(days=random.randint(1, 7)),
                    label=1,
                    scenario_type="merchant_fraud",
                )
            )
    return txns


def velocity_attack(
    customer_id: str,
    base_time: datetime,
    *,
    num_txns: int = 20,
    amount_range: tuple = (10.0, 200.0),
    burst_seconds: int = 5,
) -> List[TxRecord]:
    """Rapid-fire burst of transactions in a very short time window.

    Pattern: 15–25 transactions within 1–2 minutes, often spread across
    multiple merchants and sometimes alternating channels.
    """
    merchants = [f"merch-rapid-{i:03d}" for i in range(30)]
    device = f"dev-velocity-{_uid()}"
    txns = []
    for i in range(num_txns):
        txns.append(
            TxRecord(
                customer_id=customer_id,
                merchant_id=random.choice(merchants),
                amount=round(random.uniform(*amount_range), 2),
                country=random.choice(["US", "GB"]),
                channel=random.choice(["online", "pos", "atm"]),
                device_id=device,
                timestamp=base_time + timedelta(seconds=i * burst_seconds + random.randint(0, 2)),
                label=1,
                scenario_type="velocity_attack",
            )
        )
    return txns


# ── Registry ────────────────────────────────────────────────────────

SCENARIO_REGISTRY = {
    "card_testing": card_testing,
    "account_takeover": account_takeover,
    "merchant_fraud": merchant_fraud,
    "velocity_attack": velocity_attack,
}
