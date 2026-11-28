-- The headline column must actually be its components. Guards against an edit
-- that changes one side of the subtraction and not the other.
-- Passes when it returns no rows.

SELECT
    user_id,
    revenue_eur,
    variable_cost_eur,
    contribution_margin_eur,
    operational_cost_eur,
    marketing_cost_eur,
    fully_allocated_eur
FROM {{ ref('ltv_per_user') }}
WHERE ABS(contribution_margin_eur - (revenue_eur - variable_cost_eur)) > 0.01
   OR ABS(fully_allocated_eur
          - (revenue_eur - operational_cost_eur - marketing_cost_eur)) > 0.01
