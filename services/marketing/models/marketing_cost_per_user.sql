{{ config(materialized='table', tags=['daily']) }}

WITH acquisitions AS (

    SELECT
        user_id::int                                       AS user_id,
        channel,
        campaign,
        acquired_at::timestamp                             AS acquired_at,
        DATE_TRUNC('month', acquired_at::timestamp)::date  AS acquisition_month
    FROM {{ ref('seed_user_acquisition') }}

),

cohort_size AS (

    SELECT
        channel,
        acquisition_month,
        COUNT(*) AS users_acquired
    FROM acquisitions
    GROUP BY 1, 2

),

paid_channels AS (

    SELECT DISTINCT channel
    FROM {{ ref('marketing_spend_monthly') }}

)

SELECT
    a.user_id,
    a.channel,
    a.campaign,
    a.acquired_at,
    a.acquisition_month,
    (p.channel IS NOT NULL)                                 AS channel_is_paid,
    COALESCE(ROUND(s.spend_eur / c.users_acquired, 2), 0)   AS marketing_cost_eur
FROM acquisitions a
INNER JOIN cohort_size c
    ON  c.channel           = a.channel
    AND c.acquisition_month = a.acquisition_month
LEFT JOIN paid_channels p
    ON p.channel = a.channel
LEFT JOIN {{ ref('marketing_spend_monthly') }} s
    ON  s.channel     = a.channel
    AND s.spend_month = a.acquisition_month
