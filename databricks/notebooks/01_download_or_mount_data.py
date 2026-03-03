# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Download / Mount Data
# MAGIC
# MAGIC Reads the Kaggle **Credit Card Fraud Detection** CSV from ADLS `raw/` into a Spark DataFrame.
# MAGIC
# MAGIC ## Prerequisites
# MAGIC
# MAGIC The CSV must be placed in your ADLS Gen2 raw container **before** running this notebook:
# MAGIC
# MAGIC ```
# MAGIC abfss://raw@<storage_account>.dfs.core.windows.net/creditcardfraud/creditcard.csv
# MAGIC ```
# MAGIC
# MAGIC ### Option A — Manual upload (Azure Portal)
# MAGIC 1. Go to Storage Account → Containers → `raw`
# MAGIC 2. Create folder `creditcardfraud/`
# MAGIC 3. Upload `creditcard.csv` from [Kaggle](https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud)
# MAGIC
# MAGIC ### Option B — AzCopy (CLI)
# MAGIC ```bash
# MAGIC azcopy login
# MAGIC azcopy copy creditcard.csv "https://<storage_account>.blob.core.windows.net/raw/creditcardfraud/creditcard.csv"
# MAGIC ```
# MAGIC
# MAGIC ### Option C — Local development (no ADLS)
# MAGIC Set `USE_LOCAL_FILE = True` below and place the CSV at `DATA_LOCAL_PATH`.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

# Config — adjust for your environment
STORAGE_ACCOUNT = dbutils.widgets.get("storage_account") if "dbutils" in dir() else "frauddetectionadls"
RAW_CONTAINER = "raw"
RAW_PATH = f"abfss://{RAW_CONTAINER}@{STORAGE_ACCOUNT}.dfs.core.windows.net/creditcard.csv"

# Local fallback for development without ADLS
USE_LOCAL_FILE = False
DATA_LOCAL_PATH = "/dbfs/FileStore/creditcardfraud/creditcard.csv"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Read CSV with Explicit Schema

# COMMAND ----------

from pyspark.sql.types import (
    StructType,
    StructField,
    DoubleType,
    IntegerType,
)

# Build schema: Time(double), V1..V28(double), Amount(double), Class(int)
fields = [StructField("Time", DoubleType(), nullable=False)]
for i in range(1, 29):
    fields.append(StructField(f"V{i}", DoubleType(), nullable=True))
fields.append(StructField("Amount", DoubleType(), nullable=False))
fields.append(StructField("Class", IntegerType(), nullable=False))

CREDIT_CARD_SCHEMA = StructType(fields)

# COMMAND ----------

data_path = DATA_LOCAL_PATH if USE_LOCAL_FILE else RAW_PATH

raw_df = (
    spark.read.format("csv")
    .option("header", "true")
    .schema(CREDIT_CARD_SCHEMA)
    .load(data_path)
)

print(f"Loaded {raw_df.count():,} rows from {data_path}")
raw_df.printSchema()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Quick Validation

# COMMAND ----------

display(raw_df.limit(5))

# COMMAND ----------

# Sanity checks
row_count = raw_df.count()
assert row_count > 280_000, f"Expected ~284,807 rows, got {row_count}"

class_dist = raw_df.groupBy("Class").count().collect()
print("Class distribution:")
for row in class_dist:
    print(f"  Class {row['Class']}: {row['count']:,}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Store as temp view for next notebook
# MAGIC
# MAGIC The raw DataFrame is registered as a temp view so notebook 02 can pick it up,
# MAGIC or notebook 02 can re-read from the same path independently.

# COMMAND ----------

raw_df.createOrReplaceTempView("raw_creditcard")
print("✅ Temp view 'raw_creditcard' created")
