-- Revenue is a sum of fees net of refunds. A refund returns its purchase's
-- fee, so a user's revenue never drops below zero. Passes when it returns no
-- rows.

SELECT
    user_id,
    fee_revenue_eur,
    gross_volume_eur
FROM {{ ref('revenue_per_user') }}
WHERE fee_revenue_eur < 0
   OR gross_volume_eur < 0
