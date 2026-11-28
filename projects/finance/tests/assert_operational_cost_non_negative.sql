-- Operational cost per user is always a positive share of a positive monthly
-- total; it can never be negative. Passes when it returns no rows.

SELECT
    user_id,
    acquisition_month,
    operational_cost_eur
FROM {{ ref('operational_cost_per_user') }}
WHERE operational_cost_eur < 0
