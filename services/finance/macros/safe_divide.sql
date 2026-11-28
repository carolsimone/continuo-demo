{% macro safe_divide(numerator, denominator, scale=2) -%}
    ROUND(({{ numerator }})::numeric / NULLIF({{ denominator }}, 0), {{ scale }})
{%- endmacro %}
