{% macro safe_divide(numerator, divisor, scale=2) -%}
    ROUND(({{ numerator }})::numeric / NULLIF({{ denominator }}, 0), {{ scale }})
{%- endmacro %}
