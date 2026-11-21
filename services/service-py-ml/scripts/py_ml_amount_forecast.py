"""XGBoost daily-amount forecast — the ML worked example for a Continuo node.

The node reads raw per-transaction rows from analytics.daily_transactions (a
table the core dbt project produces), rolls them up to one row per day, fits an
XGBoost regressor on simple calendar/volume features, and returns each day's
actual total next to the model's in-sample prediction.

It is a stand-in for a real model, and deliberately so: the point it proves is
that any Python ML stack runs inside a Continuo node unchanged. The runtime
contract is only ``run(ctx) -> Arrow table``; XGBoost is an ordinary library
added on top of the runtime base image. A production node would instead load a
pre-trained model baked into the image and only score here, keeping training
out of the request path.

The native ``xgboost.train`` / ``DMatrix`` API is used rather than the
``XGBRegressor`` scikit-learn wrapper so the image needs neither scikit-learn
nor the GPU stack the plain ``xgboost`` wheel drags in (see the Dockerfile).
"""

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import xgboost as xgb


def run(ctx):
    rows = ctx.read("daily")

    # Roll the raw rows up to one row per calendar day: count and EUR total.
    day = pc.cast(rows["created_at"], pa.date32())
    rows = rows.append_column("day", day)
    daily = (
        rows.group_by("day")
        .aggregate([("created_at", "count"), ("amount_eur", "sum")])
        .sort_by("day")
    )

    days = daily.column("day")
    actual = daily.column("amount_eur_sum")

    # A run always has upstream data; guard the empty case anyway so a genuinely
    # empty upstream yields an empty, correctly-typed table instead of feeding
    # XGBoost a zero-row matrix.
    if daily.num_rows == 0:
        return pa.table(
            {
                "day": pa.array([], type=pa.date32()),
                "actual_amount": pa.array([], type=actual.type),
                "predicted_amount": pa.array([], type=pa.float64()),
            }
        )

    tx_count = daily.column("created_at_count").to_numpy(zero_copy_only=False)

    # Features: position in the series (trend), day-of-week (weekly seasonality),
    # and that day's transaction count. Target: that day's total EUR amount.
    day_list = days.to_pylist()
    day_of_week = np.array([d.weekday() for d in day_list], dtype=float)
    trend = np.arange(len(day_list), dtype=float)
    features = np.column_stack([trend, day_of_week, tx_count.astype(float)])
    target = np.array([float(v) for v in actual.to_pylist()], dtype=float)

    booster = xgb.train(
        {"max_depth": 3, "eta": 0.2, "objective": "reg:squarederror", "verbosity": 0},
        xgb.DMatrix(features, label=target),
        num_boost_round=50,
    )
    predicted = booster.predict(xgb.DMatrix(features)).astype("float64")

    return pa.table(
        {
            "day": days,
            "actual_amount": actual,
            "predicted_amount": pa.array(predicted, type=pa.float64()),
        }
    )
