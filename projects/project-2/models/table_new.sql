{{ config(materialized='table', tags=['daily']) }}
SELECT * FROM analytics.table_e
