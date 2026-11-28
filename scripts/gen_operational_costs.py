#!/usr/bin/env python3
"""Generate projects/finance/seeds/seed_operational_costs.csv.

One row per (cost line, month) for 2023-01 .. 2024-12 — the window covered by
core's seed_users. Costs and user acquisition must overlap, otherwise
operational_cost_per_user has costs with no users to allocate them to.

Amounts are derived from a stable md5 hash of (subcategory, month), never
`random`, so re-running produces no diff.

Run from repo root:  uv run python scripts/gen_operational_costs.py
"""
import csv
import hashlib
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DST = ROOT / "projects" / "finance" / "seeds" / "seed_operational_costs.csv"

# A non-empty SEED_SALT draws a different dataset from the same rules: the
# agent-remediation eval grades a fix on data the fix never ran on. Unset, the
# output is the committed seed.
SALT_PREFIX = f"{os.environ['SEED_SALT']}|" if os.environ.get("SEED_SALT") else ""

YEARS = (2023, 2024)  # MUST match gen_users.py and gen_marketing_spend.py

# (category, subcategory, cost_type, base_eur, monthly_growth) -- 10 cost lines,
# sized for a ~6-person fintech serving 2,000 users, not a large company.
#
# The split matters: ltv_per_user headlines contribution margin, which
# subtracts ONLY the variable lines. Fixed lines are excluded from the LTV
# numerator and show up in fully_allocated_eur instead.
#
# Variable lines drift upward with the month index as the user base grows;
# fixed lines only jitter around their base.
#
# Over 24 months these total ~EUR 40k variable (~EUR 20/user) and ~EUR 706k
# fixed (~EUR 353/user), which puts contribution margin at ~EUR 81 against
# ~EUR 101 of revenue and leaves fully-allocated at ~ -EUR 302. A company
# burning at Series A, which is the honest shape.
COST_LINES = [
    ("COGS", "cloud_hosting",        "variable", 850.0,   0.015),
    ("COGS", "transaction_fees",     "variable", 570.0,   0.015),
    ("COGS", "customer_support",     "fixed",    2500.0,  0.0),
    ("R&D",  "engineering_salaries", "fixed",    16000.0, 0.0),
    ("R&D",  "product_design",       "fixed",    3000.0,  0.0),
    ("R&D",  "tooling_saas",         "fixed",    1200.0,  0.0),
    ("G&A",  "office_rent",          "fixed",    2800.0,  0.0),
    ("G&A",  "finance_legal",        "fixed",    1800.0,  0.0),
    ("G&A",  "hr_admin",             "fixed",    1500.0,  0.0),
    ("G&A",  "insurance",            "fixed",    600.0,   0.0),
]

JITTER = 0.08  # deterministic +/-8% wobble around the trend line


def _frac(subcategory: str, month: str) -> float:
    """Deterministic float in [0.0, 1.0] from a stable hash."""
    h = hashlib.md5(f"{SALT_PREFIX}{subcategory}|{month}".encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def build_rows() -> list[dict]:
    """Return all (cost line, month) rows, ordered by month then cost line."""
    rows = []
    cost_id = 1
    month_index = 0
    for year in YEARS:
        for month_num in range(1, 13):
            month = f"{year}-{month_num:02d}"
            for category, subcategory, cost_type, base, growth in COST_LINES:
                trend = base * (1 + growth * month_index)
                wobble = 1 - JITTER + 2 * JITTER * _frac(subcategory, month)
                rows.append({
                    "cost_id": cost_id,
                    "cost_date": f"{month}-01 00:00:00",
                    "category": category,
                    "subcategory": subcategory,
                    "cost_type": cost_type,
                    "amount": round(trend * wobble, 2),
                    "currency": "EUR",
                })
                cost_id += 1
            month_index += 1
    return rows


def main():
    rows = build_rows()
    with DST.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    log.info("Wrote %s rows to %s", len(rows), DST.relative_to(ROOT))


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(message)s")
    main()
