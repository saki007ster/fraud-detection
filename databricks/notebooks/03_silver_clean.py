# Databricks notebook source
# MAGIC %md
# MAGIC # 03 — Silver Clean
# MAGIC
# MAGIC Reads **bronze.creditcard_transactions** and produces a cleaned silver table with:
# MAGIC - Type enforcement and null checks
# MAGIC - `normalised_amount` (z-score standardisation)
# MAGIC - `hour_of_day` feature derived from `Time`
# MAGIC - `log_amount` for skew reduction

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

BRONZE_TABLE = "bronze.creditcard_transactions"
SILVER_TABLE = "silver.creditcard_cleaned"
DATABASE = "silver"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Read Bronze

# COMMAND ----------

bronze_df = spark.table(BRONZE_TABLE)
print(f"Bronze rows: {bronze_df.count():,}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Null Check + Type Enforcement

# COMMAND ----------

from pyspark.sql import functions as F

# Check for nulls in critical columns
critical_cols = ["Time", "Amount", "Class"]
for col_name in critical_cols:
    null_count = bronze_df.filter(F.col(col_name).isNull()).count()
    print(f"  {col_name}: {null_count} nulls")
    assert null_count == 0, f"Unexpected nulls in {col_name}"

# Check V-columns for nulls (informational; PCA components should be complete)
v_cols = [f"V{i}" for i in range(1, 29)]
v_null_counts = bronze_df.select(
    [F.sum(F.col(c).isNull().cast("int")).alias(c) for c in v_cols]
).collect()[0]
total_v_nulls = sum(v_null_counts[c] for c in v_cols)
print(f"  V-columns total nulls: {total_v_nulls}")

# Drop any rows with nulls in V-columns (defensive)
clean_df = bronze_df.dropna(subset=v_cols)
dropped = bronze_df.count() - clean_df.count()
print(f"  Dropped {dropped} rows with null V-features")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Feature Engineering

# COMMAND ----------

# Compute Amount statistics for normalisation
amount_stats = clean_df.select(
    F.mean("Amount").alias("mean_amount"),
    F.stddev("Amount").alias("std_amount"),
).collect()[0]

mean_amount = amount_stats["mean_amount"]
std_amount = amount_stats["std_amount"]
print(f"Amount stats — mean: {mean_amount:.2f}, std: {std_amount:.2f}")

silver_df = (
    clean_df
    # Z-score normalised amount
    .withColumn(
        "normalised_amount",
        (F.col("Amount") - F.lit(mean_amount)) / F.lit(std_amount),
    )
    # Log-transformed amount (handles skew; +1 to avoid log(0))
    .withColumn("log_amount", F.log1p(F.col("Amount")))
    # Hour of day — Time is seconds from first transaction (~48h span)
    .withColumn("hour_of_day", F.hour(F.col("transaction_timestamp")))
    # Rename label for clarity
    .withColumnRenamed("Class", "label")
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write to Delta — Silver

# COMMAND ----------

spark.sql(f"CREATE DATABASE IF NOT EXISTS {DATABASE}")

(
    silver_df.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(SILVER_TABLE)
)

row_count = spark.table(SILVER_TABLE).count()
print(f"✅ Wrote {row_count:,} rows to {SILVER_TABLE}")

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
            ROUND(AVG(normalised_amount), 4) AS avg_norm_amount,
            ROUND(AVG(log_amount), 4) AS avg_log_amount,
            ROUND(AVG(hour_of_day), 1) AS avg_hour
        FROM {SILVER_TABLE}
        GROUP BY label
    """)
)
