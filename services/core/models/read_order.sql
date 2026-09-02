{{ config(materialized='table', tags=['daily']}}

SELECT *
FROM analytics.demo_orders_csv
