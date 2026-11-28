{{ config(materialized='table', tags=['daily']) }}

WITH monthly AS (

    SELECT
        channel,
        spend_month,
        spend_eur,
        impressions,
        clicks,
        campaign_count
    FROM {{ ref('marketing_spend_monthly') }}

),

channels AS (

    SELECT
        channel,
        COUNT(*)             AS active_months,
        MIN(spend_month)     AS first_spend_month,
        MAX(spend_month)     AS last_spend_month,
        SUM(spend_eur)       AS spend_eur,
        SUM(campaign_count)  AS campaign_months,
        SUM(impressions)     AS impressions,
        SUM(clicks)          AS clicks
    FROM monthly
    GROUP BY channel

)

SELECT
    channel,
    active_months,
    first_spend_month,
    last_spend_month,
    spend_eur,
    campaign_months,
    impressions,
    clicks,
    ROUND(clicks::numeric / NULLIF(impressions, 0), 6)  AS click_through_rate,
    ROUND(spend_eur / NULLIF(clicks, 0), 4)             AS cost_per_click_eur,
    ROUND(spend_eur / SUM(spend_eur) OVER (), 6)        AS share_of_spend,
    RANK() OVER (ORDER BY spend_eur DESC)               AS spend_rank
FROM channels
