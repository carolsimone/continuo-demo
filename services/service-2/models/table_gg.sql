{{ config(materialized='table', tags=['daily}}
SELECT * FROM analytics.table_d WHERE 1 = 1
