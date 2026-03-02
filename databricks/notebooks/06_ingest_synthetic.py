# Databricks notebook source
# MAGIC %md
# MAGIC # 06 — Ingest Synthetic Transactions
# MAGIC
# MAGIC Reads synthetic generator output from ADLS `raw/synthetic_transactions/`
# MAGIC and processes it through the same medallion pipeline as the Kaggle data:
# MAGIC
# MAGIC - **Bronze**: `bronze.synthetic_transactions` (raw + metadata)
# MAGIC - **Silver**: Cleaned + normalised (intermediate; written to silver schema)
# MAGIC - **Gold**: `gold.synthetic_features` (feature vector + label + scenario_type)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

STORAGE_ACCOUNT = dbutils.widgets.get("storage_account") if "dbutils" in dir() else "frauddetectionadls"
RAW_CONTAINER = "raw"
RAW_PATH = f"abfss://{RAW_CONTAINER}@{STORAGE_ACCOUNT}.dfs.core.windows.net/synthetic_transactions/"

USE_LOCAL_FILE = False
DATA_LOCAL_PATH = "/dbfs/FileStore/synthetic_transactions/synthetic_transactions.csv"

BRONZE_TABLE = "bronze.synthetic_transactions"
GOLD_TABLE = "gold.synthetic_features"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Read Raw Synthetic Data

# COMMAND ----------

from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
    DoubleType,
    IntegerType,
    TimestampType,
)

synthetic_schema = StructType([
    StructField("transaction_id", StringType(), nullable=False),
    StructField("customer_id", StringType(), nullable=False),
    StructField("merchant_id", StringType(), nullable=False),
    StructField("amount", DoubleType(), nullable=False),
    StructField("currency", StringType(), nullable=True),
    StructField("country", StringType(), nullable=True),
    StructField("channel", StringType(), nullable=True),
    StructField("device_id", StringType(), nullable=True),
    StructField("timestamp", StringType(), nullable=False),  # ISO-8601 string → cast below
    StructField("label", IntegerType(), nullable=False),
    StructField("scenario_type", StringType(), nullable=False),
    StructField("dataset_source", StringType(), nullable=False),
])

data_path = DATA_LOCAL_PATH if USE_LOCAL_FILE else RAW_PATH

raw_df = (
    spark.read.format("csv")
    .option("header", "true")
    .schema(synthetic_schema)
    .load(data_path)
)

print(f"Loaded {raw_df.count():,} synthetic transactions")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Bronze — Add Metadata + Write Delta

# COMMAND ----------

from pyspark.sql import functions as F

bronze_df = (
    raw_df
    .withColumn("transaction_timestamp", F.to_timestamp(F.col("timestamp")))
    .withColumn("transaction_date", F.to_date(F.col("transaction_timestamp")))
    .withColumn("ingestion_timestamp", F.current_timestamp())
    .withColumn("source_file", F.lit(data_path))
    .drop("timestamp")  # replaced by transaction_timestamp
)

spark.sql("CREATE DATABASE IF NOT EXISTS bronze")

(
    bronze_df.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .partitionBy("transaction_date")
    .saveAsTable(BRONZE_TABLE)
)

count = spark.table(BRONZE_TABLE).count()
print(f"✅ Wrote {count:,} rows to {BRONZE_TABLE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Scenario distribution in bronze

# COMMAND ----------

display(
    spark.sql(f"""
        SELECT scenario_type, label, COUNT(*) AS cnt
        FROM {BRONZE_TABLE}
        GROUP BY scenario_type, label
        ORDER BY scenario_type
    """)
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Silver → Gold (Combined)
# MAGIC
# MAGIC For synthetic data the schema is already clean (generator produces
# MAGIC well-typed data).  We apply the same normalisation as notebook 03
# MAGIC and feature assembly as notebook 04 in a single pass.

# COMMAND ----------

# Compute amount stats for normalisation
amount_stats = bronze_df.select(
    F.mean("amount").alias("mean_amount"),
    F.stddev("amount").alias("std_amount"),
).collect()[0]

mean_amt = amount_stats["mean_amount"]
std_amt = amount_stats["std_amount"] or 1.0  # guard div-by-zero

gold_df = (
    bronze_df
    .withColumn(
        "normalised_amount",
        (F.col("amount") - F.lit(mean_amt)) / F.lit(std_amt),
    )
    .withColumn("log_amount", F.log1p(F.abs(F.col("amount"))))
    .withColumn("hour_of_day", F.hour(F.col("transaction_timestamp")))
)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Feature Vector Assembly
# MAGIC
# MAGIC The synthetic data does **not** have V1–V28 PCA components (those are
# MAGIC specific to the Kaggle dataset).  Instead we build a feature vector from
# MAGIC the available numeric signals.  The agent system uses `amount`,
# MAGIC `normalised_amount`, `hour_of_day` plus scenario metadata for scoring.

# COMMAND ----------

from pyspark.ml.feature import VectorAssembler

# Available numeric features for synthetic data
feature_cols = ["amount", "normalised_amount", "log_amount", "hour_of_day"]

assembler = VectorAssembler(
    inputCols=feature_cols,
    outputCol="features",
    handleInvalid="skip",
)

gold_assembled = assembler.transform(gold_df)

gold_final = gold_assembled.select(
    "transaction_id",
    "customer_id",
    "merchant_id",
    "amount",
    "normalised_amount",
    "log_amount",
    "currency",
    "country",
    "channel",
    "device_id",
    "transaction_date",
    "transaction_timestamp",
    "hour_of_day",
    "features",
    "label",
    "scenario_type",
    "dataset_source",
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write Gold

# COMMAND ----------

spark.sql("CREATE DATABASE IF NOT EXISTS gold")

(
    gold_final.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(GOLD_TABLE)
)

count = spark.table(GOLD_TABLE).count()
print(f"✅ Wrote {count:,} rows to {GOLD_TABLE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify

# COMMAND ----------

display(
    spark.sql(f"""
        SELECT
            scenario_type,
            label,
            COUNT(*) AS cnt,
            ROUND(AVG(amount), 2) AS avg_amount,
            ROUND(MIN(amount), 2) AS min_amount,
            ROUND(MAX(amount), 2) AS max_amount
        FROM {GOLD_TABLE}
        GROUP BY scenario_type, label
        ORDER BY scenario_type
    """)
)
