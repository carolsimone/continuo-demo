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


_JOB_END = re.compile(r"\n(?:[^ \n]|  [^ \n])")


def _job_text(text, name):
    """The text of the job called `name`: its key line to the end of its last line.

    The jobs are the two-space-indented keys under `jobs:`; every line inside one is indented
    by four spaces or more, so the next job, the comment above it or a top-level key ends it.
    """
    marker = f"\n  {name}:\n"
    start = text.find(marker)
    if start == -1:
        raise AssertionError(f"no job named {name!r}")
    start += 1
    end = _JOB_END.search(text, start)
    return text[start : len(text) if end is None else end.start() + 1]


_ODCS_DETECT = (
    'if compgen -G "services/${SERVICE}/contracts/*.odcs.yaml" > /dev/null; then KIND="python-odcs"; '
    'else KIND="dbt"; fi'
)
_ODCS_ONLY = "needs.detect.outputs.kind == 'python-odcs' && needs.detect.outputs.skip_release != 'true'"
_ODCS_STEPS = (
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

    def test_the_python_branch_of_detect_is_gone(self):
        for name, text in (("release.yml", _RELEASE), ("ci.yml", _CI)):
            with self.subTest(workflow=name):
                # A service with contracts/ and no ODCS file is a dbt service now, not `python`.
                self.assertNotIn('KIND="python"', text)
                self.assertNotIn('elif [ -d "services/${SERVICE}/contracts" ]', text)
                self.assertNotRegex(text, r'(?m)^\s*if \[ -d "services/\$\{SERVICE\}/contracts" \]')

    def test_no_workflow_merges_contracts_or_writes_a_contract_yaml(self):
        for name, text in (("release.yml", _RELEASE), ("ci.yml", _CI)):
            with self.subTest(workflow=name):
                self.assertNotRegex(text, r"continuo-runtime\s+merge")
                self.assertNotIn("contract.yaml", text)
                self.assertNotRegex(text, r"(?mi)^\s*-\s+name:\s*merge\b")
        for step in ("Merge python contracts", "Upload contract.yaml to S3"):
            with self.subTest(step=step):
                self.assertNotIn(f"- name: {step}\n", _RELEASE)

    def test_no_condition_names_the_plain_python_kind_or_both_python_kinds(self):
        for name, text in (("release.yml", _RELEASE), ("ci.yml", _CI)):
            with self.subTest(workflow=name):
                self.assertNotIn("== 'python'", text)
                self.assertNotIn("startsWith(", text)

    def test_the_python_steps_run_only_for_python_odcs(self):
        for name in _ODCS_STEPS:
            with self.subTest(step=name):
                self.assertIn(f"\n        if: {_ODCS_ONLY}\n", _step(_RELEASE, name))
        # The count pins every step: the steps above, then the pack and the bundle upload.
        self.assertEqual(_RELEASE.count(f"\n        if: {_ODCS_ONLY}\n"), len(_ODCS_STEPS) + 2)

    def test_the_post_sends_the_full_image_ref_for_python_odcs(self):
        self.assertIn(
            "          IMAGE_TAG: ${{ needs.detect.outputs.kind == 'python-odcs' "
            "&& env.PYTHON_IMAGE_TAG || needs.detect.outputs.image_tag }}\n",
            _step(_RELEASE, _POST),
        )

    def test_the_post_sends_the_kind(self):
        self.assertIn("          KIND: ${{ needs.detect.outputs.kind }}\n", _step(_RELEASE, _POST))

    def test_the_post_and_the_odcs_steps_carry_no_status_function(self):
        # A step with no status function has an implicit success(): a failed pack stops
        # the upload and the POST, and a failed upload stops the POST.
        post = _step(_RELEASE, _POST)
        self.assertIn("\n        if: needs.detect.outputs.skip_release != 'true'\n", post)
        for name in (_PACK, _UPLOAD_BUNDLE, _POST):
            with self.subTest(step=name):
                step = _step(_RELEASE, name)
                for function in ("always()", "failure()", "cancelled()"):
                    self.assertNotIn(function, step)

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

    def test_ci_runs_the_python_checks_for_python_odcs_only(self):
        self.assertIn(
            "\n  python-checks:\n"
            "    needs: check-single-service\n"
            "    if: needs.check-single-service.outputs.kind == 'python-odcs'\n",
            _CI,
        )

    def test_ci_dry_runs_pack_for_python_odcs(self):
        step = _step(_CI, _PACK_DRY_RUN)
        # The job runs only for python-odcs, so the step has no condition of its own.
        self.assertNotIn("\n        if:", step)
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
        # It comes after the validate and before the dbt-checks job, and CI builds no
        # image and reaches no storage.
        validate = _position(_CI, "Validate python contracts")
        dry_run = _position(_CI, _PACK_DRY_RUN)
        self.assertLess(validate, dry_run)
        self.assertLess(dry_run, _CI.index("\n  dbt-checks:\n"))
        self.assertIn("dry run", _CI[: dry_run].rsplit("\n\n", 1)[1])
        self.assertNotIn("s3://", _CI)
        self.assertNotIn("HETZNER", _CI)



_LITE = "dbt-lite-check"
_REQUIREMENTS = 'requirements="$(python3 scripts/image_pins.py dbt-requirements "services/${SERVICE}")"'
_LITE_COMMANDS = (
    'uv venv --python 3.12 "$RUNNER_TEMP/dbt"',
    _REQUIREMENTS,
    'uv pip install --python "$RUNNER_TEMP/dbt/bin/python" $requirements',
    'uv tool install --python 3.14 "continuo-contracts==${CONTINUO_CONTRACTS_VERSION}"',
    'continuo-contracts dbt check "services/${SERVICE}" --dbt "$RUNNER_TEMP/dbt/bin/dbt"',
)


class DbtLiteCheckTest(unittest.TestCase):
    def test_the_job_text_ends_at_the_next_job_and_its_comment(self):
        job = _job_text(_CI, "dbt-checks")
        self.assertTrue(job.startswith("  dbt-checks:\n"))
        self.assertIn("scripts/image_pins.py check-dbt", job)
        self.assertNotIn("dbt-lite-check", job)
        self.assertNotIn("\n  scripts:\n", job)
        self.assertTrue(job.endswith("\n"))
        self.assertEqual(_job_text(_CI, "scripts"), _CI[_CI.index("\n  scripts:\n") + 1 :])

    def test_the_lite_check_runs_only_for_dbt_services(self):
        job = _job_text(_CI, _LITE)
        self.assertIn("\n    needs: check-single-service\n", job)
        self.assertIn("\n    if: needs.check-single-service.outputs.kind == 'dbt'\n", job)
        # The job's steps carry no condition of their own that could widen it.
        self.assertNotIn("\n        if:", job)

    def test_the_lite_check_runs_read_only_with_a_time_limit(self):
        job = _job_text(_CI, _LITE)
        self.assertIn("\n    runs-on: ubuntu-latest\n    timeout-minutes: 10\n", job)
        self.assertIn("\n    permissions:\n      contents: read\n", job)

    def test_the_lite_check_names_the_service_it_checks(self):
        env = _job_text(_CI, _LITE).split("\n    env:\n", 1)[1].split("\n    steps:\n", 1)[0]
        self.assertIn("      SERVICE: ${{ needs.check-single-service.outputs.service }}\n", env)

    def test_the_lite_check_installs_the_dbt_the_image_pins(self):
        job = _job_text(_CI, _LITE)
        self.assertIn(_REQUIREMENTS, job)
        # No dbt version is written in the job: the pins come from the service's Dockerfile.
        self.assertNotIn("dbt-core==", job)
        self.assertIsNone(re.search(r"dbt-(core|postgres|adapters|common)\s*(==|>=|~=|@)", job))

    def test_the_lite_check_pins_one_exact_library_version(self):
        job = _job_text(_CI, _LITE)
        versions = re.findall(r'(?m)^      CONTINUO_CONTRACTS_VERSION: "([^"]*)"$', job)
        self.assertEqual(len(versions), 1)
        self.assertRegex(versions[0], r"\A\d+\.\d+\.\d+\Z")
        # The version is written once, in env, and the install reads it from there.
        self.assertEqual(len(re.findall(r"continuo-contracts==", job)), 1)
        self.assertIn('"continuo-contracts==${CONTINUO_CONTRACTS_VERSION}"', job)

    def test_the_lite_check_says_where_the_library_version_comes_from(self):
        job = _job_text(_CI, _LITE)
        self.assertIn(
            "      # The continuo-contracts version that continuo's topology-controller/pyproject.toml pins on main.\n"
            '      CONTINUO_CONTRACTS_VERSION: "',
            job,
        )

    def test_the_lite_check_passes_the_dbt_executable(self):
        job = _job_text(_CI, _LITE)
        self.assertIn(
            'continuo-contracts dbt check "services/${SERVICE}" --dbt "$RUNNER_TEMP/dbt/bin/dbt"\n', job
        )

    def test_the_lite_check_runs_its_commands_in_order(self):
        job = _job_text(_CI, _LITE)
        positions = [job.find(command) for command in _LITE_COMMANDS]
        for command, position in zip(_LITE_COMMANDS, positions):
            with self.subTest(command=command):
                self.assertNotEqual(position, -1)
        self.assertEqual(positions, sorted(positions))

    def test_the_lite_check_sets_up_the_checkout_and_uv_the_other_jobs_use(self):
        job = _job_text(_CI, _LITE)
        self.assertIn("      - name: Checkout\n        uses: actions/checkout@v4\n", job)
        self.assertIn("      - name: Set up uv\n        uses: astral-sh/setup-uv@v5\n", job)
        self.assertLess(job.index("actions/checkout@v4"), job.index("astral-sh/setup-uv@v5"))
        self.assertLess(job.index("astral-sh/setup-uv@v5"), job.index("uv venv"))
