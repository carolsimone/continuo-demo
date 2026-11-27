{{ config(materialized='table', tags=['daily']) }}

WITH transactions AS (

    SELECT
        transaction_id,
        user_id,
        amount,
        fee_amount,
        currency_from,
        currency_to,
        rate,
        created_at
    FROM analytics.seed_fx_transactions

),

rated AS (

    SELECT
        t.*,
        r.rate_date,
        r.rate_to_eur
    FROM transactions t
    LEFT JOIN LATERAL (
        SELECT
            rate_date,
            rate_to_eur
        FROM {{ ref('seed_fx_rates_eur') }}
        WHERE currency = t.currency_from
          AND rate_date <= t.created_at::date
        ORDER BY rate_date DESC
        LIMIT 1
    ) r ON true

)

SELECT
    transaction_id,
    user_id,
    amount,
    fee_amount,
    currency_from,
    currency_to,
    rate,
    created_at,
    rate_date,
    rate_to_eur,
    ROUND((amount * rate_to_eur)::numeric, 2)      AS amount_eur,
    ROUND((fee_amount * rate_to_eur)::numeric, 2)  AS fee_amount_eur
FROM rated
