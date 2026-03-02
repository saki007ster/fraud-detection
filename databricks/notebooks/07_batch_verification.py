# Databricks notebook source
# MAGIC %md
# MAGIC # 07 — Batch Agent Verification Harness
# MAGIC
# MAGIC This notebook acts as the evaluation harness for the Agentic Fraud System.
# MAGIC It reads from the `gold` Delta tables, calls the FastAPI agent endpoint
# MAGIC for each transaction, and writes the results to `results.agent_decisions`.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

AGENT_URL = dbutils.widgets.get("agent_url") if "dbutils" in dir() else "http://localhost:8000/analyze-transaction"

# Read both datasets and union them
GOLD_SYNTHETIC = "gold.synthetic_features"
GOLD_KAGGLE = "gold.cc_features"
RESULTS_TABLE = "results.agent_decisions"

# For demonstration, we limit the number of rows processed to avoid long runtimes.
# In production, this would be an incremental batch (e.g. streaming or yesterday's data).
SAMPLE_SIZE_SYNTHETIC = 1000
SAMPLE_SIZE_KAGGLE = 1000

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load Data to Verify

# COMMAND ----------

spark.sql("CREATE DATABASE IF NOT EXISTS results")

try:
    synth_df = spark.table(GOLD_SYNTHETIC).limit(SAMPLE_SIZE_SYNTHETIC)
    kaggle_df = spark.table(GOLD_KAGGLE).limit(SAMPLE_SIZE_KAGGLE)

    # Align columns explicitly just in case (we only need the fields required by the API)
    cols = ["transaction_id", "amount", "country", "channel", "device_id", "label", "dataset_source", "scenario_type"]
    
    # Handle missing columns in Kaggle data by adding null/default columns
    if "scenario_type" not in kaggle_df.columns:
        from pyspark.sql import functions as F
        kaggle_df = kaggle_df.withColumn("scenario_type", F.lit("unknown"))
        
    if "device_id" not in kaggle_df.columns:
        from pyspark.sql import functions as F
        kaggle_df = kaggle_df.withColumn("device_id", F.lit(None).cast("string"))

    df_to_score = synth_df.select(*cols).union(kaggle_df.select(*cols))
    print(f"Loaded {df_to_score.count()} total transactions for agent verification")
except Exception as e:
    print(f"Warning: Could not load data. Ensure notebooks 01-06 have been run. {e}")
    dbutils.notebook.exit("Data not found")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Pandas UDF for parallel API Invocation
# MAGIC
# MAGIC We use `mapInPandas` to efficiently batch calls to the external REST API
# MAGIC from spark executor nodes.

# COMMAND ----------

import pandas as pd
import requests
import json
import time

def call_agent_api(iterator):
    """
    Pandas Iterator UDF for efficient HTTP calls per partition.
    Yields Pandas DataFrames containing the API responses.
    """
    for pdf in iterator:
        results = []
        for _, row in pdf.iterrows():
            payload = {
                "transaction_id": row["transaction_id"],
                "customer_id": "unknown", # For Kaggle dataset we don't have this explicitly
                "merchant_id": "unknown",
                "amount": float(row["amount"]),
                "country": row["country"] if pd.notna(row["country"]) else "US",
                "channel": row["channel"] if pd.notna(row["channel"]) else "online",
                "device_id": row["device_id"] if pd.notna(row["device_id"]) else None,
                "dataset_source": row["dataset_source"],
                "label": int(row["label"]),
                "scenario_type": row["scenario_type"]
            }
            
            # Send Request
            start = time.time()
            try:
                resp = requests.post(
                    AGENT_URL, 
                    json=payload, 
                    headers={"Content-Type": "application/json"},
                    timeout=10
                )
                if resp.status_code == 200:
                    data = resp.json()
                    results.append({
                        "transaction_id": row["transaction_id"],
                        "dataset_source": row["dataset_source"],
                        "scenario_type": row["scenario_type"],
                        "label": int(row["label"]),
                        "decision": data.get("decision", "error"),
                        "risk_score": float(data.get("risk_score", 0.0)),
                        "risk_level": data.get("risk_level", "unknown"),
                        "llm_used": bool(data.get("llm_used", False)),
                        "latency_ms": (time.time() - start) * 1000,
                        "reasons": json.dumps(data.get("reasons", []))
                    })
                else:
                    results.append({
                        "transaction_id": row["transaction_id"],
                        "dataset_source": row["dataset_source"],
                        "scenario_type": row["scenario_type"],
                        "label": int(row["label"]),
                        "decision": "api_error",
                        "risk_score": 0.0,
                        "risk_level": "unknown",
                        "llm_used": False,
                        "latency_ms": (time.time() - start) * 1000,
                        "reasons": f"HTTP {resp.status_code}: {resp.text}"
                    })
            except Exception as e:
                results.append({
                    "transaction_id": row["transaction_id"],
                    "dataset_source": row["dataset_source"],
                    "scenario_type": row["scenario_type"],
                    "label": int(row["label"]),
                    "decision": "request_failed",
                    "risk_score": 0.0,
                    "risk_level": "unknown",
                    "llm_used": False,
                    "latency_ms": (time.time() - start) * 1000,
                    "reasons": str(e)
                })
        
        yield pd.DataFrame(results)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Execute Verification Batch

# COMMAND ----------

from pyspark.sql.types import StructType, StructField, StringType, DoubleType, IntegerType, BooleanType

result_schema = StructType([
    StructField("transaction_id", StringType(), True),
    StructField("dataset_source", StringType(), True),
    StructField("scenario_type", StringType(), True),
    StructField("label", IntegerType(), True),
    StructField("decision", StringType(), True),
    StructField("risk_score", DoubleType(), True),
    StructField("risk_level", StringType(), True),
    StructField("llm_used", BooleanType(), True),
    StructField("latency_ms", DoubleType(), True),
    StructField("reasons", StringType(), True),
])

# Process the data
# Repartition to control concurrency against the FastAPI server
concurrency = 4
results_df = df_to_score.repartition(concurrency).mapInPandas(call_agent_api, schema=result_schema)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write Results to Delta Lake

# COMMAND ----------

(
    results_df.write
    .format("delta")
    .mode("overwrite")  # overwrite for easy re-runs during development
    .option("overwriteSchema", "true")
    .saveAsTable(RESULTS_TABLE)
)

print(f"✅ Agent decisions written to {RESULTS_TABLE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verification Summary

# COMMAND ----------

display(spark.sql(f"""
    SELECT 
        dataset_source,
        decision, 
        COUNT(*) as count,
        ROUND(AVG(latency_ms), 2) as avg_latency_ms,
        SUM(INT(llm_used)) as llm_calls
    FROM {RESULTS_TABLE}
    GROUP BY dataset_source, decision
    ORDER BY dataset_source, count DESC
"""))
