{{ config(materialized='table') }}

-- A dormant node: it has an owner (the project's top-level +meta) and no tag,
-- so it has no schedule. continuo puts it in the topology and checks it in
-- every release, but no cron runs it: you run it by hand from its node page.
--
-- One row per paid channel with its campaign count and total spend in EUR.

SELECT
    channel,
    COUNT(*)                       AS campaign_count,
    ROUND(SUM(amount::numeric), 2) AS spend_eur
FROM {{ ref('seed_marketing_spend') }}
GROUP BY 1
