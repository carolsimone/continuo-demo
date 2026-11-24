{{ config(materialized='table', tags=['daily']) }}
SELECT does_not_exist FROM analytics.seed_table_3