# Databricks Notebooks

Notebooks for the fraud-detection medallion pipeline.

| Notebook | Prompt | Purpose |
|---|---|---|
| `01_download_or_mount_data.py` | 2 | Read Kaggle CSV from ADLS raw/ |
| `02_bronze_ingest.py` | 2 | Write raw → bronze Delta |
| `03_silver_clean.py` | 2 | Clean, type, normalise |
| `04_gold_features.py` | 2 | Feature engineering |
| `05_eval_baseline.py` | 2 | Baseline ML model eval |
| `06_ingest_synthetic.py` | 3 | Synthetic data ingestion |
| `07_agent_replay_eval.py` | 5 | Agent verification harness |

All notebooks are implemented in their respective prompts.
