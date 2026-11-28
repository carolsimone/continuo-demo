{{ config(materialized='table', tags=['daily']) }}
SELECT * FROM analytics.table_a JOIN analytics.table_b USING (id)
