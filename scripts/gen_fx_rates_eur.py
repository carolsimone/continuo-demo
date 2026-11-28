#!/usr/bin/env python3
"""Generate projects/finance/seeds/seed_fx_rates_eur.csv.

Rates are published on business days only, the way a central bank publishes
them: one row per currency per weekday, from a week before core's first FX
transaction (seed_fx_transactions.csv) to its last. A transaction on a weekend
takes the last rate published before it. rate_to_eur = base rate per currency
+ deterministic daily jitter (+/- 0.5%). EUR is pinned to exactly 1.0.

Run from repo root:  uv run python scripts/gen_fx_rates_eur.py
"""
import csv
import hashlib
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "projects" / "core" / "seeds" / "seed_fx_transactions.csv"
DST = ROOT / "projects" / "finance" / "seeds" / "seed_fx_rates_eur.csv"

# A non-empty SEED_SALT draws a different dataset from the same rules: the
# agent-remediation eval grades a fix on data the fix never ran on. Unset, the
# output is the committed seed.
SALT_PREFIX = f"{os.environ['SEED_SALT']}|" if os.environ.get("SEED_SALT") else ""

# Realistic 2024 base rates: 1 unit of <currency> in EUR.
BASE_RATES = {
    "EUR": 1.0,
    "USD": 0.92,
    "GBP": 1.17,
    "CHF": 1.05,
    "AUD": 0.61,
    "CAD": 0.68,
    "JPY": 0.0061,
    "NOK": 0.086,
    "PLN": 0.23,
    "SEK": 0.088,
}

JITTER = 0.005  # +/- 0.5%

# Rates start this many days before the first transaction, so a transaction on
# the window's first weekend still has a rate published before it.
LEAD_DAYS = 7


def _jitter_factor(currency: str, date: str) -> float:
    """Deterministic multiplier in [1 - JITTER, 1 + JITTER] from a stable hash."""
    h = hashlib.md5(f"{SALT_PREFIX}{currency}{date}".encode()).hexdigest()
    frac = int(h[:8], 16) / 0xFFFFFFFF  # 0.0 .. 1.0
    return 1.0 + (frac * 2 - 1) * JITTER  # -JITTER .. +JITTER


def rate_to_eur(currency: str, date: str) -> float:
    if currency == "EUR":
        return 1.0
    base = BASE_RATES[currency]  # KeyError on unknown currency (intentional)
    return round(base * _jitter_factor(currency, date), 6)


def build_rows(txns: Iterable[dict]) -> list[dict]:
    """txns: iterable of dicts with 'created_at'.
    Returns one {'currency','rate_date','rate_to_eur'} row per currency per
    weekday of the transactions' window, sorted by currency then date.
    """
    days = sorted(t["created_at"][:10] for t in txns)
    first = date.fromisoformat(days[0]) - timedelta(days=LEAD_DAYS)
    last = date.fromisoformat(days[-1])
    weekdays = []
    day = first
    while day <= last:
        if day.weekday() < 5:
            weekdays.append(day.isoformat())
        day += timedelta(days=1)
    return [
        {"currency": c, "rate_date": d, "rate_to_eur": rate_to_eur(c, d)}
        for c in sorted(BASE_RATES)
        for d in weekdays
    ]


def main():
    with SRC.open(newline="") as f:
        txns = list(csv.DictReader(f))
    rows = build_rows(txns)
    with DST.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["currency", "rate_date", "rate_to_eur"])
        w.writeheader()
        w.writerows(rows)
    log.info("Wrote %s rows to %s", len(rows), DST.relative_to(ROOT))


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(message)s")
    main()
