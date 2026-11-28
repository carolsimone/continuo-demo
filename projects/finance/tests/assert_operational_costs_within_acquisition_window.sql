-- Timeline-drift guard (spec decision 6): every cost month must fall inside
-- the acquisition window covered by core's seed_users. Months with costs but
-- zero signups INSIDE the window are fine (unallocated by design); a cost
-- month OUTSIDE the window means the two seeds' timelines have drifted apart
-- again -- the bug this repo had when costs covered 2024 but users stopped in
-- 2023 -- and must fail the build. Passes when it returns no rows.

WITH acquisition_window AS (

    SELECT
        DATE_TRUNC('month', MIN(created_at::timestamp))::date AS first_month,
        DATE_TRUNC('month', MAX(created_at::timestamp))::date AS last_month
    FROM analytics.seed_users

)

SELECT
    m.cost_month
FROM {{ ref('operational_costs_monthly') }} m
CROSS JOIN acquisition_window w
WHERE m.cost_month < w.first_month
   OR m.cost_month > w.last_month
