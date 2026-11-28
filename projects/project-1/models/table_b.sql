{{ config(materialized='table', tags=['daily']) }}
SELECT * FROM {{ ref('seed_table_2') }}
