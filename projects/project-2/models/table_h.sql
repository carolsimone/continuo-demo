{{ config(materialized='table', tags=['daily']) }}
SELECT * FROM analytics.table_e JOIN analytics.table_f USING (id)
