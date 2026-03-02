# Databricks notebook source
# MAGIC %md
# MAGIC # 05 — Baseline Model Evaluation
# MAGIC
# MAGIC Trains a **Logistic Regression** baseline on `gold.cc_features` and evaluates
# MAGIC precision, recall, F1, and PR-AUC against the `Class` label.
# MAGIC
# MAGIC ### Why Logistic Regression?
# MAGIC - Interpretable coefficients map directly to PCA features
# MAGIC - Fast to train on ~284K rows with Spark ML
# MAGIC - Serves as a floor for agent system comparison
# MAGIC
# MAGIC ### Tradeoff
# MAGIC - LR assumes linear separability — fraud may be nonlinear
# MAGIC - Class imbalance (0.17% fraud) requires weighting or resampling
# MAGIC - We use `weightCol` to handle imbalance rather than SMOTE (simpler, reproducible)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

GOLD_TABLE = "gold.cc_features"
METRICS_TABLE = "metrics.model_eval"
METRICS_DATABASE = "metrics"

TEST_FRACTION = 0.2
SEED = 42
MODEL_VERSION = "lr-baseline-v1"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load Gold Features

# COMMAND ----------

gold_df = spark.table(GOLD_TABLE)
print(f"Gold rows: {gold_df.count():,}")

# Class distribution
gold_df.groupBy("label").count().show()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Train / Test Split
# MAGIC
# MAGIC Stratified split — preserves fraud ratio in both sets.

# COMMAND ----------

train_df, test_df = gold_df.randomSplit([1 - TEST_FRACTION, TEST_FRACTION], seed=SEED)

print(f"Train: {train_df.count():,}  Test: {test_df.count():,}")
print("Train label distribution:")
train_df.groupBy("label").count().show()
print("Test label distribution:")
test_df.groupBy("label").count().show()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Class Weight Calculation
# MAGIC
# MAGIC To handle the severe class imbalance (~0.17% fraud), we assign higher weight
# MAGIC to the minority class.

# COMMAND ----------

from pyspark.sql import functions as F

total = train_df.count()
fraud_count = train_df.filter(F.col("label") == 1).count()
legit_count = total - fraud_count

# Balance ratio: weight fraud class higher
weight_legit = 1.0
weight_fraud = legit_count / fraud_count if fraud_count > 0 else 1.0

print(f"Legit: {legit_count:,} (weight {weight_legit:.2f})")
print(f"Fraud: {fraud_count:,} (weight {weight_fraud:.2f})")

train_weighted = train_df.withColumn(
    "weight",
    F.when(F.col("label") == 1, F.lit(weight_fraud)).otherwise(F.lit(weight_legit)),
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Train Logistic Regression

# COMMAND ----------

from pyspark.ml.classification import LogisticRegression

lr = LogisticRegression(
    featuresCol="features",
    labelCol="label",
    weightCol="weight",
    maxIter=100,
    regParam=0.01,
    elasticNetParam=0.0,  # L2 regularisation
)

lr_model = lr.fit(train_weighted)
print(f"Coefficients count: {len(lr_model.coefficients)}")
print(f"Intercept: {lr_model.intercept:.4f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Predict on Test Set

# COMMAND ----------

predictions = lr_model.transform(test_df)
predictions.select("transaction_id", "label", "prediction", "probability").show(10, truncate=False)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Evaluation Metrics

# COMMAND ----------

from pyspark.ml.evaluation import (
    BinaryClassificationEvaluator,
    MulticlassClassificationEvaluator,
)

# PR-AUC (preferred for imbalanced datasets)
pr_evaluator = BinaryClassificationEvaluator(
    labelCol="label",
    rawPredictionCol="rawPrediction",
    metricName="areaUnderPR",
)
pr_auc = pr_evaluator.evaluate(predictions)

# ROC-AUC
roc_evaluator = BinaryClassificationEvaluator(
    labelCol="label",
    rawPredictionCol="rawPrediction",
    metricName="areaUnderROC",
)
roc_auc = roc_evaluator.evaluate(predictions)

# Precision, Recall, F1
precision_eval = MulticlassClassificationEvaluator(
    labelCol="label", predictionCol="prediction", metricName="weightedPrecision"
)
recall_eval = MulticlassClassificationEvaluator(
    labelCol="label", predictionCol="prediction", metricName="weightedRecall"
)
f1_eval = MulticlassClassificationEvaluator(
    labelCol="label", predictionCol="prediction", metricName="f1"
)

precision = precision_eval.evaluate(predictions)
recall = recall_eval.evaluate(predictions)
f1 = f1_eval.evaluate(predictions)

print(f"PR-AUC:    {pr_auc:.4f}")
print(f"ROC-AUC:   {roc_auc:.4f}")
print(f"Precision: {precision:.4f}")
print(f"Recall:    {recall:.4f}")
print(f"F1:        {f1:.4f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Confusion Matrix

# COMMAND ----------

confusion = (
    predictions.groupBy("label", "prediction")
    .count()
    .orderBy("label", "prediction")
)
display(confusion)

# Detailed breakdown
tp = predictions.filter((F.col("label") == 1) & (F.col("prediction") == 1)).count()
fp = predictions.filter((F.col("label") == 0) & (F.col("prediction") == 1)).count()
tn = predictions.filter((F.col("label") == 0) & (F.col("prediction") == 0)).count()
fn = predictions.filter((F.col("label") == 1) & (F.col("prediction") == 0)).count()

print(f"\nConfusion Matrix:")
print(f"  TP: {tp:,}  FP: {fp:,}")
print(f"  FN: {fn:,}  TN: {tn:,}")

fraud_precision = tp / (tp + fp) if (tp + fp) > 0 else 0
fraud_recall = tp / (tp + fn) if (tp + fn) > 0 else 0
print(f"\nFraud-class precision: {fraud_precision:.4f}")
print(f"Fraud-class recall:    {fraud_recall:.4f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Save Metrics to Delta

# COMMAND ----------

from datetime import datetime

metrics_data = [
    {
        "model_version": MODEL_VERSION,
        "dataset": "kaggle_creditcard",
        "split": "test",
        "test_size": test_df.count(),
        "train_size": train_df.count(),
        "pr_auc": float(pr_auc),
        "roc_auc": float(roc_auc),
        "precision_weighted": float(precision),
        "recall_weighted": float(recall),
        "f1_weighted": float(f1),
        "fraud_precision": float(fraud_precision),
        "fraud_recall": float(fraud_recall),
        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn),
        "evaluated_at": datetime.utcnow().isoformat(),
    }
]

metrics_df = spark.createDataFrame(metrics_data)

spark.sql(f"CREATE DATABASE IF NOT EXISTS {METRICS_DATABASE}")

(
    metrics_df.write
    .format("delta")
    .mode("append")  # append so we keep history across runs
    .option("mergeSchema", "true")
    .saveAsTable(METRICS_TABLE)
)

print(f"✅ Metrics saved to {METRICS_TABLE}")
display(spark.table(METRICS_TABLE))
