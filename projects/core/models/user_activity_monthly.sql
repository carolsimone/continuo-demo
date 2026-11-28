{{ config(materialized='table', tags=['daily']) }}

WITH users AS (

    SELECT
        user_id::int                                      AS user_id,
        DATE_TRUNC('month', created_at::timestamp)::date  AS acquisition_month
    FROM {{ ref('seed_users') }}

),

monthly AS (

    SELECT
        user_id::int                                      AS user_id,
        DATE_TRUNC('month', created_at::timestamp)::date  AS activity_month,
        COUNT(*)                                          AS transaction_count,
        SUM(amount_eur)                                   AS volume_eur,
        SUM(fee_amount_eur)                               AS fee_revenue_eur
    FROM {{ ref('daily_transactions') }}
    GROUP BY 1, 2

),

last_month AS (

    SELECT MAX(activity_month) AS activity_month
    FROM monthly

),

spine AS (

    SELECT
        u.user_id,
        u.acquisition_month,
        m::date AS activity_month
    FROM users u
    CROSS JOIN last_month l
    CROSS JOIN LATERAL generate_series(u.acquisition_month, l.activity_month, INTERVAL '1 month') AS m

),

filled AS (

    SELECT
        s.user_id,
        s.activity_month,
        s.acquisition_month,
        (DATE_PART('year', s.activity_month) - DATE_PART('year', s.acquisition_month)) * 12
            + DATE_PART('month', s.activity_month) - DATE_PART('month', s.acquisition_month)
                                                  AS months_since_acquisition,
        COALESCE(m.transaction_count, 0)          AS transaction_count,
        COALESCE(m.volume_eur, 0)                 AS volume_eur,
        COALESCE(m.fee_revenue_eur, 0)            AS fee_revenue_eur
    FROM spine s
    LEFT JOIN monthly m
        ON  m.user_id = s.user_id
        AND m.activity_month = s.activity_month

)

SELECT
    user_id,
    activity_month,
    acquisition_month,
    months_since_acquisition::int                 AS months_since_acquisition,
    transaction_count,
    volume_eur,
    fee_revenue_eur,
    SUM(fee_revenue_eur) OVER (
        PARTITION BY user_id
        ORDER BY activity_month
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    )                                             AS cumulative_fee_revenue_eur,
    transaction_count > 0                         AS is_active,
    COALESCE(LAG(transaction_count > 0) OVER (
        PARTITION BY user_id
        ORDER BY activity_month
    ), false)                                     AS was_active_last_month
FROM filled
