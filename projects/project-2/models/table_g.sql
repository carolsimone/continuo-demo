{{ config(materialized='table', tags=['daily']) }}
SELECT * FROM analytics.table_d
JOIN analytics.table_e USING (id)