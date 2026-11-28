-- Acquisition cost can be zero (organic/referral) but never negative.
-- Passes when it returns no rows.

SELECT
    user_id,
    channel,
    marketing_cost_eur
FROM {{ ref('marketing_cost_per_user') }}
WHERE marketing_cost_eur < 0
