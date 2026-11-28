-- No user can transact before they exist. This held only by accident before
-- the timeline change (every transaction was 2024, every acquisition <= 2023);
-- now that the windows overlap it needs enforcing. Passes when it returns no rows.

SELECT
    t.transaction_id,
    t.source,
    t.user_id,
    t.created_at            AS transacted_at,
    u.created_at            AS acquired_at
FROM {{ ref('daily_transactions') }} t
INNER JOIN {{ ref('seed_users') }} u
    ON u.user_id::int = t.user_id::int
WHERE t.created_at::timestamp < u.created_at::timestamp
