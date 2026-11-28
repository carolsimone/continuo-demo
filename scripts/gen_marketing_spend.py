#!/usr/bin/env python3
"""Generate projects/marketing/seeds/seed_marketing_spend.csv.

One row per (campaign, month) for 2023-01 .. 2024-12 — the window covered by
seed_user_acquisition. Spend and acquisition must overlap, otherwise
marketing_cost_per_user has spend with no users to allocate it to. Referral
rows are computed from seed_user_acquisition.csv (bounty x referrals that
month), so this script must run after gen_users.py.

Amounts, dates, impressions and clicks are derived from a stable md5 hash of
(campaign, month), never `random`, so re-running produces no diff.

Run from repo root:  uv run python scripts/gen_marketing_spend.py
"""
import csv
import hashlib
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DST = ROOT / "projects" / "marketing" / "seeds" / "seed_marketing_spend.csv"
ACQ_SRC = ROOT / "projects" / "marketing" / "seeds" / "seed_user_acquisition.csv"

# A non-empty SEED_SALT draws a different dataset from the same rules: the
# agent-remediation eval grades a fix on data the fix never ran on. Unset, the
# output is the committed seed.
SALT_PREFIX = f"{os.environ['SEED_SALT']}|" if os.environ.get("SEED_SALT") else ""

YEARS = (2023, 2024)  # MUST match gen_users.py and gen_operational_costs.py

# (channel, campaign) — the 11 pairs already present in the seed, preserved so
# seed_user_acquisition.campaign values keep matching.
CAMPAIGNS = [
    ("google_ads", "gad_brand"),
    ("google_ads", "gad_generic"),
    ("google_ads", "gad_retargeting"),
    ("meta_ads", "fb_prospecting"),
    ("meta_ads", "ig_lookalike"),
    ("tiktok_ads", "tt_awareness"),
    ("tiktok_ads", "tt_conversion"),
    ("email", "newsletter"),
    ("email", "winback"),
    ("affiliate", "aff_partner_a"),
    ("affiliate", "aff_partner_b"),
    ("referral", "refer_a_friend"),
]

# EUR bounds per campaign-month. With 2,000 users over 24 months a paid
# campaign-month acquires ~5 users, so these describe a real budget rather
# than a single user's CAC -- ~EUR 193 per campaign-month over 264
# ad campaign-months lands paid CAC at ~EUR 40 and blended CAC at ~EUR 30.
#
# referral is NOT here: a referral payout is incurred per acquisition, not
# committed as a monthly budget, so its row is computed rather than drawn.
CHANNEL_AMOUNT_RANGE = {
    "google_ads": (40.0, 500.0),
    "meta_ads": (40.0, 400.0),
    "tiktok_ads": (30.0, 300.0),
    "email": (4.0, 80.0),
    "affiliate": (30.0, 360.0),
}

# Paid to the referrer for each referred signup. Mirrored as
# `vars: referral_bounty_eur` in projects/marketing/dbt_project.yml;
# assert_referral_cac_equals_bounty.sql fails the build if they drift apart.
REFERRAL_BOUNTY_EUR = 25.0

IMPRESSIONS_RANGE = (20000, 800000)
CTR_RANGE = (0.005, 0.06)


def _frac(campaign: str, month: str, salt: str) -> float:
    """Deterministic float in [0.0, 1.0] from a stable hash.

    `salt` yields independent draws for each field of the same row.
    """
    h = hashlib.md5(f"{SALT_PREFIX}{campaign}|{month}|{salt}".encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def _lerp(lo: float, hi: float, f: float) -> float:
    return lo + (hi - lo) * f


def _referrals_by_month() -> dict[str, int]:
    """How many users each month acquired through the referral programme."""
    counts: dict[str, int] = {}
    with ACQ_SRC.open() as f:
        for row in csv.DictReader(f):
            if row["channel"] == "referral":
                month = row["acquired_at"][:7]
                counts[month] = counts.get(month, 0) + 1
    return counts


def build_rows() -> list[dict]:
    """Return all (campaign, month) spend rows, ordered by month then campaign."""
    rows = []
    spend_id = 1
    referrals = _referrals_by_month()
    for year in YEARS:
        for month_num in range(1, 13):
            month = f"{year}-{month_num:02d}"
            for channel, campaign in CAMPAIGNS:
                if channel == "referral":
                    referred = referrals.get(month, 0)
                    if referred == 0:
                        continue  # no referrals that month means no payout row
                    rows.append({
                        "spend_id": spend_id,
                        "channel": channel,
                        "campaign": campaign,
                        "spend_date": f"{month}-01 00:00:00",
                        "amount": round(REFERRAL_BOUNTY_EUR * referred, 2),
                        "currency": "EUR",
                        "impressions": 0,  # meaningless for a payout
                        "clicks": 0,
                    })
                    spend_id += 1
                    continue

                lo, hi = CHANNEL_AMOUNT_RANGE[channel]
                amount = round(_lerp(lo, hi, _frac(campaign, month, "amount")), 2)

                # Day capped at 28 so every month is valid without calendar logic.
                # Clamped: _frac() can return exactly 1.0, which would otherwise
                # give day=29 (invalid in non-leap Februaries) or minute=60
                # (invalid in every month).
                day = 1 + min(27, int(_frac(campaign, month, "day") * 28))
                hour = 8 + int(_frac(campaign, month, "hour") * 13)  # 08..20
                minute = min(59, int(_frac(campaign, month, "minute") * 60))

                impressions = int(_lerp(*IMPRESSIONS_RANGE, _frac(campaign, month, "impr")))
                ctr = _lerp(*CTR_RANGE, _frac(campaign, month, "ctr"))
                clicks = max(1, int(impressions * ctr))

                rows.append({
                    "spend_id": spend_id,
                    "channel": channel,
                    "campaign": campaign,
                    "spend_date": f"{month}-{day:02d} {hour:02d}:{minute:02d}:00",
                    "amount": amount,
                    "currency": "EUR",
                    "impressions": impressions,
                    "clicks": clicks,
                })
                spend_id += 1
    return rows


def main():
    rows = build_rows()
    with DST.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {DST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
