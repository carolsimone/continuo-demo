{{ config(materialized='table', tags=['daily']) }}

WITH users AS (

    SELECT
        user_id,
        channel,
        acquisition_month,
        revenue_eur,
        contribution_margin_eur,
        marketing_cost_eur
    FROM {{ ref('ltv_per_user') }}

),

activity AS (

    SELECT
        user_id,
        months_since_acquisition,
        cumulative_fee_revenue_eur
    FROM analytics.user_activity_monthly

),

payback AS (

    SELECT
        u.user_id,
        MIN(a.months_since_acquisition) AS payback_month
    FROM users u
    INNER JOIN activity a
        ON a.user_id = u.user_id
    WHERE u.marketing_cost_eur > 0
      AND a.cumulative_fee_revenue_eur >= u.marketing_cost_eur
    GROUP BY u.user_id

),

cohorts AS (

    SELECT
        u.channel,
        u.acquisition_month,
        COUNT(*)                                          AS users,
        COUNT(*) FILTER (WHERE u.marketing_cost_eur > 0)  AS paid_users,
        SUM(u.revenue_eur)                                AS revenue_eur,
        SUM(u.contribution_margin_eur)                    AS contribution_margin_eur,
        SUM(u.marketing_cost_eur)                         AS marketing_cost_eur,
        COUNT(p.payback_month)                            AS paid_back_users,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY p.payback_month)
                                                          AS median_payback_months
    FROM users u
    LEFT JOIN payback p
        ON p.user_id = u.user_id
    GROUP BY u.channel, u.acquisition_month

)

SELECT
    channel,
    acquisition_month,
    users,
    paid_users,
    revenue_eur,
    contribution_margin_eur,
    marketing_cost_eur,
    {{ safe_divide('contribution_margin_eur', 'marketing_cost_eur', 4) }}  AS ltv_to_cac,
    paid_back_users,
    {{ safe_divide('paid_back_users', 'paid_users', 4) }}                  AS paid_back_share,
    median_payback_months
FROM cohorts
