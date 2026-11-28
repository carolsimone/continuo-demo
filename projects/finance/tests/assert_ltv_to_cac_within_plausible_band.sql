-- Economic-drift guard, the counterpart of
-- assert_operational_costs_within_acquisition_window.
--
-- Before this repo had revenue, operational cost per user sat at a median of
-- EUR 48,723 against roughly EUR 10 of fee revenue -- every model compiled and
-- every test passed while the numbers meant nothing. This makes that class of
-- drift a red build.
--
-- Blended, NOT an average of the per-row ratio: ltv_to_cac is NULL for the
-- ~16% of users acquired organically at EUR 0 CAC, so averaging the column
-- would silently drop them and measure a different population.
-- Passes when it returns no rows.

WITH blended AS (

    SELECT
        SUM(contribution_margin_eur)            AS total_margin,
        SUM(marketing_cost_eur)                 AS total_cac,
        SUM(contribution_margin_eur)
            / NULLIF(SUM(marketing_cost_eur), 0) AS ratio
    FROM {{ ref('ltv_per_user') }}

)

SELECT
    total_margin,
    total_cac,
    ratio
FROM blended
WHERE ratio IS NULL
   OR ratio < 1.5
   OR ratio > 6.0
