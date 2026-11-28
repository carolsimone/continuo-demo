{{ config(materialized='view', tags=['daily']) }}
SELECT * FROM analytics.table_a WHERE 1=1
