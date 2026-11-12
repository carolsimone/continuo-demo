"""Text checks of the release and CI workflows."""

import pathlib
import re
import unittest

_WORKFLOWS = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows"
_RELEASE = (_WORKFLOWS / "release.yml").read_text()
_CI = (_WORKFLOWS / "ci.yml").read_text()


class ReleaseDispatchTest(unittest.TestCase):
    def test_the_dispatch_offers_a_rebaseline_input(self):
        self.assertRegex(
            _RELEASE,
            r"\n      rebaseline:\n        description: .+\n        required: false\n"
            r"        default: false\n        type: boolean\n",
        )

    def test_the_release_step_passes_rebaseline_to_release_sh(self):
        self.assertIn("REBASELINE: ${{ inputs.rebaseline == true }}", _RELEASE)

    def test_force_bootstrap_no_longer_offers_to_rebaseline(self):
        for old in ("re-baseline the whole estate", "re-baselining the whole estate"):
            self.assertNotIn(old, _RELEASE)
