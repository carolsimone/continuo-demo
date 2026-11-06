{{ config(materialized='table', tags=['hourly']) }}
SELECT 1 AS id