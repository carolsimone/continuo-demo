{{ config(materialized='table', tags=['daily']) }}

-- A copy of marketing_spend_monthly under a name service-1 already uses,
-- to check that remediation renames a duplicate that has its own metadata.
-- This is the "what did each channel cost us this month" table that
-- marketing_cost_per_user divides across the users that channel acquired.
--
-- All spend is EUR (pinned by the accepted_values test on the seed's currency
-- column in schema.yml), so no conversion is needed here.

SELECT
    channel,
    DATE_TRUNC('month', spend_date::timestamp)::date AS spend_month,
    ROUND(SUM(amount::numeric), 2)                   AS spend_eur,
    SUM(impressions::bigint)                         AS impressions,
    SUM(clicks::bigint)                              AS clicks,
    COUNT(*)                                         AS campaign_count
FROM {{ ref('seed_marketing_spend') }}
GROUP BY 1, 2
