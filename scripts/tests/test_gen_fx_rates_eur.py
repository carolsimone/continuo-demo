import csv
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


gen = _load("gen_fx_rates_eur")


class BuildRowsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (_ROOT / "projects" / "core" / "seeds" / "seed_fx_transactions.csv").open(newline="") as f:
            cls.txns = list(csv.DictReader(f))
        cls.rows = gen.build_rows(cls.txns)
        cls.by_currency = {}
        for r in cls.rows:
            cls.by_currency.setdefault(r["currency"], []).append(r["rate_date"])

    def test_rates_are_published_on_weekdays_only(self):
        for r in self.rows:
            self.assertLess(datetime.date.fromisoformat(r["rate_date"]).weekday(), 5, msg=str(r))

    def test_every_currency_has_a_rate_every_weekday(self):
        dates = set(self.by_currency["EUR"])
        for currency in gen.BASE_RATES:
            self.assertEqual(set(self.by_currency[currency]), dates, msg=currency)

    def test_every_transaction_has_a_rate_published_on_or_before_it(self):
        for t in self.txns:
            day = t["created_at"][:10]
            self.assertTrue(any(d <= day for d in self.by_currency[t["currency_from"]]), msg=str(t))

    def test_eur_is_one(self):
        self.assertTrue(all(r["rate_to_eur"] == 1.0 for r in self.rows if r["currency"] == "EUR"))

    def test_rows_are_sorted_by_currency_then_date(self):
        keys = [(r["currency"], r["rate_date"]) for r in self.rows]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(keys), len(set(keys)))


if __name__ == "__main__":
    unittest.main()
