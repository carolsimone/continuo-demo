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
                self.assertIn('listed="$(uv tool list --color never)"', text)
                self.assertRegex(
                    text,
                    r'python3 scripts/image_pins\.py check-installed "services/[^"]+" <<< "\$listed"',
                )


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


def _step(text, name):
    """The text of the step called `name`: its `- name:` line to the end of its last line.

    The workflows separate their steps by a blank line and keep none inside one.
    """
    marker = f"\n      - name: {name}\n"
    start = text.find(marker)
    if start == -1:
        raise AssertionError(f"no step named {name!r}")
    start += 1
    end = text.find("\n\n", start)
    return text[start : len(text) if end == -1 else end + 1]


def _position(text, name):
    position = text.find(f"      - name: {name}\n")
    if position == -1:
        raise AssertionError(f"no step named {name!r}")
    return position


_ODCS_DETECT = (
    'if compgen -G "services/${SERVICE}/contracts/*.odcs.yaml" > /dev/null; then KIND="python-odcs"; '
    'elif [ -d "services/${SERVICE}/contracts" ]; then KIND="python"; else KIND="dbt"; fi'
)
_BOTH_PYTHON_KINDS = "startsWith(needs.detect.outputs.kind, 'python') && needs.detect.outputs.skip_release != 'true'"
_PYTHON_ONLY = "needs.detect.outputs.kind == 'python' && needs.detect.outputs.skip_release != 'true'"
_ODCS_ONLY = "needs.detect.outputs.kind == 'python-odcs' && needs.detect.outputs.skip_release != 'true'"
_SHARED_PYTHON_STEPS = (
    "Set up uv",
    "Read the runtime version from the service image",
    "Install continuo-python-runtime",
    "Check the installed runtime is the image's",
    "Lint python scripts (no hand-written SQL)",
    "Validate python contracts",
    "Compose full image ref for python release",
)
_BUILD = "Build and push the changed service image"
_COMPOSE = "Compose full image ref for python release"
_PACK = "Pack the ODCS bundle"
_UPLOAD_BUNDLE = "Upload odcs-bundle.json to S3"
_POST = "Drive the release through continuo"
_PACK_DRY_RUN = "Dry-run the ODCS bundle pack"


