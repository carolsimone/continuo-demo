{{ config(materialized='table', tags=['daily']) }}

WITH acquisitions AS (

    SELECT
        user_id::int                        AS user_id,
        created_at::timestamp               AS acquired_at,
        {{ first_of_month('created_at') }}  AS acquisition_month
    FROM analytics.seed_users

),

cohort_size AS (

    SELECT
        acquisition_month,
        COUNT(*) AS users_acquired
    FROM acquisitions
    GROUP BY 1

)

SELECT
    a.user_id,
    a.acquired_at,
    a.acquisition_month,
    c.users_acquired                                              AS users_in_cohort,
    {{ safe_divide('m.total_cost_eur', 'c.users_acquired') }}     AS operational_cost_eur,
    {{ safe_divide('m.variable_cost_eur', 'c.users_acquired') }}  AS variable_cost_eur
FROM acquisitions a
INNER JOIN cohort_size c
    ON c.acquisition_month = a.acquisition_month
INNER JOIN analytics.operational_costs_monthly m
    ON m.period_start = a.acquisition_month