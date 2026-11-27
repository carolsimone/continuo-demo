{{ config(materialized='table', tags=['daily']) }}

WITH fx AS (

    SELECT
        currency_from,
        currency_to,
        DATE_TRUNC('month', created_at::timestamp)::date  AS fx_month,
        user_id,
        amount_eur,
        fee_amount_eur
    FROM analytics.fx_transactions_eur

),

corridors AS (

    SELECT
        currency_from,
        currency_to,
        fx_month,
        COUNT(*)                 AS transaction_count,
        COUNT(DISTINCT user_id)  AS active_users,
        SUM(amount_eur)          AS volume_eur,
        SUM(fee_amount_eur)      AS fee_revenue_eur
    FROM fx
    GROUP BY 1, 2, 3

)

SELECT
    currency_from,
    currency_to,
    fx_month,
    transaction_count,
    active_users,
    volume_eur,
    fee_revenue_eur,
    ROUND(fee_revenue_eur / NULLIF(volume_eur, 0), 6)                         AS take_rate,
    ROUND(volume_eur / SUM(volume_eur) OVER (PARTITION BY fx_month), 6)       AS share_of_month_volume
FROM corridors
