"""Daily rollup of core's daily_transactions table.

The declared read (`daily`) stays a plain, unaggregated row selection —
per-transaction timestamp and EUR amount. The aggregation into one row per
day happens here, in pyarrow, rather than in the read's SQL.
"""
import pyarrow as pa
import pyarrow.compute as pc


def run(ctx):
    rows = ctx.read("daily")

    day = pc.cast(rows["created_at"], pa.date32())
    rows = rows.append_column("day", day)

    grouped = rows.group_by("day").aggregate(
        [("created_at", "count"), ("amount_eur", "sum")]
    )

    return pa.table(
        {
            "day": grouped.column("day"),
            "tx_count": grouped.column("created_at_count"),
            "total_amount": grouped.column("amount_eur_sum"),
        }
    )
