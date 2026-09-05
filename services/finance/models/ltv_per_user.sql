{{ config(materialized='table', tags=['daily']) }}

-- Per-user unit economics: the model both cost designs deferred to, now
-- buildable because core carries revenue.
--
-- Two views, on purpose:
--   * contribution_margin_eur = revenue - VARIABLE cost. The standard LTV
--     numerator, and the one that makes ltv_to_cac comparable to any figure
--     quoted outside this repo.
--   * fully_allocated_eur = revenue - TOTAL operational cost - marketing cost.
--     The accounting truth. It is negative for essentially every user, as it
--     is for real companies at this stage. Carrying both means the headline is
--     the standard one and nothing is hidden.
--
-- NOTE: analytics.revenue_per_user (core) and analytics.marketing_cost_per_user
-- (marketing) are produced by *other* dbt projects and are referenced by raw
-- schema-qualified name. They must NOT be turned into ref() calls.
-- See README.md "Cross-service references".

WITH revenue AS (

    SELECT
        user_id,
        acquisition_month
    FROM analytics.revenue_per_user

),

marketing AS (

    SELECT
        user_id,
        channel,
        marketing_cost_eur
    FROM analytics.marketing_cost_per_user

)

SELECT
    r.user_id,
    r.acquisition_month,
    m.channel,
    rv.revenue_eur,
    o.variable_cost_eur,
    o.operational_cost_eur,
    m.marketing_cost_eur,
    ROUND(rv.revenue_eur - o.variable_cost_eur, 2)
        AS contribution_margin_eur,
    ROUND(rv.revenue_eur - o.operational_cost_eur - m.marketing_cost_eur, 2)
        AS fully_allocated_eur,
    -- NULLIF is load-bearing: organic users have EUR 0 CAC, so an unguarded
    -- division errors on a sixth of the table. Referral users are NOT in that
    -- group -- they carry the referral bounty.
    ROUND(
        (rv.revenue_eur - o.variable_cost_eur) / NULLIF(m.marketing_cost_eur, 0), 4
    ) AS ltv_to_cac
FROM revenue r
INNER JOIN analytics.revenue_per_user rv
    ON rv.user_id = r.user_id
INNER JOIN {{ ref('operational_cost_per_user') }} o
    ON o.user_id = r.user_id
INNER JOIN marketing m
    ON m.user_id = r.user_id