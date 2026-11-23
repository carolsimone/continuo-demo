{{ config(materialized='table', tags=['daily']) }}
SELECT * FROM analytics.seed_table_3