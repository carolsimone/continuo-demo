{{ config(materialized='table', tags=['probe_external_source']) }}
SELECT * FROM {{ source('ingest', 'ingest_probe') }}
