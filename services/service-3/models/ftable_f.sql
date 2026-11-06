{{ config(materialized='table', tags=['hourly']) }}
SELECT d.id
FROM analytics.ftable_d d
LEFT JOIN analytics.ftable_e e ON d.id = e.id
