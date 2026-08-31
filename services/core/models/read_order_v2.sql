{{ config(materialized=, tags=['daily']) }}

SELECT *
FROM analytics.read_order
