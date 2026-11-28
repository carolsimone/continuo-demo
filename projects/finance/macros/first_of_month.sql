{% macro first_of_month(ts) -%}
    DATE_TRUNC('month', ({{ ts }})::timestamp)::date
{%- endmacro %}
