-- Composite uniqueness: exactly one row per (channel, spend_month).
-- Built-in `unique` only covers single columns and this repo has no dbt_utils,
-- so this is expressed as a singular test. Passes when it returns no rows.

SELECT
    channel,
    spend_month,
    COUNT(*) AS row_count
FROM {{ ref('marketing_spend_monthly') }}
GROUP BY 1, 2
HAVING COUNT(*) > 1
