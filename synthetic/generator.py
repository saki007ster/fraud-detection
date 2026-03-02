"""
Config-driven synthetic transaction generator.

Usage
─────
  # Generate to local CSV
  python synthetic/generator.py --output ./output/synthetic_transactions.csv

  # Generate to Parquet
  python synthetic/generator.py --output ./output/synthetic_transactions.parquet --format parquet

  # Custom config
  python synthetic/generator.py --config synthetic/config.json --output ./output/

All parameters have sensible defaults.  Override via CLI or config file.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from scenarios import (
    SCENARIO_REGISTRY,
    TxRecord,
    account_takeover,
    card_testing,
    merchant_fraud,
    velocity_attack,
)

# ── Default configuration ────────────────────────────────────────────

DEFAULT_CONFIG: Dict[str, Any] = {
    "seed": 42,
    "num_legitimate": 5000,
    "scenarios": {
        "card_testing": {"count": 20, "num_probes": 10},
        "account_takeover": {"count": 15, "num_txns": 3},
        "merchant_fraud": {"count": 10, "num_customers": 15},
        "velocity_attack": {"count": 15, "num_txns": 20},
    },
    "legitimate": {
        "amount_mean": 88.0,
        "amount_std": 150.0,
        "amount_min": 0.50,
        "amount_max": 3000.0,
        "countries": ["US", "GB", "DE", "FR", "ES", "IT", "NL", "BE"],
        "channels": ["online", "pos", "atm"],
        "channel_weights": [0.6, 0.3, 0.1],
        "num_customers": 500,
        "num_merchants": 200,
        "time_span_days": 30,
    },
}


# ── Legitimate transaction generation ────────────────────────────────

def _generate_legitimate(config: Dict[str, Any], base_time: datetime) -> List[TxRecord]:
    """Generate normal (non-fraud) transactions with realistic distributions."""
    cfg = config["legitimate"]
    num_txns = config["num_legitimate"]

    customers = [f"cust-{uuid.uuid4().hex[:8]}" for _ in range(cfg["num_customers"])]
    merchants = [f"merch-{uuid.uuid4().hex[:8]}" for _ in range(cfg["num_merchants"])]
    devices_by_customer = {c: f"dev-{uuid.uuid4().hex[:8]}" for c in customers}

    txns = []
    for _ in range(num_txns):
        cust = random.choice(customers)
        # Log-normal amount (right-skewed, realistic)
        amount = -1.0
        while amount < cfg["amount_min"] or amount > cfg["amount_max"]:
            amount = round(random.gauss(cfg["amount_mean"], cfg["amount_std"]), 2)
            amount = abs(amount)

        channel = random.choices(cfg["channels"], weights=cfg["channel_weights"], k=1)[0]
        offset_seconds = random.randint(0, cfg["time_span_days"] * 86400)

        txns.append(
            TxRecord(
                customer_id=cust,
                merchant_id=random.choice(merchants),
                amount=amount,
                country=random.choice(cfg["countries"]),
                channel=channel,
                device_id=devices_by_customer[cust],
                timestamp=base_time + timedelta(seconds=offset_seconds),
                label=0,
                scenario_type="legitimate",
            )
        )
    return txns


# ── Scenario injection ──────────────────────────────────────────────

def _generate_fraud_scenarios(config: Dict[str, Any], base_time: datetime) -> List[TxRecord]:
    """Inject labeled fraud scenarios according to config."""
    all_fraud: List[TxRecord] = []
    scenario_cfg = config["scenarios"]

    for scenario_name, params in scenario_cfg.items():
        fn = SCENARIO_REGISTRY.get(scenario_name)
        if fn is None:
            print(f"⚠️  Unknown scenario '{scenario_name}', skipping.")
            continue

        count = params.pop("count", 10)
        for i in range(count):
            # Stagger each scenario instance across the time span
            offset = timedelta(
                hours=random.randint(0, config["legitimate"]["time_span_days"] * 24)
            )
            ts = base_time + offset

            if scenario_name == "merchant_fraud":
                merchant = f"merch-fraud-{i:04d}"
                txns = fn(merchant_id=merchant, base_time=ts, **params)
            else:
                customer = f"cust-fraud-{scenario_name[:4]}-{i:04d}"
                txns = fn(customer_id=customer, base_time=ts, **params)

            all_fraud.extend(txns)

    return all_fraud


# ── Output writers ───────────────────────────────────────────────────

def _write_csv(records: List[Dict[str, Any]], path: str) -> None:
    import csv

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fieldnames = list(records[0].keys())
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    print(f"✅ Wrote {len(records):,} rows to {path}")


def _write_parquet(records: List[Dict[str, Any]], path: str) -> None:
    try:
        import pandas as pd
    except ImportError:
        print("❌ pandas is required for Parquet output: pip install pandas pyarrow")
        raise

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df.to_parquet(path, index=False, engine="pyarrow")
    print(f"✅ Wrote {len(records):,} rows to {path}")


# ── Main ─────────────────────────────────────────────────────────────

def generate(config: Dict[str, Any] | None = None, output: str = "output/synthetic_transactions.csv", fmt: str = "csv") -> List[Dict[str, Any]]:
    """Generate synthetic transactions and write to file.

    Returns the list of transaction dicts for programmatic use.
    """
    if config is None:
        config = DEFAULT_CONFIG.copy()

    random.seed(config.get("seed", 42))
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

    print(f"Generating {config['num_legitimate']:,} legitimate transactions...")
    legit = _generate_legitimate(config, base_time)

    print("Injecting fraud scenarios...")
    fraud = _generate_fraud_scenarios(config, base_time)

    all_txns = legit + fraud
    # Sort by timestamp for realism
    all_txns.sort(key=lambda t: t.timestamp)

    records = [t.to_dict() for t in all_txns]
    print(f"Total: {len(records):,} transactions ({len(legit):,} legit, {len(fraud):,} fraud)")

    # Scenario breakdown
    scenario_counts: Dict[str, int] = {}
    for r in records:
        st = r["scenario_type"]
        scenario_counts[st] = scenario_counts.get(st, 0) + 1
    print("Scenario breakdown:")
    for s, c in sorted(scenario_counts.items()):
        print(f"  {s}: {c:,}")

    # Write output
    if fmt == "parquet":
        _write_parquet(records, output)
    else:
        _write_csv(records, output)

    return records


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic fraud transactions",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to JSON config file (overrides defaults)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="output/synthetic_transactions.csv",
        help="Output file path",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["csv", "parquet"],
        default="csv",
        help="Output format",
    )
    args = parser.parse_args()

    config = DEFAULT_CONFIG.copy()
    if args.config:
        with open(args.config) as f:
            overrides = json.load(f)
        # Deep merge scenarios
        if "scenarios" in overrides:
            config["scenarios"].update(overrides.pop("scenarios"))
        config.update(overrides)

    generate(config=config, output=args.output, fmt=args.format)


if __name__ == "__main__":
    main()
