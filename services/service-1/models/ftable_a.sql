{{ config(materialized='table', tags=['e2e-schedule-failure']) }}
SELECT 1 AS id from dumb.error_v1
