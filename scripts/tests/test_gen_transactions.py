import datetime
import importlib.util
import pathlib
import unittest

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load("gen_transactions")
gen_users = _load("gen_users")


class BuildRowsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _users, cls.acquisitions = gen_users.build_rows()
        cls.card, cls.fx = gen.build_rows(cls.acquisitions)

    def test_total_transactions_near_target(self):
        total = len(self.card) + len(self.fx)
        self.assertAlmostEqual(total, gen.TARGET_TX, delta=gen.TARGET_TX * 0.05)

    def test_card_share_is_about_sixty_percent(self):
        total = len(self.card) + len(self.fx)
        self.assertAlmostEqual(len(self.card) / total, gen.CARD_SHARE, delta=0.03)

    def test_no_transaction_predates_its_user(self):
        # The guarantee core/tests/assert_transactions_after_acquisition.sql
        # enforces in the warehouse. Previously true only by accident, because
        # every transaction was 2024 and every acquisition <= 2023.
        acquired = {
            int(a["user_id"]): datetime.datetime.strptime(a["acquired_at"], "%Y-%m-%d %H:%M:%S")
            for a in self.acquisitions
        }
        for row in self.card + self.fx:
            ts = datetime.datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
            self.assertGreaterEqual(ts, acquired[row["user_id"]], msg=str(row))

    def test_no_transaction_past_the_window_end(self):
        for row in self.card + self.fx:
            self.assertLess(row["created_at"][:7], gen.TX_WINDOW_END)

    def test_columns_match_the_existing_seed_headers_plus_fee(self):
        self.assertEqual(
            list(self.card[0].keys()),
            ["transaction_id", "user_id", "amount", "payer", "receiver",
             "created_at", "fee_amount"],
        )
        self.assertEqual(
            list(self.fx[0].keys()),
            ["transaction_id", "user_id", "amount", "currency_from", "currency_to",
             "rate", "created_at", "fee_amount"],
        )

    def test_every_purchase_fee_is_positive(self):
        for row in [r for r in self.card if r["amount"] > 0] + self.fx:
            self.assertGreater(row["fee_amount"], 0, msg=str(row))

    def test_a_refund_negates_an_earlier_purchase(self):
        refunds = [r for r in self.card if r["amount"] < 0]
        self.assertGreater(len(refunds), 0)
        purchases = {}
        for r in self.card:
            if r["amount"] > 0:
                purchases.setdefault((r["user_id"], r["receiver"], -r["amount"], -r["fee_amount"]), []).append(r)
        for refund in refunds:
            key = (refund["user_id"], refund["receiver"], refund["amount"], refund["fee_amount"])
            refunded = datetime.datetime.strptime(refund["created_at"], "%Y-%m-%d %H:%M:%S")
            earlier = [
                p for p in purchases.get(key, [])
                if datetime.timedelta(0) < refunded - datetime.datetime.strptime(p["created_at"], "%Y-%m-%d %H:%M:%S")
                <= datetime.timedelta(days=gen.REFUND_WITHIN_DAYS)
            ]
            self.assertTrue(earlier, msg=str(refund))

    def test_some_users_never_transact(self):
        active = {r["user_id"] for r in self.card + self.fx}
        dormant_share = 1 - len(active) / len(self.acquisitions)
        self.assertAlmostEqual(dormant_share, gen.DORMANT_SHARE, delta=0.015)

    def test_card_fee_tracks_the_take_rate(self):
        blended = sum(r["fee_amount"] for r in self.card) / sum(r["amount"] for r in self.card)
        self.assertAlmostEqual(blended, gen.CARD_TAKE_RATE, delta=gen.CARD_TAKE_RATE * 0.1)

    def test_fx_fee_tracks_the_take_rate(self):
        blended = sum(r["fee_amount"] for r in self.fx) / sum(r["amount"] for r in self.fx)
        self.assertAlmostEqual(blended, gen.FX_TAKE_RATE, delta=gen.FX_TAKE_RATE * 0.1)

    def test_fx_currencies_always_differ(self):
        for row in self.fx:
            self.assertNotEqual(row["currency_from"], row["currency_to"])

    def test_fx_rate_is_the_true_cross_rate(self):
        # The old seed's `rate` was noise: for currency_to='EUR' rows it should
        # have equalled rate_to_eur and was off by an order of magnitude. It is
        # now the real mid-market cross-rate. The company's margin is
        # fee_amount, never a hidden spread.
        for row in self.fx[:200]:
            date = row["created_at"][:10]
            expected = gen.fx_rates.rate_to_eur(row["currency_from"], date) / \
                gen.fx_rates.rate_to_eur(row["currency_to"], date)
            self.assertAlmostEqual(row["rate"], round(expected, 6), places=5)

    def test_transaction_ids_are_dense_per_file(self):
        self.assertEqual([r["transaction_id"] for r in self.card], list(range(1, len(self.card) + 1)))
        self.assertEqual([r["transaction_id"] for r in self.fx], list(range(1, len(self.fx) + 1)))

    def test_is_deterministic(self):
        again_card, again_fx = gen.build_rows(self.acquisitions)
        self.assertEqual(self.card, again_card)
        self.assertEqual(self.fx, again_fx)


if __name__ == "__main__":
    unittest.main()
