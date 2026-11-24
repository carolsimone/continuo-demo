{{ config(materialized='table', tags=['daily']) }}
SELECT * FROM (SELECT * FROM analytics.table_new) AS table_new_squared
