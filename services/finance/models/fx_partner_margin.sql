{{ config(materialized='table', tags=['daily']) }}

WITH fees AS (

    SELECT
        currency_from,
        {{ first_of_month('created_at') }}  AS fx_month,
        SUM(amount_eur)                     AS volume_eur,
        SUM(fee_amount_eur)                 AS fee_revenue_eur
    FROM {{ ref('fx_transactions_eur') }}
    GROUP BY 1, 2

),

partner_costs AS (

    SELECT
        currency,
        {{ first_of_month('invoiced_at') }}  AS fx_month,
        SUM(cost_eur)                        AS partner_cost_eur
    FROM analytics.fx_partner_costs
    GROUP BY 1, 2

)

SELECT
    f.currency_from,
    f.fx_month,
    f.volume_eur,
    f.fee_revenue_eur,
    COALESCE(p.partner_cost_eur, 0)                      AS partner_cost_eur,
    f.fee_revenue_eur - COALESCE(p.partner_cost_eur, 0)  AS net_fx_margin_eur,
    {{ safe_divide('f.fee_revenue_eur - COALESCE(p.partner_cost_eur, 0)', 'f.volume_eur', 6) }}
                                                         AS net_take_rate
FROM fees f
LEFT JOIN partner_costs p
    ON  p.currency = f.currency_from
    AND p.fx_month = f.fx_month
