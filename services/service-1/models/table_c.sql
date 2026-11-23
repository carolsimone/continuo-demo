{{ config(materialized='table', tags=['daily']) }}
SELECT does_not_exist FROM {{ ref('seed_table_3') }}
