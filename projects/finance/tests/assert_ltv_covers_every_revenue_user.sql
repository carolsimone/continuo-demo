-- Every user with revenue must also appear in ltv_per_user. Nothing in the
-- dbt-level pipeline otherwise catches operational_cost_per_user's INNER JOIN
-- silently dropping cohorts if cost data ever became incomplete (not just
-- out-of-window — assert_operational_costs_within_acquisition_window only
-- catches the out-of-window case). Passes when it returns no rows.

SELECT r.user_id
FROM analytics.revenue_per_user r
WHERE NOT EXISTS (
    SELECT 1 FROM {{ ref('ltv_per_user') }} l WHERE l.user_id = r.user_id
)
