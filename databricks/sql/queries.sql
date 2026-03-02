-- ============================================================
-- Fraud Detection Platform — Analytical Queries
-- Run against the Delta tables created by notebooks 01–05.
-- ============================================================

-- ─────────────────────────────────────────────────────────────
-- 1. Overall fraud rate (Kaggle dataset)
-- ─────────────────────────────────────────────────────────────
SELECT
    COUNT(*)                          AS total_transactions,
    SUM(label)                        AS fraud_count,
    COUNT(*) - SUM(label)             AS legit_count,
    ROUND(SUM(label) / COUNT(*), 6)   AS fraud_rate
FROM gold.cc_features
WHERE dataset_source = 'kaggle';


-- ─────────────────────────────────────────────────────────────
-- 2. Class distribution with amount statistics
-- ─────────────────────────────────────────────────────────────
SELECT
    label,
    COUNT(*)                     AS cnt,
    ROUND(MIN(Amount), 2)        AS min_amount,
    ROUND(AVG(Amount), 2)        AS avg_amount,
    ROUND(MAX(Amount), 2)        AS max_amount,
    ROUND(STDDEV(Amount), 2)     AS std_amount,
    ROUND(PERCENTILE(Amount, 0.5), 2) AS median_amount
FROM gold.cc_features
GROUP BY label;


-- ─────────────────────────────────────────────────────────────
-- 3. Hourly fraud pattern
-- ─────────────────────────────────────────────────────────────
SELECT
    hour_of_day,
    COUNT(*)                        AS total_tx,
    SUM(label)                      AS fraud_tx,
    ROUND(SUM(label) / COUNT(*), 6) AS fraud_rate
FROM gold.cc_features
GROUP BY hour_of_day
ORDER BY hour_of_day;


-- ─────────────────────────────────────────────────────────────
-- 4. Daily transaction volume
-- ─────────────────────────────────────────────────────────────
SELECT
    transaction_date,
    COUNT(*)       AS total_tx,
    SUM(label)     AS fraud_tx
FROM gold.cc_features
GROUP BY transaction_date
ORDER BY transaction_date;


-- ─────────────────────────────────────────────────────────────
-- 5. Baseline model evaluation results
-- ─────────────────────────────────────────────────────────────
SELECT
    model_version,
    dataset,
    pr_auc,
    roc_auc,
    fraud_precision,
    fraud_recall,
    f1_weighted,
    tp, fp, tn, fn,
    evaluated_at
FROM metrics.model_eval
ORDER BY evaluated_at DESC;


-- ─────────────────────────────────────────────────────────────
-- 6. Agent flagged rate (populated after Prompt 5)
-- ─────────────────────────────────────────────────────────────
SELECT
    decision,
    COUNT(*)                          AS cnt,
    ROUND(COUNT(*) / SUM(COUNT(*)) OVER(), 4) AS pct
FROM results.agent_decisions
GROUP BY decision
ORDER BY cnt DESC;


-- ─────────────────────────────────────────────────────────────
-- 7. Per-scenario accuracy — synthetic (populated after Prompt 5)
-- ─────────────────────────────────────────────────────────────
SELECT
    scenario_type,
    COUNT(*) AS total,
    SUM(CASE WHEN decision = 'block' AND label = 1 THEN 1
             WHEN decision = 'approve' AND label = 0 THEN 1
             ELSE 0 END) AS correct,
    ROUND(SUM(CASE WHEN decision = 'block' AND label = 1 THEN 1
                    WHEN decision = 'approve' AND label = 0 THEN 1
                    ELSE 0 END) / COUNT(*), 4) AS accuracy
FROM results.agent_decisions
WHERE dataset_source = 'synthetic'
GROUP BY scenario_type
ORDER BY accuracy;