class PythonOdcsKindTest(unittest.TestCase):
    def test_detect_sets_python_odcs_when_odcs_files_exist(self):
        # release.yml detects the kind for a dispatch and for a push; ci.yml for a PR.
        self.assertEqual(_RELEASE.count(_ODCS_DETECT), 2)
        self.assertEqual(_CI.count(_ODCS_DETECT), 1)
        for name, text in (("release.yml", _RELEASE), ("ci.yml", _CI)):
            with self.subTest(workflow=name):
                # The plain contracts/ check is only the `elif` of the ODCS one now.
                self.assertNotRegex(text, r'(?m)^\s*if \[ -d "services/\$\{SERVICE\}/contracts" \]')

    def test_the_python_steps_run_for_both_python_kinds(self):
        for name in _SHARED_PYTHON_STEPS:
            with self.subTest(step=name):
                self.assertIn(f"\n        if: {_BOTH_PYTHON_KINDS}\n", _step(_RELEASE, name))

    def test_the_post_sends_the_full_image_ref_for_both_python_kinds(self):
        self.assertIn(
            "          IMAGE_TAG: ${{ startsWith(needs.detect.outputs.kind, 'python') "
            "&& env.PYTHON_IMAGE_TAG || needs.detect.outputs.image_tag }}\n",
            _step(_RELEASE, _POST),
        )

    def test_the_merge_and_the_contract_upload_stay_python_only(self):
        for name in ("Merge python contracts", "Upload contract.yaml to S3"):
            with self.subTest(step=name):
                self.assertIn(f"\n        if: {_PYTHON_ONLY}\n", _step(_RELEASE, name))
        # No other step is guarded by the plain python kind.
        self.assertEqual(_RELEASE.count("needs.detect.outputs.kind == 'python' &&"), 2)

    def test_pack_runs_after_the_push_and_before_the_upload_and_the_post(self):
        lint = _position(_RELEASE, "Lint python scripts (no hand-written SQL)")
        validate = _position(_RELEASE, "Validate python contracts")
        build = _position(_RELEASE, _BUILD)
        compose = _position(_RELEASE, _COMPOSE)
        pack = _position(_RELEASE, _PACK)
        upload = _position(_RELEASE, _UPLOAD_BUNDLE)
        post = _position(_RELEASE, _POST)
        self.assertLess(lint, validate)
        self.assertLess(validate, build)
        self.assertLess(build, compose)
        # The pack names the image `compose` sets in PYTHON_IMAGE_TAG.
        self.assertLess(compose, pack)
        self.assertLess(pack, upload)
        self.assertLess(upload, post)

    def test_pack_names_the_pushed_image_and_writes_the_bundle(self):
        step = _step(_RELEASE, _PACK)
        self.assertIn(f"\n        if: {_ODCS_ONLY}\n", step)
        self.assertIn(
            "        run: |\n"
            '          continuo-runtime pack "services/${{ needs.detect.outputs.service }}/contracts" \\\n'
            '            --service "${{ needs.detect.outputs.service }}" \\\n'
            '            --repo-root "services/${{ needs.detect.outputs.service }}" \\\n'
            "            --dialect postgres \\\n"
            '            --image "${PYTHON_IMAGE_TAG}" \\\n'
            '            --out "${RUNNER_TEMP}/odcs-bundle.json"\n',
            step,
        )

    def test_the_odcs_bundle_is_uploaded_under_the_release(self):
        step = _step(_RELEASE, _UPLOAD_BUNDLE)
        self.assertIn(f"\n        if: {_ODCS_ONLY}\n", step)
        self.assertIn(
            "        env:\n"
            "          AWS_ACCESS_KEY_ID: ${{ secrets.HETZNER_S3_ACCESS_KEY_ID }}\n"
            "          AWS_SECRET_ACCESS_KEY: ${{ secrets.HETZNER_S3_SECRET_ACCESS_KEY }}\n"
            "        run: |\n"
            '          aws s3 cp "${RUNNER_TEMP}/odcs-bundle.json" \\\n'
            '            "s3://continuo-dev/${{ needs.detect.outputs.service }}/'
            '${{ needs.detect.outputs.release_id }}/odcs-bundle.json" \\\n'
            "            --endpoint-url https://nbg1.your-objectstorage.com \\\n"
            "            --region eu-central-1\n",
            step,
        )
        # The upload completes before the POST, which does no existence check.
        comment = _RELEASE[: _position(_RELEASE, _UPLOAD_BUNDLE)].rsplit("\n\n", 1)[1]
        self.assertIn("upload to complete before the POST", re.sub(r"\n\s*# ?", " ", comment))

    def test_ci_runs_the_python_checks_for_both_python_kinds(self):
        self.assertIn(
            "\n    if: startsWith(needs.check-single-service.outputs.kind, 'python')\n",
            _CI,
        )
        self.assertNotIn("needs.check-single-service.outputs.kind == 'python'\n", _CI)

    def test_ci_dry_runs_pack_for_python_odcs(self):
        step = _step(_CI, _PACK_DRY_RUN)
        self.assertIn("\n        if: needs.check-single-service.outputs.kind == 'python-odcs'\n", step)
        self.assertIn(
            "        run: |\n"
            "          echo '{}' > \"${RUNNER_TEMP}/packages.json\"\n"
            '          continuo-runtime pack "services/${{ needs.check-single-service.outputs.service }}/contracts" \\\n'
            '            --service "${{ needs.check-single-service.outputs.service }}" \\\n'
            '            --repo-root "services/${{ needs.check-single-service.outputs.service }}" \\\n'
            "            --dialect postgres \\\n"
            '            --image-packages "${RUNNER_TEMP}/packages.json" \\\n'
            '            --out "${RUNNER_TEMP}/odcs-bundle.json"\n',
            step,
        )
        # It is the last step of python-checks, after the validate, and CI builds no
        # image and reaches no storage.
        validate = _position(_CI, "Validate python contracts")
        dry_run = _position(_CI, _PACK_DRY_RUN)
        self.assertLess(validate, dry_run)
        self.assertLess(dry_run, _CI.index("\n  dbt-checks:\n"))
        self.assertIn("dry run", _CI[: dry_run].rsplit("\n\n", 1)[1])
        self.assertNotIn("s3://", _CI)
        self.assertNotIn("HETZNER", _CI)

