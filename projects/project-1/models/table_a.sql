{{ config(materialized='table', tags=['daily']) }}
SELECT * FROM {{ ref('seed_table_1') }} WHERE 1=1
