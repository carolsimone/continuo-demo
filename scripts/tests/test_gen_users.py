import collections
import importlib.util
import pathlib
import unittest

_MOD_PATH = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "gen_users.py"
_spec = importlib.util.spec_from_file_location("gen_users", _MOD_PATH)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


class BuildRowsTest(unittest.TestCase):
    def setUp(self):
        self.users, self.acquisitions = gen.build_rows()

    def test_emits_exactly_n_users_in_both_files(self):
        self.assertEqual(len(self.users), gen.N_USERS)
        self.assertEqual(len(self.acquisitions), gen.N_USERS)

    def test_user_ids_are_dense_and_one_based(self):
        self.assertEqual([u["user_id"] for u in self.users], list(range(1, gen.N_USERS + 1)))

    def test_the_two_files_agree_on_every_users_date(self):
        # The invariant the single generator exists to guarantee (design decision 9).
        created = {u["user_id"]: u["created_at"] for u in self.users}
        acquired = {a["user_id"]: a["acquired_at"] for a in self.acquisitions}
        self.assertEqual(created, acquired)

    def test_every_acquisition_falls_inside_the_window(self):
        months = sorted({a["acquired_at"][:7] for a in self.acquisitions})
        self.assertEqual(months[0], "2023-01")
        self.assertEqual(months[-1], "2024-12")
        self.assertEqual(len(months), 24)

    def test_columns_match_the_existing_seed_headers(self):
        self.assertEqual(
            list(self.users[0].keys()),
            ["user_id", "name", "email", "birth_year", "created_at"],
        )
        self.assertEqual(
            list(self.acquisitions[0].keys()),
            ["user_id", "channel", "campaign", "acquired_at"],
        )

    def test_channel_mix_is_within_two_points_of_target(self):
        counts = collections.Counter(a["channel"] for a in self.acquisitions)
        for channel, share, _campaigns in gen.CHANNELS:
            actual = counts[channel] / gen.N_USERS
            self.assertAlmostEqual(actual, share, delta=0.02, msg=channel)

    def test_referral_and_organic_channels_are_present(self):
        # referral is paid (a bounty to the referrer) -- design decision 8a.
        channels = {a["channel"] for a in self.acquisitions}
        self.assertIn("referral", channels)
        self.assertIn("organic", channels)

    def test_campaigns_stay_inside_their_channel(self):
        allowed = {c: set(camps) for c, _s, camps in gen.CHANNELS}
        for a in self.acquisitions:
            self.assertIn(a["campaign"], allowed[a["channel"]])

    def test_emails_are_unique(self):
        emails = [u["email"] for u in self.users]
        self.assertEqual(len(set(emails)), len(emails))

    def test_is_deterministic(self):
        again_users, again_acq = gen.build_rows()
        self.assertEqual(self.users, again_users)
        self.assertEqual(self.acquisitions, again_acq)

    def test_signups_grow_over_the_window(self):
        by_month = collections.Counter(a["acquired_at"][:7] for a in self.acquisitions)
        self.assertGreater(by_month["2024-12"], by_month["2023-01"])


class SaltTest(unittest.TestCase):
    def test_a_salt_draws_another_dataset_by_the_same_rules(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"SEED_SALT": "eval-hidden"}):
            spec = importlib.util.spec_from_file_location("gen_users_salted", _MOD_PATH)
            salted = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(salted)
        users, acquisitions = gen.build_rows()
        salted_users, salted_acquisitions = salted.build_rows()
        self.assertEqual(len(salted_users), len(users))
        self.assertNotEqual(
            [a["channel"] for a in salted_acquisitions],
            [a["channel"] for a in acquisitions],
        )


if __name__ == "__main__":
    unittest.main()
