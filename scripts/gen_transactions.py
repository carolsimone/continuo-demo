#!/usr/bin/env python3
"""Generate the two transaction seeds, carrying the fee the company earns.

Writes services/core/seeds/seed_card_transactions.csv and
services/core/seeds/seed_fx_transactions.csv. Reads
seed_user_acquisition.csv, so run gen_users.py first.

fee_amount is the reason this generator exists. Before it, every transaction
model carried gross volume -- what customers moved -- and nothing carried what
the company earned on it, which made LTV uncomputable. The fee cannot be
inferred from the other columns.

Card fees are EUR. FX fees are denominated in currency_from, so
fx_transactions_eur converts them with the same rate_to_eur join it already
uses for amount -- no new join, no new failure mode.

`rate` is the true mid-market cross-rate. The old seed's value was noise (for
currency_to='EUR' rows it should have equalled rate_to_eur and was off by an
order of magnitude). The margin is fee_amount, never a hidden spread.

Placement is by days since acquisition rather than by calendar month, which
makes created_at >= acquired_at true by construction instead of by clamping.

Run from repo root (AFTER gen_users.py):
    uv run python scripts/gen_transactions.py
"""
import csv
import hashlib
import importlib.util
import os
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACQ_SRC = ROOT / "services" / "marketing" / "seeds" / "seed_user_acquisition.csv"
CARD_DST = ROOT / "services" / "core" / "seeds" / "seed_card_transactions.csv"
FX_DST = ROOT / "services" / "core" / "seeds" / "seed_fx_transactions.csv"

# A non-empty SEED_SALT draws a different dataset from the same rules: the
# agent-remediation eval grades a fix on data the fix never ran on. Unset, the
# output is the committed seed.
SALT_PREFIX = f"{os.environ['SEED_SALT']}|" if os.environ.get("SEED_SALT") else ""


