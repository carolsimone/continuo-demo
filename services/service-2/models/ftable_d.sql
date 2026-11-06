{{ config(materialized='table', tags=['hourly']) }}
SELECT id FROM analytics.ftable_c
