import importlib.util
import pathlib
import unittest

_MOD_PATH = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "gen_marketing_spend.py"
_spec = importlib.util.spec_from_file_location("gen_marketing_spend", _MOD_PATH)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


class BuildRowsTest(unittest.TestCase):
    def setUp(self):
        self.rows = gen.build_rows()

    def test_row_count_is_ad_campaigns_plus_referral_months(self):
        # 11 hash-driven ad campaigns x 24 months, plus one referral row for
        # each month that actually acquired a referred user.
        ad_rows = [r for r in self.rows if r["channel"] != "referral"]
        referral_rows = [r for r in self.rows if r["channel"] == "referral"]
        self.assertEqual(len(ad_rows), 11 * 24)
        self.assertGreater(len(referral_rows), 0)
        self.assertLessEqual(len(referral_rows), 24)

    def test_columns_match_existing_seed_header(self):
        self.assertEqual(
            list(self.rows[0].keys()),
            ["spend_id", "channel", "campaign", "spend_date",
             "amount", "currency", "impressions", "clicks"],
        )

    def test_spend_id_is_sequential_from_one(self):
        self.assertEqual(
            [r["spend_id"] for r in self.rows], list(range(1, len(self.rows) + 1))
        )

    def test_is_deterministic(self):
        self.assertEqual(gen.build_rows(), gen.build_rows())

    def test_covers_every_month_from_2023_01_to_2024_12(self):
        months = sorted({r["spend_date"][:7] for r in self.rows})
        expected = [f"{y}-{m:02d}" for y in (2023, 2024) for m in range(1, 13)]
        self.assertEqual(months, expected)

    def test_every_month_has_all_eleven_ad_campaigns(self):
        seen = {}
        for r in self.rows:
            if r["channel"] == "referral":
                continue
            seen.setdefault(r["spend_date"][:7], set()).add(r["campaign"])
        for month, campaigns in seen.items():
            self.assertEqual(len(campaigns), 11, f"{month} has {len(campaigns)} campaigns")

    def test_currency_is_always_eur(self):
        self.assertEqual({r["currency"] for r in self.rows}, {"EUR"})

    def test_amount_within_channel_range(self):
        # referral amounts are bounty x referral count, not a hash-driven
        # draw from CHANNEL_AMOUNT_RANGE, so they're covered separately by
        # test_referral_spend_is_bounty_times_referrals_that_month.
        for r in self.rows:
            if r["channel"] == "referral":
                continue
            lo, hi = gen.CHANNEL_AMOUNT_RANGE[r["channel"]]
            self.assertGreaterEqual(r["amount"], lo)
            self.assertLessEqual(r["amount"], hi)

    def test_amount_rounded_to_cents(self):
        for r in self.rows:
            self.assertEqual(r["amount"], round(r["amount"], 2))

    def test_clicks_never_exceed_impressions(self):
        # referral rows carry no impressions/clicks (a payout, not an ad
        # campaign) and are covered separately by
        # test_referral_rows_carry_no_impressions_or_clicks.
        for r in self.rows:
            if r["channel"] == "referral":
                continue
            self.assertLessEqual(r["clicks"], r["impressions"])
            self.assertGreater(r["clicks"], 0)

    def test_spend_date_is_parseable_timestamp(self):
        import datetime
        for r in self.rows:
            datetime.datetime.strptime(r["spend_date"], "%Y-%m-%d %H:%M:%S")

    def test_paid_channels_are_exactly_the_six_expected(self):
        # organic is unpaid and must never appear in spend. referral is now
        # paid: a referral programme pays the referrer for each signup.
        self.assertEqual(
            {r["channel"] for r in self.rows},
            {"google_ads", "meta_ads", "tiktok_ads", "email", "affiliate", "referral"},
        )

    def test_referral_spend_is_bounty_times_referrals_that_month(self):
        import collections
        import csv as _csv
        with gen.ACQ_SRC.open() as f:
            acq = list(_csv.DictReader(f))
        referrals = collections.Counter(
            a["acquired_at"][:7] for a in acq if a["channel"] == "referral"
        )
        for row in self.rows:
            if row["channel"] != "referral":
                continue
            month = row["spend_date"][:7]
            self.assertAlmostEqual(
                row["amount"], round(gen.REFERRAL_BOUNTY_EUR * referrals[month], 2), places=2
            )

    def test_referral_rows_carry_no_impressions_or_clicks(self):
        for row in self.rows:
            if row["channel"] == "referral":
                self.assertEqual(row["impressions"], 0)
                self.assertEqual(row["clicks"], 0)

    def test_referral_is_present_so_the_channel_counts_as_paid(self):
        # marketing_cost_per_user derives paidness from presence in this seed.
        self.assertIn("referral", {r["channel"] for r in self.rows})


if __name__ == "__main__":
    unittest.main()
