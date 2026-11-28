#!/usr/bin/env python3
"""Generate the two user seeds from a single source of truth.

Writes projects/core/seeds/seed_users.csv and
projects/marketing/seeds/seed_user_acquisition.csv.

The two files must agree on user_id -> date: finance allocates operational cost
by core's seed_users.created_at, marketing allocates spend by
seed_user_acquisition.acquired_at, and if they disagree the two cost models
describe different cohorts for the same user. They are identical today by
coincidence; emitting both from one generator makes it an invariant.

Everything derives from a stable md5 hash of the user_id, never `random`, so
re-running produces no diff.

Run from repo root:  uv run python scripts/gen_users.py
"""
import csv
import hashlib
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
USERS_DST = ROOT / "projects" / "core" / "seeds" / "seed_users.csv"
ACQ_DST = ROOT / "projects" / "marketing" / "seeds" / "seed_user_acquisition.csv"

# A non-empty SEED_SALT draws a different dataset from the same rules: the
# agent-remediation eval grades a fix on data the fix never ran on. Unset, the
# output is the committed seed.
SALT_PREFIX = f"{os.environ['SEED_SALT']}|" if os.environ.get("SEED_SALT") else ""

N_USERS = 2000

# Acquisition window. MUST match YEARS in gen_marketing_spend.py and
# gen_operational_costs.py -- assert_operational_costs_within_acquisition_window
# fails the build if costs fall outside the window these produce.
YEARS = (2023, 2024)

# Signups grow 5% per month index, so cohorts get larger over the window and a
# cohort curve has something to show. Flat signups would be a fine dataset and
# a boring one.
MONTHLY_GROWTH = 0.05

# (channel, share of users, campaigns). Shares sum to 1.0 and reproduce the
# mix the 50-user seed had. The (channel, campaign) pairs MUST match CAMPAIGNS
# in gen_marketing_spend.py -- marketing_cost_per_user joins spend to
# acquisitions on (channel, month), so a channel with no spend row silently
# gets 0 CAC.
#
# organic is the ONLY unpaid channel. referral costs a bounty paid to the
# referrer; treating it as free understated CAC on a fifth of the user base.
CHANNELS = [
    ("google_ads", 0.36, ["gad_brand", "gad_generic", "gad_retargeting"]),
    ("referral",   0.20, ["refer_a_friend"]),
    ("meta_ads",   0.16, ["fb_prospecting", "ig_lookalike"]),
    ("organic",    0.16, ["organic"]),
    ("tiktok_ads", 0.08, ["tt_awareness", "tt_conversion"]),
    ("affiliate",  0.02, ["aff_partner_a", "aff_partner_b"]),
    ("email",      0.02, ["newsletter", "winback"]),
]

FIRST_NAMES = [
    "Lena", "Elijah", "Emma", "Lea", "Noah", "Sofia", "Liam", "Mila",
    "Hugo", "Nora", "Aris", "Yuki", "Omar", "Ines", "Kai", "Zara",
    "Milan", "Aya", "Tomas", "Freya", "Ravi", "Nina", "Luca", "Sana",
]
LAST_NAMES = [
    "Muller", "Haddad", "Ivanov", "Johnson", "Novak", "Rossi", "Dubois",
    "Silva", "Kowalski", "Andersen", "Berg", "Costa", "Nakamura", "Okafor",
    "Petrov", "Ricci", "Sorensen", "Toth", "Varga", "Weber", "Yilmaz",
    "Zhang", "Larsen", "Moreau",
]

BIRTH_YEAR_RANGE = (1955, 2003)  # inclusive lower, exclusive upper


def _frac(user_id: int, salt: str) -> float:
    """Deterministic float in [0.0, 1.0). `salt` gives independent draws per field."""
    h = hashlib.md5(f"{SALT_PREFIX}{user_id}|{salt}".encode()).hexdigest()
    return int(h[:8], 16) / 0x100000000


def _months() -> list[str]:
    return [f"{y}-{m:02d}" for y in YEARS for m in range(1, 13)]


def _monthly_counts() -> list[int]:
    """Users acquired per month, growing, summing to exactly N_USERS."""
    months = _months()
    weights = [1 + MONTHLY_GROWTH * i for i in range(len(months))]
    total = sum(weights)
    counts = [round(N_USERS * w / total) for w in weights]
    counts[-1] += N_USERS - sum(counts)  # absorb rounding drift in the last month
    return counts


def _channel_for(user_id: int) -> tuple[str, str]:
    """Pick a (channel, campaign) pair by cumulative share."""
    draw = _frac(user_id, "channel")
    cumulative = 0.0
    for channel, share, campaigns in CHANNELS:
        cumulative += share
        if draw < cumulative:
            break
    else:  # float drift past 1.0 on the final bucket
        channel, _share, campaigns = CHANNELS[-1]
    index = int(_frac(user_id, "campaign") * len(campaigns))
    return channel, campaigns[min(index, len(campaigns) - 1)]


def _timestamp(user_id: int, month: str) -> str:
    """A timestamp inside `month`. Day capped at 28 so every month is valid."""
    day = 1 + int(_frac(user_id, "day") * 28)
    hour = int(_frac(user_id, "hour") * 24)
    minute = int(_frac(user_id, "minute") * 60)
    second = int(_frac(user_id, "second") * 60)
    return f"{month}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"


def build_rows() -> tuple[list[dict], list[dict]]:
    """Return (users, acquisitions), one row each per user, ordered by user_id."""
    users: list[dict] = []
    acquisitions: list[dict] = []
    user_id = 1
    for month, count in zip(_months(), _monthly_counts()):
        for _ in range(count):
            created_at = _timestamp(user_id, month)
            channel, campaign = _channel_for(user_id)
            first = FIRST_NAMES[int(_frac(user_id, "first") * len(FIRST_NAMES))]
            last = LAST_NAMES[int(_frac(user_id, "last") * len(LAST_NAMES))]
            lo, hi = BIRTH_YEAR_RANGE
            users.append({
                "user_id": user_id,
                "name": f"{first} {last}",
                # user_id in the local part guarantees uniqueness across the
                # 576 name combinations.
                "email": f"{first.lower()}.{last.lower()}{user_id}@example.com",
                "birth_year": lo + int(_frac(user_id, "birth") * (hi - lo)),
                "created_at": created_at,
            })
            acquisitions.append({
                "user_id": user_id,
                "channel": channel,
                "campaign": campaign,
                "acquired_at": created_at,  # identical by construction
            })
            user_id += 1
    return users, acquisitions


def _write(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    users, acquisitions = build_rows()
    _write(USERS_DST, users, ["user_id", "name", "email", "birth_year", "created_at"])
    _write(ACQ_DST, acquisitions, ["user_id", "channel", "campaign", "acquired_at"])
    log.info("wrote %s rows to %s", len(users), USERS_DST)
    log.info("wrote %s rows to %s", len(acquisitions), ACQ_DST)


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(message)s")
    main()
