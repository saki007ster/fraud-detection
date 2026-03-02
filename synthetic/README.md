# Synthetic Transaction Generator

Config-driven generator for realistic labeled fraud scenarios.

## Quick Start

```bash
# Generate 5,000 legit + ~800 fraud transactions to CSV
python synthetic/generator.py --output output/synthetic_transactions.csv

# Generate as Parquet (requires pandas + pyarrow)
python synthetic/generator.py --output output/synthetic_transactions.parquet --format parquet

# Use custom config
python synthetic/generator.py --config synthetic/config.json --output output/
```

## Scenarios

| Scenario | Tag | Pattern | Default Count |
|---|---|---|---|
| **Card Testing** | `card_testing` | 10 micro-charges ($0.50–$2.00) within minutes on different merchants | 20 instances |
| **Account Takeover** | `account_takeover` | New device + geo jump (US→NG/RU/BR/CN) + 3 high-value purchases ($500–$5K) | 15 instances |
| **Merchant Fraud** | `merchant_fraud` | 15 customers charged, 60% refunded — abnormal refund rate indicating laundering | 10 instances |
| **Velocity Attack** | `velocity_attack` | 20 rapid-fire transactions within ~100 seconds across multiple merchants | 15 instances |

## Default Configuration

```json
{
  "seed": 42,
  "num_legitimate": 5000,
  "scenarios": {
    "card_testing":     {"count": 20, "num_probes": 10},
    "account_takeover": {"count": 15, "num_txns": 3},
    "merchant_fraud":   {"count": 10, "num_customers": 15},
    "velocity_attack":  {"count": 15, "num_txns": 20}
  },
  "legitimate": {
    "amount_mean": 88.0,
    "amount_std": 150.0,
    "countries": ["US", "GB", "DE", "FR", "ES", "IT", "NL", "BE"],
    "channels": ["online", "pos", "atm"],
    "channel_weights": [0.6, 0.3, 0.1],
    "num_customers": 500,
    "num_merchants": 200,
    "time_span_days": 30
  }
}
```

## Output Schema

| Column | Type | Description |
|---|---|---|
| `transaction_id` | string | UUID-based unique ID |
| `customer_id` | string | Pseudonymised customer |
| `merchant_id` | string | Pseudonymised merchant |
| `amount` | float | Transaction amount (negative = refund) |
| `currency` | string | ISO-4217 code (default EUR) |
| `country` | string | ISO-3166 country code |
| `channel` | string | `online` / `pos` / `atm` |
| `device_id` | string | Device fingerprint |
| `timestamp` | datetime | ISO-8601 UTC |
| `label` | int | `0`=legit, `1`=fraud |
| `scenario_type` | string | Scenario tag or `legitimate` |
| `dataset_source` | string | Always `synthetic` |

## ADLS Upload

After generation, upload to the raw container:

```bash
azcopy copy output/synthetic_transactions.csv \
  "https://<storage>.blob.core.windows.net/raw/synthetic_transactions/synthetic_transactions.csv"
```

Then run notebook `06_ingest_synthetic.py` to process through the medallion pipeline.
