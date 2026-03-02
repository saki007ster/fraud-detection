# Databricks notebook source
# MAGIC %md
# MAGIC # 04 — Gold Features
# MAGIC
# MAGIC Reads **silver.creditcard_cleaned** and produces the final feature table
# MAGIC used for model training, scoring, and agent evaluation.
# MAGIC
# MAGIC - Assembles a Spark ML `features` vector from V1–V28, normalised_amount, hour_of_day
# MAGIC - Preserves `label` column for evaluation
# MAGIC - Adds a `transaction_id` (deterministic hash) for downstream traceability

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

SILVER_TABLE = "silver.creditcard_cleaned"
GOLD_TABLE = "gold.cc_features"
DATABASE = "gold"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Read Silver

# COMMAND ----------

silver_df = spark.table(SILVER_TABLE)
print(f"Silver rows: {silver_df.count():,}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Generate Transaction ID
# MAGIC
# MAGIC The Kaggle dataset has no natural primary key.  We create a deterministic
# MAGIC `transaction_id` by hashing `Time + Amount + V1 + V2` (collision probability
# MAGIC is negligible for 284K rows).  This gives us a stable key for agent replay.

# COMMAND ----------

from pyspark.sql import functions as F

silver_with_id = silver_df.withColumn(
    "transaction_id",
    F.sha2(
        F.concat_ws(
            "|",
            F.col("Time").cast("string"),
            F.col("Amount").cast("string"),
            F.col("V1").cast("string"),
            F.col("V2").cast("string"),
        ),
        256,
    ),
)

# Verify uniqueness
total = silver_with_id.count()
distinct = silver_with_id.select("transaction_id").distinct().count()
print(f"Total: {total:,}, Distinct IDs: {distinct:,}, Collisions: {total - distinct}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Assemble Feature Vector

# COMMAND ----------

from pyspark.ml.feature import VectorAssembler

feature_cols = [f"V{i}" for i in range(1, 29)] + ["normalised_amount", "hour_of_day"]

assembler = VectorAssembler(
    inputCols=feature_cols,
    outputCol="features",
    handleInvalid="skip",  # drop rows with NaN/null features
)

gold_df = assembler.transform(silver_with_id)

# Select final columns for the gold table
gold_final = gold_df.select(
    "transaction_id",
    "transaction_date",
    "transaction_timestamp",
    "Time",
    "Amount",
    "normalised_amount",
    "log_amount",
    "hour_of_day",
    *[f"V{i}" for i in range(1, 29)],
    "features",
    "label",
    "dataset_source",
)

print(f"Gold rows: {gold_final.count():,}")
gold_final.printSchema()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write to Delta — Gold

# COMMAND ----------

spark.sql(f"CREATE DATABASE IF NOT EXISTS {DATABASE}")

(
    gold_final.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(GOLD_TABLE)
)

row_count = spark.table(GOLD_TABLE).count()
print(f"✅ Wrote {row_count:,} rows to {GOLD_TABLE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify

# COMMAND ----------

display(
    spark.sql(f"""
        SELECT
            label,
            COUNT(*) AS cnt,
            ROUND(AVG(Amount), 2) AS avg_amount,
            MIN(transaction_date) AS min_date,
            MAX(transaction_date) AS max_date
        FROM {GOLD_TABLE}
        GROUP BY label
    """)
)
