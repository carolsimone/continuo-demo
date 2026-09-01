{{ config(materialized='table', tags=['daily']) }}

SELECT *
FROM analytics.read_order
