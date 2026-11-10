{{ config(materialized='table', tags=['probe_external_source']) }}
SELECT * FROM raw.ingest_probe
