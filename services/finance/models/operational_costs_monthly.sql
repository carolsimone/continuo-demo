{{ config(materialized='table', tags=['daily']) }}

SELECT
    {{ first_of_month('cost_date') }}                                AS period_start,
    ROUND(SUM(amount::numeric), 2)                                   AS total_cost_eur,
    ROUND(SUM(amount::numeric) FILTER (WHERE category = 'COGS'), 2)  AS cogs_eur,
    ROUND(SUM(amount::numeric) FILTER (WHERE category = 'R&D'), 2)   AS rd_eur,
    ROUND(SUM(amount::numeric) FILTER (WHERE category = 'G&A'), 2)   AS ga_eur,
    ROUND(SUM(amount::numeric) FILTER (WHERE cost_type = 'variable'), 2) AS variable_cost_eur,
    ROUND(SUM(amount::numeric) FILTER (WHERE cost_type = 'fixed'), 2)    AS fixed_cost_eur,
    COUNT(*)                                                         AS cost_line_count
FROM {{ ref('seed_operational_costs') }}
GROUP BY 1
