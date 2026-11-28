{{ config(materialized='table') }}

SELECT
    channel,
    COUNT(*)                       AS campaign_count,
    ROUND(SUM(amount::numeric), 2) AS spend_eur
FROM {{ ref('seed_marketing_spend') }}
GROUP BY 1
