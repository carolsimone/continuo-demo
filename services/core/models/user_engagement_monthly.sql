{{ config(materialized='table', tags=['daily']) }}

WITH sessions AS (

    SELECT
        user_id,
        DATE_TRUNC('month', event_at)::date  AS activity_month,
        COUNT(DISTINCT session_id)           AS sessions,
        COUNT(DISTINCT event_at::date)       AS active_days
    FROM analytics.app_events
    WHERE event_name = 'session_start'
    GROUP BY 1, 2

)

SELECT
    a.user_id,
    a.activity_month,
    COALESCE(s.sessions, 0)                                         AS sessions,
    COALESCE(s.active_days, 0)                                      AS active_days,
    a.transaction_count,
    ROUND(a.transaction_count::numeric / NULLIF(s.sessions, 0), 4)  AS transactions_per_session
FROM {{ ref('user_activity_monthly') }} a
LEFT JOIN sessions s
    ON  s.user_id = a.user_id
    AND s.activity_month = a.activity_month
