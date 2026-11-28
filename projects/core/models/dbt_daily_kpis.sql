{{ config(materialized='table', tags=['daily']) }}

SELECT *
FROM analytics.py_daily_kpis
