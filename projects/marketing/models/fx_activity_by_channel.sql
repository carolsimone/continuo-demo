{{ config(materialized='table', tags=['daily']) }}

WITH acquisitions AS (

    SELECT
        user_id::int  AS user_id,
        channel
    FROM {{ ref('seed_user_acquisition') }}

),

fx AS (

    SELECT
        user_id,
        DATE_TRUNC('month', created_at::timestamp)::date  AS fx_month,
        amount_eur,
        fee_amount_eur
    FROM analytics.fx_transactions_eur

),

first_fx AS (

    SELECT
        user_id,
        MIN(fx_month) AS first_fx_month
    FROM fx
    GROUP BY user_id

)

SELECT
    a.channel,
    f.fx_month,
    COUNT(DISTINCT f.user_id)                                                 AS fx_users,
    COUNT(DISTINCT f.user_id) FILTER (WHERE ff.first_fx_month = f.fx_month)   AS first_time_fx_users,
    COUNT(*)                                                                  AS fx_transaction_count,
    SUM(f.amount_eur)                                                         AS fx_volume_eur,
    SUM(f.fee_amount_eur)                                                     AS fx_fee_revenue_eur
FROM fx f
INNER JOIN acquisitions a
    ON a.user_id = f.user_id
INNER JOIN first_fx ff
    ON ff.user_id = f.user_id
GROUP BY a.channel, f.fx_month