def _load_fx_rates():
    """Import gen_fx_rates_eur for its rate_to_eur().

    Not circular: rate_to_eur is a pure function of (currency, date). Only the
    *row set* that script emits depends on this seed, and it runs after us.
    """
    path = ROOT / "scripts" / "gen_fx_rates_eur.py"
    spec = importlib.util.spec_from_file_location("gen_fx_rates_eur", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fx_rates = _load_fx_rates()

TX_WINDOW_END = "2025-07"  # exclusive; transactions run through 2025-06
TARGET_TX = 12000
CARD_SHARE = 0.60

# Users who sign up and never transact: revenue_per_user still carries them,
# with zero revenue.
DORMANT_SHARE = 0.03

# Card purchases the customer later gets refunded. A refund is its own card
# row: the purchase's amount and fee, negated, at the same merchant, within
# REFUND_WITHIN_DAYS of the purchase and before the window ends. The fee goes
# back with the purchase, so a user's net revenue never drops below zero.
REFUND_SHARE = 0.02
REFUND_WITHIN_DAYS = 30

CARD_TAKE_RATE = 0.002  # ~interchange
FX_TAKE_RATE = 0.005    # ~retail FX spread
FEE_JITTER = 0.15       # +/-15% around the take rate, per transaction

CARD_AMOUNT_RANGE = (10.0, 1400.0)      # EUR
FX_EUR_RANGE = (500.0, 15500.0)         # EUR-equivalent, converted to currency_from

CURRENCIES = ["EUR", "USD", "GBP", "CHF", "AUD", "CAD", "JPY", "NOK", "PLN", "SEK"]

MERCHANTS = [
    "Amazon", "Shell", "Lidl", "Deutsche Bahn", "Uber", "Spotify", "IKEA",
    "Carrefour", "Booking.com", "Apple", "Zara", "Decathlon",
]


def _frac(key: str, salt: str) -> float:
    """Deterministic float in [0.0, 1.0)."""
    h = hashlib.md5(f"{SALT_PREFIX}{key}|{salt}".encode()).hexdigest()
    return int(h[:8], 16) / 0x100000000


def _lerp(lo: float, hi: float, f: float) -> float:
    return lo + (hi - lo) * f


def _fee(amount: float, take_rate: float, key: str) -> float:
    """Fee at `take_rate` with deterministic jitter; never rounds to zero."""
    wobble = 1 - FEE_JITTER + 2 * FEE_JITTER * _frac(key, "feejitter")
    return max(round(amount * take_rate * wobble, 2), 0.01)


def _read_acquisitions() -> list[dict]:
    with ACQ_SRC.open() as f:
        return list(csv.DictReader(f))


def build_rows(acquisitions: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (card_rows, fx_rows), each ordered by user then sequence."""
    window_end = datetime.strptime(TX_WINDOW_END + "-01", "%Y-%m-%d")

    tenures: dict[int, tuple[datetime, float]] = {}
    for a in acquisitions:
        if _frac(a["user_id"], "dormant") < DORMANT_SHARE:
            continue
        acquired = datetime.strptime(a["acquired_at"], "%Y-%m-%d %H:%M:%S")
        days = max((window_end - acquired).total_seconds() / 86400.0, 1.0)
        tenures[int(a["user_id"])] = (acquired, days)

    # One rate across the whole population means transaction count scales with
    # tenure: an early cohort transacts more than a December-2024 cohort
    # because it has been around longer, not because it is a different kind of
    # user.
    per_day = TARGET_TX / sum(days for _acq, days in tenures.values())

    card: list[dict] = []
    fx: list[dict] = []
    for user_id, (acquired, days) in sorted(tenures.items()):
        expected = days * per_day
        count = int(expected)
        if _frac(str(user_id), "remainder") < (expected - count):
            count += 1  # resolve the fractional remainder deterministically

        for k in range(count):
            key = f"{user_id}|{k}"
            created = acquired + timedelta(days=_frac(key, "offset") * days)
            created_at = created.strftime("%Y-%m-%d %H:%M:%S")
            date = created_at[:10]

            if _frac(key, "kind") < CARD_SHARE:
                amount = round(_lerp(*CARD_AMOUNT_RANGE, _frac(key, "amount")), 2)
                purchase = {
                    "transaction_id": 0,  # renumbered below
                    "user_id": user_id,
                    "amount": amount,
                    "payer": "",          # filled below, needs the user's name
                    "receiver": MERCHANTS[int(_frac(key, "merchant") * len(MERCHANTS))],
                    "created_at": created_at,
                    "fee_amount": _fee(amount, CARD_TAKE_RATE, key),
                }
                card.append(purchase)
                if _frac(key, "refund") < REFUND_SHARE:
                    refunded = created + timedelta(days=1 + _frac(key, "refund_day") * (REFUND_WITHIN_DAYS - 1))
                    if refunded < window_end:
                        card.append(dict(
                            purchase,
                            amount=-purchase["amount"],
                            fee_amount=-purchase["fee_amount"],
                            created_at=refunded.strftime("%Y-%m-%d %H:%M:%S"),
                        ))
            else:
                ccy_from = CURRENCIES[int(_frac(key, "from") * len(CURRENCIES))]
                ccy_to = CURRENCIES[int(_frac(key, "to") * len(CURRENCIES))]
                if ccy_to == ccy_from:  # a same-currency FX trade is not a trade
                    ccy_to = CURRENCIES[(CURRENCIES.index(ccy_from) + 1) % len(CURRENCIES)]
                rate_from = fx_rates.rate_to_eur(ccy_from, date)
                rate_to = fx_rates.rate_to_eur(ccy_to, date)
                eur_value = _lerp(*FX_EUR_RANGE, _frac(key, "amount"))
                amount = round(eur_value / rate_from, 2)
                fx.append({
                    "transaction_id": 0,
                    "user_id": user_id,
                    "amount": amount,
                    "currency_from": ccy_from,
                    "currency_to": ccy_to,
                    "rate": round(rate_from / rate_to, 6),
                    "created_at": created_at,
                    "fee_amount": _fee(amount, FX_TAKE_RATE, key),
                })

    for rows in (card, fx):
        rows.sort(key=lambda r: (r["created_at"], r["user_id"]))
        for i, row in enumerate(rows, start=1):
            row["transaction_id"] = i
    return card, fx


def main() -> None:
    acquisitions = _read_acquisitions()
    names = {int(a["user_id"]): a["user_id"] for a in acquisitions}
    card, fx = build_rows(acquisitions)
    # payer is cosmetic; the seed has always carried a person-shaped string.
    for row in card:
        row["payer"] = f"user {names[row['user_id']]}"

    with CARD_DST.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["transaction_id", "user_id", "amount",
                                          "payer", "receiver", "created_at", "fee_amount"])
        w.writeheader()
        w.writerows(card)
    with FX_DST.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["transaction_id", "user_id", "amount",
                                          "currency_from", "currency_to", "rate",
                                          "created_at", "fee_amount"])
        w.writeheader()
        w.writerows(fx)
    print(f"wrote {len(card)} rows to {CARD_DST}")
    print(f"wrote {len(fx)} rows to {FX_DST}")


if __name__ == "__main__":
    main()
