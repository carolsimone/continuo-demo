{{ config(materialized='view', tags=['daily']) }}
select * from {{ ref('operational_cost_per_user')}}
