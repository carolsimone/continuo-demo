{{ config(materialized='table', tags=['daily']) }}
SELECT *
FROM analytics.table_b
JOIN analytics.table_c USING (id)
