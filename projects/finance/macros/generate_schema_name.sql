{#
    Schema resolution shared by every dbt project image.

    A release check builds each node of a candidate release in an isolated
    schema, so it never touches production tables. continuo's
    execution-controller passes that schema through the DBT_TARGET_SCHEMA env
    var (dbt has no --target-schema flag), so when it is set every model
    materializes there regardless of its configured schema. When the env var is
    absent (a run in production) this falls back to dbt's default behaviour,
    leaving production materialization byte-identical to a project without this
    macro.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- set override = env_var('DBT_TARGET_SCHEMA', '') -%}
    {%- if override | length > 0 -%}
        {{ override }}
    {%- elif custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ target.schema }}_{{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
