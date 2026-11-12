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


class RuntimeVersionWiringTest(unittest.TestCase):
    def test_no_workflow_names_a_runtime_version(self):
        for name, text in (("release.yml", _RELEASE), ("ci.yml", _CI)):
            with self.subTest(workflow=name):
                self.assertIsNone(re.search(r"continuo-python-runtime(==|@v)[0-9]", text))

    def test_both_workflows_install_and_check_the_runtime_the_image_names(self):
        for name, text in (("release.yml", _RELEASE), ("ci.yml", _CI)):
            with self.subTest(workflow=name):
                self.assertIn("python3 scripts/image_pins.py runtime-version", text)
                self.assertIn("python3 scripts/image_pins.py check-installed", text)


class CiChecksTest(unittest.TestCase):
    def test_ci_checks_the_dbt_pins_of_the_changed_dbt_service(self):
        self.assertIn(
            'python3 scripts/image_pins.py check-dbt "services/${{ needs.check-single-service.outputs.service }}"',
            _CI,
        )

    def test_ci_runs_every_scripts_test(self):
        self.assertIn(
            "uvx pytest==9.1.1 scripts/tests/test_release_sh.py scripts/tests/test_image_pins.py "
            "scripts/tests/test_workflows.py",
            _CI,
        )
