{{ config(materialized='table', tags=['daily']) }}

SELECT
    transaction_id,
    user_id,
    ROUND(amount::numeric, 2)     AS amount_eur,
    ROUND(fee_amount::numeric, 2) AS fee_amount_eur,
    created_at,
    'card' AS source
FROM {{ ref('seed_card_transactions') }}

UNION ALL

SELECT
    transaction_id,
    user_id,
    amount_eur,
    fee_amount_eur,
    created_at,
    'fx' AS source
FROM analytics.fx_transactions_eur
