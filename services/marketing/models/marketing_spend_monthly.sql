{{ config(materialized='table', tags=['daily']) }}

SELECT
    channel,
    DATE_TRUNC('month', spend_date::timestamp)::date AS spend_month,
    ROUND(SUM(amount::numeric), 2)                   AS spend_eur,
    SUM(impressions::bigint)                         AS impressions,
    SUM(clicks::bigint)                              AS clicks,
    COUNT(*)                                         AS campaign_count
FROM {{ ref('seed_marketing_spend') }}
GROUP BY 1, 2
