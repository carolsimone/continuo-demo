{{ config(materialized='table', tags=['daily']), tags=['daily']) }}
SELECT * FROM analytics.table_k
