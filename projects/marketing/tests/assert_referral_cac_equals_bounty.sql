-- Referral CAC must be exactly the bounty.
--
-- The referral spend row is written as bounty x referrals-that-month, so
-- marketing_cost_per_user's cohort division is a deliberate no-op for this
-- channel and the result is exact, not an estimate. That makes this an
-- equality rather than a tolerance.
--
-- It fails loudly if anyone reintroduces referral as an unpaid channel, or if
-- REFERRAL_BOUNTY_EUR in scripts/gen_marketing_spend.py drifts away from
-- vars.referral_bounty_eur. Passes when it returns no rows.

SELECT
    user_id,
    channel,
    marketing_cost_eur
FROM {{ ref('marketing_cost_per_user') }}
WHERE channel = 'referral'
  AND marketing_cost_eur <> {{ var('referral_bounty_eur') }}
