{{ config(materialized='table', tags=['daily']) }}

-- Per-user realized revenue: the fees this user generated over the observation
-- window. The counterpart of marketing_cost_per_user and
-- operational_cost_per_user, and the third input the LTV model needs.
--
-- gross_volume_eur is carried alongside revenue_eur on purpose. Confusing the
-- two is the mistake this whole design exists to correct: volume is what the
-- customer moved, revenue is what we earned on it, and they differ by ~200x.
--
-- Users with no transactions get a row with revenue 0, not NULL -- zero is the
-- truthful value, and an inner join here would silently shrink the LTV
-- population and flatter the ratio.

WITH users AS (

    SELECT
        user_id::int                                      AS user_id,
        created_at::timestamp                             AS acquired_at,
        DATE_TRUNC('month', created_at::timestamp)::date  AS acquisition_month
    FROM {{ ref('seed_users') }}

),

activity AS (

    SELECT
        user_id::int                       AS user_id,
        COUNT(*)                           AS transaction_count,
        ROUND(SUM(amount_eur), 2)          AS gross_volume_eur,
        ROUND(SUM(fee_amount_eur), 2)      AS revenue_eur,
        MIN(created_at::timestamp)         AS first_transaction_at,
        MAX(created_at::timestamp)         AS last_transaction_at
    FROM {{ ref('daily_transactions') }}
    GROUP BY 1

)

SELECT
    u.user_id,
    u.acquired_at,
    u.acquisition_month,
    COALESCE(a.transaction_count, 0)  AS transaction_count,
    COALESCE(a.gross_volume_eur, 0)   AS gross_volume_eur,
    COALESCE(a.revenue_eur, 0)        AS revenue_eur,
    a.first_transaction_at,
    a.last_transaction_at
FROM users u
LEFT JOIN activity a
    ON a.user_id = u.user_id
