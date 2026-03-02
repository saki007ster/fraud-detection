# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — Bronze Ingest
# MAGIC
# MAGIC Writes the raw Kaggle CSV into a **bronze** Delta table with:
# MAGIC - Synthetic date derived from the `Time` column
# MAGIC - Ingestion metadata columns
# MAGIC - Partition by derived date
# MAGIC
# MAGIC ### Date Derivation (Tradeoff Documented)
# MAGIC
# MAGIC The `Time` column is seconds elapsed from the first transaction in the dataset
# MAGIC (spanning ~48 hours). We map this to a synthetic calendar date starting from
# MAGIC `2013-09-01` to enable meaningful date-based partitioning and downstream
# MAGIC time-series analysis. **This is NOT the real transaction date** — it is a
# MAGIC synthetic mapping for demonstration purposes.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

STORAGE_ACCOUNT = dbutils.widgets.get("storage_account") if "dbutils" in dir() else "frauddetectionadls"
RAW_CONTAINER = "raw"
RAW_PATH = f"abfss://{RAW_CONTAINER}@{STORAGE_ACCOUNT}.dfs.core.windows.net/creditcardfraud/creditcard.csv"

USE_LOCAL_FILE = False
DATA_LOCAL_PATH = "/dbfs/FileStore/creditcardfraud/creditcard.csv"

BRONZE_TABLE = "bronze.creditcard_transactions"
DATABASE = "bronze"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Read Raw Data

# COMMAND ----------

from pyspark.sql.types import (
    StructType,
    StructField,
    DoubleType,
    IntegerType,
)

fields = [StructField("Time", DoubleType(), nullable=False)]
for i in range(1, 29):
    fields.append(StructField(f"V{i}", DoubleType(), nullable=True))
fields.append(StructField("Amount", DoubleType(), nullable=False))
fields.append(StructField("Class", IntegerType(), nullable=False))

CREDIT_CARD_SCHEMA = StructType(fields)

data_path = DATA_LOCAL_PATH if USE_LOCAL_FILE else RAW_PATH
raw_df = (
    spark.read.format("csv")
    .option("header", "true")
    .schema(CREDIT_CARD_SCHEMA)
    .load(data_path)
)

print(f"Read {raw_df.count():,} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Add Metadata Columns + Derive Date

# COMMAND ----------

from pyspark.sql import functions as F

BASE_DATE = "2013-09-01"

bronze_df = (
    raw_df
    # Derive a synthetic date from Time (seconds offset from base date)
    .withColumn(
        "transaction_date",
        F.to_date(
            F.from_unixtime(
                F.unix_timestamp(F.lit(BASE_DATE), "yyyy-MM-dd") + F.col("Time")
            )
        ),
    )
    # Derive a synthetic timestamp
    .withColumn(
        "transaction_timestamp",
        F.from_unixtime(
            F.unix_timestamp(F.lit(BASE_DATE), "yyyy-MM-dd") + F.col("Time")
        ).cast("timestamp"),
    )
    # Ingestion metadata
    .withColumn("ingestion_timestamp", F.current_timestamp())
    .withColumn("source_file", F.lit(data_path))
    .withColumn("dataset_source", F.lit("kaggle"))
)

print("Schema with metadata:")
bronze_df.printSchema()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write to Delta — Bronze

# COMMAND ----------

spark.sql(f"CREATE DATABASE IF NOT EXISTS {DATABASE}")

(
    bronze_df.write
    .format("delta")
    .mode("overwrite")
    .partitionBy("transaction_date")
    .option("overwriteSchema", "true")
    .saveAsTable(BRONZE_TABLE)
)

row_count = spark.table(BRONZE_TABLE).count()
print(f"✅ Wrote {row_count:,} rows to {BRONZE_TABLE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify

# COMMAND ----------

display(spark.sql(f"""
    SELECT transaction_date, COUNT(*) AS cnt, SUM(Class) AS fraud_count
    FROM {BRONZE_TABLE}
    GROUP BY transaction_date
    ORDER BY transaction_date
"""))
