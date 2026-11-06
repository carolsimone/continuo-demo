{{ config(materialized='table', tags=['hourly']) }}
SELECT a.id
FROM analytics.ftable_a a
LEFT JOIN analytics.ftable_b b ON a.id = b.id
