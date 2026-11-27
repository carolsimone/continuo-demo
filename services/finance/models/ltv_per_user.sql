{{ config(materialized='table', tags=['daily']) }}

WITH revenue AS (

    SELECT
        user_id,
        acquisition_month,
        revenue_eur
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
    r.revenue_eur,
    o.variable_cost_eur,
    o.operational_cost_eur,
    m.marketing_cost_eur,
    ROUND(r.revenue_eur - o.variable_cost_eur, 2)
        AS contribution_margin_eur,
    ROUND(r.revenue_eur - o.operational_cost_eur - m.marketing_cost_eur, 2)
        AS fully_allocated_eur,
    {{ safe_divide('r.revenue_eur - o.variable_cost_eur', 'm.marketing_cost_eur', 4) }}
        AS ltv_to_cac
FROM revenue r
INNER JOIN {{ ref('operational_cost_per_user') }} o
    ON o.user_id = r.user_id
INNER JOIN marketing m
    ON m.user_id = r.user_id
