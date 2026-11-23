{{ config(materialized='table', tags=['daily']) }}
SELECT 1 AS id
