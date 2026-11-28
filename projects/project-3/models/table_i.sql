{{ config(materialized='table', tags=['daily']) }}
SELECT * FROM analytics.table_g JOIN analytics.table_h USING (id)
