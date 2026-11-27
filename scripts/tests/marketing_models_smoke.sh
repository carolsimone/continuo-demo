#!/usr/bin/env bash
# Local functional smoke for the marketing cost-allocation models. Builds the
# marketing image, stands up an ephemeral postgres, runs `dbt build` (seeds +
# models + tests), then asserts the row shapes the models are supposed to have.
# Exits non-zero on the first failure. Gate every marketing push on it.
#
# fx_activity_by_channel reads finance's fx_transactions_eur cross-service, so
# that table is stubbed with one row.
set -euo pipefail

IMG=marketing-models-smoke
PG=marketing-smoke-pg
NET=marketing-smoke-net
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

cleanup() {
  docker rm -f "$PG" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

echo "== build marketing image (real Dockerfile) =="
docker build -t "$IMG" -f "$ROOT/services/marketing/Dockerfile" "$ROOT/services/marketing"

echo "== start ephemeral postgres =="
docker network create "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" \
  -e POSTGRES_USER=continuo_svc -e POSTGRES_PASSWORD=runner -e POSTGRES_DB=continuo_dbt \
  postgres:16-alpine >/dev/null

echo "== wait for postgres =="
for _ in $(seq 1 30); do
  if docker exec "$PG" pg_isready -U continuo_svc -d continuo_dbt >/dev/null 2>&1; then break; fi
  sleep 1
done

echo "== create analytics schema + the finance cross-service upstream stub =="
docker exec -i "$PG" psql -U continuo_svc -d continuo_dbt <<'SQL'
CREATE SCHEMA IF NOT EXISTS analytics;
DROP TABLE IF EXISTS analytics.fx_transactions_eur;
CREATE TABLE analytics.fx_transactions_eur (
  transaction_id int, user_id int, created_at timestamp,
  amount_eur numeric, fee_amount_eur numeric
);
INSERT INTO analytics.fx_transactions_eur VALUES (1, 1, '2023-02-15 10:00:00', 92.00, 0.46);
SQL

echo "== dbt build (seeds + models + tests) =="
# The image ENTRYPOINT is a local-debug script that ignores its args and always
# runs a hardcoded `dbt run`. Override it so we actually get `dbt build`.
docker run --rm --network "$NET" \
  -e POSTGRES_HOST="$PG" -e POSTGRES_PORT=5432 \
  -e POSTGRES_DB=continuo_dbt -e POSTGRES_USER=continuo_svc -e POSTGRES_PASSWORD=runner \
  --entrypoint dbt "$IMG" build --profiles-dir /project

# assert_scalar <label> <expected> <sql>
assert_scalar() {
  local label="$1" expected="$2" sql="$3" actual
  actual="$(docker exec "$PG" psql -U continuo_svc -d continuo_dbt -tAc "$sql" | tr -d '[:space:]')"
  if [ "$actual" != "$expected" ]; then
    echo "FAIL: ${label}: expected ${expected}, got ${actual}"
    return 1
  fi
  echo "OK: ${label} = ${actual}"
}

echo "== assert marketing_spend_monthly shape =="
assert_scalar "spend_monthly row count (6 channels x 24 months)" 144 \
  "SELECT COUNT(*) FROM analytics.marketing_spend_monthly"
assert_scalar "spend_monthly distinct channels" 6 \
  "SELECT COUNT(DISTINCT channel) FROM analytics.marketing_spend_monthly"
assert_scalar "spend_monthly distinct months" 24 \
  "SELECT COUNT(DISTINCT spend_month) FROM analytics.marketing_spend_monthly"
assert_scalar "spend_monthly months are all first-of-month" 0 \
  "SELECT COUNT(*) FROM analytics.marketing_spend_monthly WHERE EXTRACT(DAY FROM spend_month) <> 1"
assert_scalar "spend_monthly campaign_count total equals seed rows" 288 \
  "SELECT SUM(campaign_count) FROM analytics.marketing_spend_monthly"
assert_scalar "spend_monthly total equals seed total" t \
  "SELECT ROUND(SUM(spend_eur),2) = (SELECT ROUND(SUM(amount::numeric),2) FROM analytics.seed_marketing_spend) FROM analytics.marketing_spend_monthly"

echo "== assert marketing_cost_per_user shape =="
assert_scalar "cost_per_user has one row per user" 2000 \
  "SELECT COUNT(*) FROM analytics.marketing_cost_per_user"
assert_scalar "cost_per_user user_id is unique" 2000 \
  "SELECT COUNT(DISTINCT user_id) FROM analytics.marketing_cost_per_user"
assert_scalar "every acquired user is present" 0 \
  "SELECT COUNT(*) FROM analytics.seed_user_acquisition a
    WHERE NOT EXISTS (SELECT 1 FROM analytics.marketing_cost_per_user c
                      WHERE c.user_id = a.user_id::int)"
assert_scalar "unpaid users (organic only)" 310 \
  "SELECT COUNT(*) FROM analytics.marketing_cost_per_user WHERE NOT channel_is_paid"
assert_scalar "unpaid users all cost exactly 0" 310 \
  "SELECT COUNT(*) FROM analytics.marketing_cost_per_user
    WHERE NOT channel_is_paid AND marketing_cost_eur = 0"
assert_scalar "organic is the only unpaid channel" t \
  "SELECT COALESCE(ARRAY_AGG(DISTINCT channel ORDER BY channel), '{}') = ARRAY['organic']
     FROM analytics.marketing_cost_per_user WHERE NOT channel_is_paid"
assert_scalar "paid users" 1690 \
  "SELECT COUNT(*) FROM analytics.marketing_cost_per_user WHERE channel_is_paid"
assert_scalar "paid users all cost more than 0" 1690 \
  "SELECT COUNT(*) FROM analytics.marketing_cost_per_user
    WHERE channel_is_paid AND marketing_cost_eur > 0"
assert_scalar "acquisition_month is always first-of-month" 0 \
  "SELECT COUNT(*) FROM analytics.marketing_cost_per_user
    WHERE EXTRACT(DAY FROM acquisition_month) <> 1"

echo "== assert the allocation rule itself =="
# For each paid cohort: users_in_cohort * per_user_cost must reconstruct that
# channel-month's spend, allowing a few cents of rounding residual. This is the
# core arithmetic of the model, not just its shape.
# At the 2,000-user/24-month scale, per-user cent rounding across large
# cohorts can drift further than a few cents: a live dbt build against the
# regenerated seeds showed a real max residual of EUR 0.20 (google_ads,
# 2024-11, 42-user cohort). 0.25 comfortably clears that observed max while
# still catching a real regression in the allocation math.
assert_scalar "each cohort's allocation reconstructs its channel-month spend" 0 \
  "WITH cohort AS (
       SELECT c.channel, c.acquisition_month,
              COUNT(*) AS users, MAX(c.marketing_cost_eur) AS per_user
       FROM analytics.marketing_cost_per_user c
       WHERE c.channel_is_paid
       GROUP BY 1, 2
   )
   SELECT COUNT(*) FROM cohort
   JOIN analytics.marketing_spend_monthly s
     ON s.channel = cohort.channel AND s.spend_month = cohort.acquisition_month
   WHERE ABS(cohort.users * cohort.per_user - s.spend_eur) > 0.25"

# Unallocated spend is expected and by design: a channel-month with spend but
# zero acquisitions has no user to carry it. Assert the direction only.
assert_scalar "allocated total never exceeds total spend" t \
  "SELECT (SELECT SUM(marketing_cost_eur) FROM analytics.marketing_cost_per_user)
        < (SELECT SUM(spend_eur) FROM analytics.marketing_spend_monthly)"

echo "== assert referral CAC equals the bounty =="
assert_scalar "referral users all carry the bounty" 0 \
  "SELECT COUNT(*) FROM analytics.marketing_cost_per_user
    WHERE channel = 'referral' AND marketing_cost_eur <> 25.00"
assert_scalar "organic is the only zero-cost channel" 1 \
  "SELECT COUNT(DISTINCT channel) FROM analytics.marketing_cost_per_user
    WHERE marketing_cost_eur = 0"
assert_scalar "referral counts as a paid channel" t \
  "SELECT bool_and(channel_is_paid) FROM analytics.marketing_cost_per_user
    WHERE channel = 'referral'"

echo "SMOKE OK"
