#!/usr/bin/env bash
# Local functional smoke for the core revenue models. Builds the core image,
# stands up an ephemeral postgres, stubs the cross-service upstreams
# (analytics.fx_transactions_eur, produced by finance, and service-py's two
# tables), runs `dbt build`, then
# asserts the row shapes. Exits non-zero on the first failure.
set -euo pipefail

IMG=core-models-smoke
PG=core-smoke-pg
NET=core-smoke-net
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

cleanup() {
  docker rm -f "$PG" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

echo "== build core image (real Dockerfile) =="
docker build -t "$IMG" -f "$ROOT/services/core/Dockerfile" "$ROOT/services/core"

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

echo "== stub the finance cross-service upstream =="
docker exec -i "$PG" psql -U continuo_svc -d continuo_dbt <<'SQL'
CREATE SCHEMA IF NOT EXISTS analytics;
DROP TABLE IF EXISTS analytics.fx_transactions_eur;
-- Mirrors finance's fx_transactions_eur output columns that core consumes.
CREATE TABLE analytics.fx_transactions_eur (
  transaction_id int, user_id int, amount numeric, fee_amount numeric,
  currency_from text, currency_to text, rate numeric, created_at timestamp,
  rate_to_eur numeric, amount_eur numeric, fee_amount_eur numeric
);
-- user_id 1 exists in seed_users; created_at must be >= that user's created_at
-- or assert_transactions_after_acquisition fails the build.
INSERT INTO analytics.fx_transactions_eur VALUES
  (1, 1, 100, 0.5, 'USD', 'EUR', 0.92, '2025-01-15 10:00:00', 0.92, 92.00, 0.46);
-- service-py's tables, which read_order, read_order_v2 and dbt_daily_kpis copy.
DROP TABLE IF EXISTS analytics.demo_orders_csv;
CREATE TABLE analytics.demo_orders_csv (order_id int, customer text, amount numeric);
DROP TABLE IF EXISTS analytics.py_daily_kpis;
CREATE TABLE analytics.py_daily_kpis (day date, tx_count bigint, total_amount numeric);
SQL

echo "== dbt seed =="
docker run --rm --network "$NET" \
  -e POSTGRES_HOST="$PG" -e POSTGRES_PORT=5432 \
  -e POSTGRES_DB=continuo_dbt -e POSTGRES_USER=continuo_svc -e POSTGRES_PASSWORD=runner \
  --entrypoint dbt "$IMG" seed --profiles-dir /project

echo "== dbt run read_order =="
# read_order_v2 reads read_order by its raw name, so dbt does not order the
# two; build read_order first.
docker run --rm --network "$NET" \
  -e POSTGRES_HOST="$PG" -e POSTGRES_PORT=5432 \
  -e POSTGRES_DB=continuo_dbt -e POSTGRES_USER=continuo_svc -e POSTGRES_PASSWORD=runner \
  --entrypoint dbt "$IMG" run -s read_order --profiles-dir /project

echo "== dbt build (seeds + models + tests) =="
docker run --rm --network "$NET" \
  -e POSTGRES_HOST="$PG" -e POSTGRES_PORT=5432 \
  -e POSTGRES_DB=continuo_dbt -e POSTGRES_USER=continuo_svc -e POSTGRES_PASSWORD=runner \
  --entrypoint dbt "$IMG" build --profiles-dir /project

assert_scalar() {
  local label="$1" expected="$2" sql="$3" actual
  actual="$(docker exec "$PG" psql -U continuo_svc -d continuo_dbt -tAc "$sql" | tr -d '[:space:]')"
  if [ "$actual" != "$expected" ]; then
    echo "FAIL: ${label}: expected ${expected}, got ${actual}"
    return 1
  fi
  echo "OK: ${label} = ${actual}"
}

echo "== assert revenue_per_user shape =="
assert_scalar "one row per user" 2000 \
  "SELECT COUNT(*) FROM analytics.revenue_per_user"
assert_scalar "user_id is unique" 2000 \
  "SELECT COUNT(DISTINCT user_id) FROM analytics.revenue_per_user"
assert_scalar "every seed user is present" 0 \
  "SELECT COUNT(*) FROM analytics.seed_users u
    WHERE NOT EXISTS (SELECT 1 FROM analytics.revenue_per_user r
                      WHERE r.user_id = u.user_id::int)"
assert_scalar "no negative revenue" 0 \
  "SELECT COUNT(*) FROM analytics.revenue_per_user WHERE revenue_eur < 0"
assert_scalar "zero-transaction users carry 0, never NULL" 0 \
  "SELECT COUNT(*) FROM analytics.revenue_per_user
    WHERE revenue_eur IS NULL OR gross_volume_eur IS NULL"
assert_scalar "revenue is far below volume (fees, not flow)" t \
  "SELECT SUM(revenue_eur) < SUM(gross_volume_eur) * 0.05 FROM analytics.revenue_per_user"
assert_scalar "revenue equals the summed transaction fees" t \
  "SELECT ROUND(SUM(revenue_eur),2) = (SELECT ROUND(SUM(fee_amount_eur),2)
                                       FROM analytics.daily_transactions)
   FROM analytics.revenue_per_user"
assert_scalar "acquisition_month is always first-of-month" 0 \
  "SELECT COUNT(*) FROM analytics.revenue_per_user
    WHERE EXTRACT(DAY FROM acquisition_month) <> 1"

echo "== all core assertions passed =="
