"""Text checks of the release and CI workflows."""

import importlib.util
import os
import pathlib
import re
import subprocess
import tempfile
import textwrap
import unittest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_WORKFLOWS = _ROOT / ".github" / "workflows"
_RELEASE = (_WORKFLOWS / "release.yml").read_text()
_CI = (_WORKFLOWS / "ci.yml").read_text()
_README = (_ROOT / "README.md").read_text(encoding="utf-8")


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
                    r'python3 scripts/image_pins\.py check-installed "projects/[^"]+" <<< "\$listed"',
                )


    def test_every_python_project_image_runs_a_runtime_that_takes_project(self):
        # `continuo-runtime validate` and `pack` take `--project` from runtime 0.15.0 on.
        spec = importlib.util.spec_from_file_location("image_pins", _ROOT / "scripts" / "image_pins.py")
        image_pins = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(image_pins)
        dockerfiles = [
            directory / "Dockerfile"
            for directory in sorted(_ROOT.glob("projects/*"))
            if any((directory / "contracts").glob("*.odcs.yaml"))
        ]
        self.assertTrue(dockerfiles, "no python project under projects/")
        for dockerfile in dockerfiles:
            with self.subTest(dockerfile=str(dockerfile.relative_to(_ROOT))):
                version = image_pins.runtime_version(dockerfile.read_text())
                self.assertGreaterEqual(tuple(int(part) for part in version.split(".")), (0, 15, 0))


class CiChecksTest(unittest.TestCase):
    def test_ci_checks_the_dbt_pins_of_the_changed_dbt_project(self):
        self.assertIn(
            'python3 scripts/image_pins.py check-dbt "projects/${{ needs.check-single-project.outputs.project }}"',
            _CI,
        )

    def test_ci_runs_every_scripts_test(self):
        # The whole folder, so a new test file runs without a change to the workflow.
        self.assertIn("        run: uvx pytest==9.1.1 scripts/tests -v\n", _CI)

    def test_ci_runs_on_every_file_the_glossary_check_reads(self):
        # The glossary check reads every tracked file, so a change to the README or to any
        # script starts CI too.
        paths = _CI.split("\njobs:\n", 1)[0]
        for path in ("'projects/**'", "'ontology/**'", "'scripts/**'", "'README.md'", "'.gitignore'",
                     "'.github/workflows/ci.yml'", "'.github/workflows/release.yml'"):
            with self.subTest(path=path):
                self.assertIn(f"\n      - {path}\n", paths)

    def test_every_file_the_glossary_check_reads_starts_ci(self):
        # A tracked file that no `paths` entry of ci.yml names never starts CI, so a pull
        # request that changes only that file could bring back a retired name unchecked.
        filters = re.findall(r"(?m)^      - '([^']+)'$", _CI.split("\njobs:\n", 1)[0])
        listed = subprocess.run(
            ["git", "ls-files", "-z"], cwd=_ROOT, check=True, capture_output=True, text=True
        ).stdout
        for path in (p for p in listed.split("\0") if p):
            # The glossary check skips seed data and the licence text.
            if path.endswith(".csv") or path == "LICENSE":
                continue
            with self.subTest(path=path):
                self.assertTrue(
                    any(path == f or (f.endswith("/**") and path.startswith(f[:-2])) for f in filters),
                    f"{path} is read by the glossary check, but no paths entry of ci.yml starts CI for it",
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
    'if compgen -G "projects/${PROJECT}/contracts/*.odcs.yaml" > /dev/null; then KIND="python"; '
    'else KIND="dbt"; fi'
)
_ODCS_ONLY = "needs.detect.outputs.kind == 'python' && needs.detect.outputs.skip_release != 'true'"
_ODCS_STEPS = (
    "Set up uv",
    "Read the runtime version from the project image",
    "Install continuo-python-runtime",
    "Check the installed runtime is the image's",
    "Lint python scripts (no hand-written SQL)",
    "Validate python contracts",
    "Compose full image ref for python release",
)
_BUILD = "Build and push the changed project image"
_COMPOSE = "Compose full image ref for python release"
_PACK = "Pack the ODCS bundle"
_UPLOAD_BUNDLE = "Upload odcs-bundle.json to S3"
_POST = "Drive the release through continuo"
_PACK_DRY_RUN = "Dry-run the ODCS bundle pack"


class PythonKindTest(unittest.TestCase):
    def test_detect_sets_python_when_odcs_files_exist(self):
        # release.yml detects the kind for a dispatch and for a push; ci.yml for a PR.
        self.assertEqual(_RELEASE.count(_ODCS_DETECT), 2)
        self.assertEqual(_CI.count(_ODCS_DETECT), 1)

    def test_only_odcs_files_make_a_python_project(self):
        for name, text in (("release.yml", _RELEASE), ("ci.yml", _CI)):
            with self.subTest(workflow=name):
                # A project with contracts/ and no ODCS file is a dbt project.
                self.assertEqual(text.count('KIND="python"'), text.count(_ODCS_DETECT))
                self.assertNotIn('elif [ -d "projects/${PROJECT}/contracts" ]', text)
                self.assertNotRegex(text, r'(?m)^\s*if \[ -d "projects/\$\{PROJECT\}/contracts" \]')

    def test_no_workflow_names_the_retired_python_kind(self):
        for name, text in (("release.yml", _RELEASE), ("ci.yml", _CI)):
            with self.subTest(workflow=name):
                self.assertNotIn("python" + "-odcs", text)

    def test_no_workflow_merges_contracts_or_writes_a_contract_yaml(self):
        for name, text in (("release.yml", _RELEASE), ("ci.yml", _CI)):
            with self.subTest(workflow=name):
                self.assertNotRegex(text, r"continuo-runtime\s+merge")
                self.assertNotIn("contract.yaml", text)
                self.assertNotRegex(text, r"(?mi)^\s*-\s+name:\s*merge\b")
        for step in ("Merge python contracts", "Upload contract.yaml to S3"):
            with self.subTest(step=step):
                self.assertNotIn(f"- name: {step}\n", _RELEASE)

    def test_every_kind_condition_names_the_kind_python_exactly(self):
        for name, text in (("release.yml", _RELEASE), ("ci.yml", _CI)):
            with self.subTest(workflow=name):
                self.assertEqual(re.findall(r"kind == '([^']*)'", text).count("python"),
                                 len(re.findall(r"kind == '[^']*python", text)))
                self.assertNotIn("startsWith(", text)

    def test_the_python_steps_run_only_for_python(self):
        for name in _ODCS_STEPS:
            with self.subTest(step=name):
                self.assertIn(f"\n        if: {_ODCS_ONLY}\n", _step(_RELEASE, name))
        # The count pins every step: the steps above, then the pack and the bundle upload.
        self.assertEqual(_RELEASE.count(f"\n        if: {_ODCS_ONLY}\n"), len(_ODCS_STEPS) + 2)

    def test_the_post_sends_the_full_image_ref_for_python(self):
        self.assertIn(
            "          IMAGE_TAG: ${{ needs.detect.outputs.kind == 'python' "
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
            '          continuo-runtime pack "projects/${{ needs.detect.outputs.project }}/contracts" \\\n'
            '            --project "${{ needs.detect.outputs.project }}" \\\n'
            '            --repo-root "projects/${{ needs.detect.outputs.project }}" \\\n'
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
            '            "s3://continuo-dev/${{ needs.detect.outputs.project }}/'
            '${{ needs.detect.outputs.release_id }}/odcs-bundle.json" \\\n'
            "            --endpoint-url https://nbg1.your-objectstorage.com \\\n"
            "            --region eu-central-1\n",
            step,
        )
        # The upload completes before the POST, which does no existence check.
        comment = _RELEASE[: _position(_RELEASE, _UPLOAD_BUNDLE)].rsplit("\n\n", 1)[1]
        self.assertIn("upload to complete before the POST", re.sub(r"\n\s*# ?", " ", comment))

    def test_ci_runs_the_python_checks_for_python_only(self):
        self.assertIn(
            "\n  python-checks:\n"
            "    needs: check-single-project\n"
            "    if: needs.check-single-project.outputs.kind == 'python'\n",
            _CI,
        )

    def test_ci_dry_runs_pack_for_python(self):
        step = _step(_CI, _PACK_DRY_RUN)
        # The job runs only for python, so the step has no condition of its own.
        self.assertNotIn("\n        if:", step)
        self.assertIn(
            "        run: |\n"
            "          echo '{}' > \"${RUNNER_TEMP}/packages.json\"\n"
            '          continuo-runtime pack "projects/${{ needs.check-single-project.outputs.project }}/contracts" \\\n'
            '            --project "${{ needs.check-single-project.outputs.project }}" \\\n'
            '            --repo-root "projects/${{ needs.check-single-project.outputs.project }}" \\\n'
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
_REQUIREMENTS = 'requirements="$(python3 scripts/image_pins.py dbt-requirements "projects/${PROJECT}")"'
_LITE_COMMANDS = (
    'uv venv --python 3.12 "$RUNNER_TEMP/dbt"',
    _REQUIREMENTS,
    'uv pip install --python "$RUNNER_TEMP/dbt/bin/python" $requirements',
    'uv tool install --python 3.14 "continuo-contracts==${CONTINUO_CONTRACTS_VERSION}"',
    'continuo-contracts dbt check "projects/${PROJECT}" --dbt "$RUNNER_TEMP/dbt/bin/dbt" --ontology ontology/ontology.yaml',
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

    def test_the_lite_check_runs_only_for_dbt_projects(self):
        job = _job_text(_CI, _LITE)
        self.assertIn("\n    needs: check-single-project\n", job)
        self.assertIn("\n    if: needs.check-single-project.outputs.kind == 'dbt'\n", job)
        # The job's steps carry no condition of their own that could widen it.
        self.assertNotIn("\n        if:", job)

    def test_the_lite_check_runs_read_only_with_a_time_limit(self):
        job = _job_text(_CI, _LITE)
        self.assertIn("\n    runs-on: ubuntu-latest\n    timeout-minutes: 10\n", job)
        self.assertIn("\n    permissions:\n      contents: read\n", job)

    def test_the_lite_check_names_the_project_it_checks(self):
        env = _job_text(_CI, _LITE).split("\n    env:\n", 1)[1].split("\n    steps:\n", 1)[0]
        # The job's env holds that and nothing else: the library version is the workflow's.
        self.assertEqual(env, "      PROJECT: ${{ needs.check-single-project.outputs.project }}")

    def test_the_lite_check_installs_the_dbt_the_image_pins(self):
        job = _job_text(_CI, _LITE)
        self.assertIn(_REQUIREMENTS, job)
        # No dbt version is written in the job: the pins come from the project's Dockerfile.
        self.assertNotIn("dbt-core==", job)
        self.assertIsNone(re.search(r"dbt-(core|postgres|adapters|common)\s*(==|>=|~=|@)", job))

    def test_the_lite_check_passes_the_dbt_executable_and_the_ontology_of_the_checkout(self):
        job = _job_text(_CI, _LITE)
        self.assertIn(
            'continuo-contracts dbt check "projects/${PROJECT}" --dbt "$RUNNER_TEMP/dbt/bin/dbt" '
            "--ontology ontology/ontology.yaml\n",
            job,
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



_CONTRACTS_VERSION = re.compile(r'(?m)^  CONTINUO_CONTRACTS_VERSION: "([^"]*)"$')
_INSTALL_CONTRACTS = 'uv tool install --python 3.14 "continuo-contracts==${CONTINUO_CONTRACTS_VERSION}"'
_ONTOLOGY_CHECK = "ontology-check"
_ONTOLOGY_PROJECTS = "ontology-projects-check"


def _workflow_env(text):
    """The workflow's own `env:` block: the top-level key between `on:` and `jobs:`."""
    match = re.search(r"(?m)^env:\n((?:(?:  .*)?\n)+)", text)
    if match is None:
        raise AssertionError("the workflow has no top-level env")
    return match.group(1)


class ContractsVersionTest(unittest.TestCase):
    def test_ci_sets_one_exact_library_version_in_the_workflow_env(self):
        versions = _CONTRACTS_VERSION.findall(_workflow_env(_CI))
        self.assertEqual(len(versions), 1)
        self.assertRegex(versions[0], r"\A\d+\.\d+\.\d+\Z")
        # It is written once in the whole file, so no job can pin a different one.
        self.assertEqual(len(re.findall(r"CONTINUO_CONTRACTS_VERSION:", _CI)), 1)

    def test_the_library_reads_the_ontology_s_projects(self):
        # continuo-contracts reads `principals.projects`, the key ontology/ontology.yaml writes,
        # from 0.5.0 on.
        (version,) = _CONTRACTS_VERSION.findall(_workflow_env(_CI))
        self.assertGreaterEqual(tuple(int(part) for part in version.split(".")), (0, 5, 0))
        ontology = (_ROOT / "ontology" / "ontology.yaml").read_text(encoding="utf-8")
        self.assertRegex(ontology, r"(?m)^principals:\n(?:  .*\n|\n|#.*\n)*?  projects:\n")

    def test_the_env_says_where_the_library_version_comes_from(self):
        self.assertIn(
            "  # The continuo-contracts version that continuo's topology-controller/pyproject.toml pins on main.\n"
            '  CONTINUO_CONTRACTS_VERSION: "',
            _workflow_env(_CI),
        )

    def test_both_jobs_that_need_the_library_install_it_from_the_env(self):
        # The three installs are the only `continuo-contracts==` in the workflow.
        self.assertEqual(len(re.findall(r"continuo-contracts==", _CI)), 3)
        for job in (_LITE, _ONTOLOGY_CHECK, _ONTOLOGY_PROJECTS):
            with self.subTest(job=job):
                self.assertIn(f"        run: {_INSTALL_CONTRACTS}\n", _job_text(_CI, job))

    def test_the_readme_installs_the_library_version_the_workflow_sets(self):
        (ci_version,) = _CONTRACTS_VERSION.findall(_workflow_env(_CI))
        readme_versions = re.findall(r"continuo-contracts==([^\s\"'`]+)", _README)
        self.assertTrue(
            readme_versions,
            "README.md has no continuo-contracts==X.Y.Z literal to compare with "
            f"CONTINUO_CONTRACTS_VERSION {ci_version!r} in the env of .github/workflows/ci.yml",
        )
        for readme_version in readme_versions:
            with self.subTest(readme_version=readme_version):
                self.assertEqual(
                    readme_version,
                    ci_version,
                    f"README.md installs continuo-contracts=={readme_version}, but the env of "
                    f".github/workflows/ci.yml sets CONTINUO_CONTRACTS_VERSION to {ci_version!r}",
                )


class OntologyCheckTest(unittest.TestCase):
    def test_the_ontology_check_runs_on_every_pull_request(self):
        job = _job_text(_CI, _ONTOLOGY_CHECK)
        # No `needs` and no condition: a project's pull request is checked against the file it carries.
        self.assertNotIn("\n    needs:", job)
        self.assertNotIn("\n    if:", job)
        self.assertNotIn("\n        if:", job)
        self.assertIn("\n    runs-on: ubuntu-latest\n    timeout-minutes: 5\n", job)
        self.assertIn("\n    permissions:\n      contents: read\n", job)

    def test_the_ontology_check_installs_the_library_then_checks_the_file(self):
        job = _job_text(_CI, _ONTOLOGY_CHECK)
        commands = (
            "      - name: Checkout\n        uses: actions/checkout@v4\n",
            "      - name: Set up uv\n        uses: astral-sh/setup-uv@v5\n",
            f"        run: {_INSTALL_CONTRACTS}\n",
            "        run: continuo-contracts ontology check ontology/ontology.yaml\n",
        )
        positions = [job.find(command) for command in commands]
        for command, position in zip(commands, positions):
            with self.subTest(command=command):
                self.assertNotEqual(position, -1)
        self.assertEqual(positions, sorted(positions))

    def test_the_scripts_job_is_the_last_job_and_the_ontology_check_comes_before_it(self):
        jobs = re.findall(r"(?m)^  ([a-z][a-z-]*):$", _CI.split("\njobs:\n", 1)[1])
        self.assertEqual(jobs[-1], "scripts")
        self.assertEqual(jobs.count(_ONTOLOGY_CHECK), 1)
        self.assertLess(jobs.index(_ONTOLOGY_CHECK), jobs.index("scripts"))

    def test_python_checks_validate_the_contracts_against_the_ontology(self):
        step = _step(_CI, "Validate python contracts")
        self.assertIn(
            '        run: continuo-runtime validate "projects/${{ needs.check-single-project.outputs.project }}/contracts" '
            '--dialect postgres --project "${{ needs.check-single-project.outputs.project }}" '
            "--ontology ontology/ontology.yaml\n",
            step,
        )

    def test_the_release_validates_the_contracts_as_the_pull_request_does(self):
        # The release checks the project property and the ontology bindings before it builds the
        # image, so a dispatched release, which no pull request checked, meets the same check.
        step = _step(_RELEASE, "Validate python contracts")
        self.assertIn(
            '        run: continuo-runtime validate "projects/${{ needs.detect.outputs.project }}/contracts" '
            '--dialect postgres --project "${{ needs.detect.outputs.project }}" '
            "--ontology ontology/ontology.yaml\n",
            step,
        )

    def test_a_change_to_the_ontology_triggers_ci_and_the_release(self):
        for name, text in (("ci.yml", _CI), ("release.yml", _RELEASE)):
            with self.subTest(workflow=name):
                self.assertIn("\n      - 'ontology/**'\n", text.split("\njobs:\n", 1)[0])


_DETECT = "detect"
_RELEASE_JOB = "release"
_ONTOLOGY_JOB = "release-ontology"


def _detect_script(event_name, before):
    """The shell of the detect step, with the GitHub expressions it holds replaced by their values.

    The dispatch inputs reach the shell only through the step's env (see _detect_env).
    """
    job = _job_text(_RELEASE, _DETECT)
    body = job.split("        id: ids\n", 1)[1].split("        run: |\n", 1)[1]
    values = {"github.event_name": event_name, "github.event.before": before}
    return re.sub(r"\$\{\{(.*?)\}\}", lambda match: values[match.group(1).strip()], textwrap.dedent(body))


def _detect_env(project):
    """The env the detect step sets, with the dispatch inputs it reads given their values."""
    job = _job_text(_RELEASE, _DETECT)
    block = job.split("        id: ids\n", 1)[1].split("        run: |\n", 1)[0]
    env = dict(re.findall(r"(?m)^          ([A-Z_]+): (.+)$", block))
    values = {
        "${{ inputs.project }}": project,
        "${{ inputs.force_bootstrap == true }}": "false",
        "${{ inputs.rebaseline == true }}": "false",
    }
    return {name: values[expression] for name, expression in env.items()}


def _commit_range(tmp, changed):
    """Make a git repository in `tmp` whose last commit changes `changed`.

    Returns (repo, git environment, the commit before the change, a function that runs git there).
    """
    repo = pathlib.Path(tmp) / "repo"
    repo.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "HOME": tmp,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }

    def git(*args):
        done = subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True)
        return done.stdout.strip()

    def write(path, text):
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)

    git("init", "-q", "-b", "main")
    for path in ("projects/a/m.sql", "projects/b/m.sql", "ontology/ontology.yaml", "ontology/README.md"):
        write(path, "v1\n")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    before = git("rev-parse", "HEAD")
    for path in changed:
        write(path, "v2\n")
    git("add", "-A")
    git("commit", "-q", "-m", "change", "--allow-empty")
    return repo, env, before, git


def _run_step(tmp, repo, env, script, extra_env):
    """Run a workflow step's shell in `repo`; return (exit status, its outputs, its output text)."""
    output = pathlib.Path(tmp) / "github_output"
    output.write_text("")
    done = subprocess.run(
        ["bash", "-e", "-c", script],
        cwd=repo,
        env={**env, "GITHUB_OUTPUT": str(output), **extra_env},
        capture_output=True,
        text=True,
    )
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines() if "=" in line)
    return done.returncode, outputs, done.stdout + done.stderr


def _run_detect(changed, event_name="push", project=""):
    """Run the detect step in a git repository whose last commit changes `changed`.

    Returns (exit status, the step's outputs, its output text, the short sha of the last commit).
    """
    with tempfile.TemporaryDirectory() as tmp:
        repo, env, before, git = _commit_range(tmp, changed)
        script = _detect_script(event_name, before)
        status, outputs, text = _run_step(tmp, repo, env, script, {"GITHUB_RUN_NUMBER": "12", **_detect_env(project)})
        return status, outputs, text, git("rev-parse", "--short", "HEAD")


def _condition(job):
    match = re.search(r"(?m)^    if: (.+)$", _job_text(_RELEASE, job))
    return None if match is None else match.group(1)


def _needs(job):
    match = re.search(r"(?m)^    needs: \[?([a-z, -]+?)\]?$", _job_text(_RELEASE, job))
    return [] if match is None else [name.strip() for name in match.group(1).split(",")]


def _holds(condition, outputs, results, cancelled=False):
    """Evaluate the part of the GitHub expression language the release jobs' conditions use.

    `always()` is true even in a cancelled run, `!cancelled()` is not.
    """
    python = condition.replace("always()", "True").replace("!cancelled()", repr(not cancelled))
    python = re.sub(r"needs\.detect\.outputs\.(\w+)", lambda match: repr(outputs.get(match.group(1), "")), python)
    python = re.sub(r"needs\.(\w+)\.result", lambda match: repr(results[match.group(1)]), python)
    python = python.replace("&&", " and ").replace("||", " or ")
    leftover = re.sub(r"'[^']*'|True|False|\band\b|\bor\b|==|!=|[()\s]", "", python)
    if leftover:
        raise AssertionError(f"the condition {condition!r} uses {leftover!r}, which this test cannot evaluate")
    return eval(python, {"__builtins__": {}}, {})


def _jobs_that_run(outputs, detect_result="success", release_outcome="success", cancelled=False):
    """The jobs of release.yml that run after a detect step that ended `detect_result`.

    A job whose condition has no status function runs only when every job it needs succeeded.
    `cancelled` is a run that was cancelled after the detect step ended: a job whose condition
    is true whatever happened (`always()`) still runs.
    """
    results = {_DETECT: detect_result}
    ran = set() if detect_result != "success" else {_DETECT}
    for job in (_RELEASE_JOB, _ONTOLOGY_JOB):
        condition = _condition(job)
        needed = [results[name] for name in _needs(job)]
        runs = _holds(condition, outputs, results, cancelled)
        if "always()" not in condition and "!cancelled()" not in condition:
            runs = runs and all(result == "success" for result in needed)
        if runs:
            ran.add(job)
            results[job] = release_outcome if job == _RELEASE_JOB else "success"
        else:
            results[job] = "skipped"
    return ran - {_DETECT}


_ONTOLOGY_UPLOAD = "Upload ontology.yaml to S3"
_ONTOLOGY_POST = "Drive the ontology release through continuo"


class OntologyReleaseTest(unittest.TestCase):
    def test_the_ontology_job_runs_after_the_project_job_and_only_on_its_success(self):
        self.assertEqual(_needs(_ONTOLOGY_JOB), [_DETECT, _RELEASE_JOB])
        status, outputs, stderr, _ = _run_detect(["projects/a/m.sql", "ontology/ontology.yaml"])
        self.assertEqual(status, 0, stderr)
        self.assertEqual((outputs["skip"], outputs["project"], outputs["ontology_changed"]), ("false", "a", "true"))
        self.assertEqual(_jobs_that_run(outputs), {_RELEASE_JOB, _ONTOLOGY_JOB})
        for outcome in ("failure", "cancelled"):
            with self.subTest(project_release=outcome):
                self.assertEqual(_jobs_that_run(outputs, release_outcome=outcome), {_RELEASE_JOB})

    def test_an_ontology_only_push_releases_only_the_ontology(self):
        status, outputs, stderr, sha = _run_detect(["ontology/ontology.yaml"])
        self.assertEqual(status, 0, stderr)
        self.assertEqual((outputs["skip"], outputs["ontology_changed"]), ("true", "true"))
        self.assertEqual(outputs["tag"], sha)
        self.assertEqual(outputs["ontology_release_id"], f"rel-{sha}-12-ontology")
        self.assertEqual(_jobs_that_run(outputs), {_ONTOLOGY_JOB})

    def test_two_projects_and_the_ontology_are_still_refused(self):
        status, outputs, stderr, _ = _run_detect(["projects/a/m.sql", "projects/b/m.sql", "ontology/ontology.yaml"])
        self.assertEqual(status, 1)
        self.assertIn("exactly one changed project per release; found 2", stderr)
        # Whatever the step wrote before it failed, no job runs: the ontology job
        # carries always(), so it must not take a refused push for a skipped project job.
        self.assertEqual(_jobs_that_run(outputs, detect_result="failure"), set())
        # Even outputs that say the ontology changed, from a detect step that failed after writing them.
        written = {"skip": "true", "ontology_changed": "true"}
        self.assertEqual(_jobs_that_run(written, detect_result="failure"), set())

    def test_a_project_only_push_releases_only_the_project(self):
        status, outputs, stderr, _ = _run_detect(["projects/b/m.sql"])
        self.assertEqual(status, 0, stderr)
        self.assertEqual(outputs["ontology_changed"], "false")
        self.assertEqual(_jobs_that_run(outputs), {_RELEASE_JOB})

    def test_a_push_that_changes_no_ontology_file_and_no_project_releases_nothing(self):
        # ontology/** starts the workflow; only ontology/ontology.yaml is the ontology.
        status, outputs, stderr, _ = _run_detect(["ontology/README.md"])
        self.assertEqual(status, 0, stderr)
        self.assertEqual((outputs["skip"], outputs["ontology_changed"]), ("true", "false"))
        self.assertEqual(_jobs_that_run(outputs), set())

    def test_a_dispatch_for_a_project_releases_that_project_and_not_the_ontology(self):
        status, outputs, stderr, _ = _run_detect([], event_name="workflow_dispatch", project="a")
        self.assertEqual(status, 0, stderr)
        self.assertEqual((outputs["project"], outputs["ontology_changed"]), ("a", "false"))
        self.assertEqual(_jobs_that_run(outputs), {_RELEASE_JOB})

    def test_a_dispatch_releases_the_project_it_names_whatever_its_commit_changes(self):
        # A push that changes more than one project is refused; a dispatch on that commit still
        # releases the one project it names (each project of a change that moves them all is
        # released this way, one dispatch at a time).
        changed = ["projects/a/m.sql", "projects/b/m.sql"]
        status, outputs, stderr, sha = _run_detect(changed, event_name="workflow_dispatch", project="b")
        self.assertEqual(status, 0, stderr)
        self.assertEqual((outputs["skip"], outputs["project"], outputs["kind"]), ("false", "b", "dbt"))
        self.assertEqual(outputs["release_id"], f"rel-{sha}-12")
        self.assertEqual(_jobs_that_run(outputs), {_RELEASE_JOB})
        status, _, stderr, _ = _run_detect(changed)
        self.assertEqual(status, 1)
        self.assertIn("exactly one changed project per release; found 2", stderr)

    def test_a_dispatch_input_is_never_run_as_shell(self):
        # The input reaches the script as an env value, never as text pasted into it.
        for project in ('a"; echo INJECTED; "', "$(echo INJECTED)", "a`echo INJECTED`"):
            with self.subTest(project=project):
                status, outputs, text, _ = _run_detect([], event_name="workflow_dispatch", project=project)
                self.assertEqual(status, 1)
                self.assertNotIn("INJECTED\n", text.replace("echo INJECTED", ""))
                self.assertNotIn("project", outputs)

    def test_a_dispatch_refuses_a_name_that_is_not_one_projects_folder(self):
        for project in ("", "../ontology", "a/b", ".hidden", "core "):
            with self.subTest(project=project):
                status, outputs, text, _ = _run_detect([], event_name="workflow_dispatch", project=project)
                self.assertEqual(status, 1)
                self.assertIn("is not a project name", text)
                self.assertNotIn("project", outputs)

    def test_no_run_script_pastes_a_dispatch_input(self):
        for name, text in (("release.yml", _RELEASE), ("ci.yml", _CI)):
            with self.subTest(workflow=name):
                for script in re.findall(r"(?ms)^        run: \|\n(.*?)(?=^      - |^  \S|\Z)", text):
                    self.assertNotIn("${{ inputs.", script)

    def test_a_dispatch_for_the_ontology_releases_only_the_ontology(self):
        status, outputs, stderr, sha = _run_detect([], event_name="workflow_dispatch", project="ontology")
        self.assertEqual(status, 0, stderr)
        self.assertEqual((outputs["skip"], outputs["ontology_changed"]), ("true", "true"))
        self.assertEqual(outputs["tag"], sha)
        self.assertEqual(outputs["ontology_release_id"], f"rel-{sha}-12-ontology")
        self.assertEqual(_jobs_that_run(outputs), {_ONTOLOGY_JOB})

    def test_a_dispatch_for_a_name_that_is_no_project_and_not_the_ontology_is_refused(self):
        status, outputs, text, _ = _run_detect([], event_name="workflow_dispatch", project="nope")
        self.assertEqual(status, 1)
        self.assertIn("unknown project 'nope'", text)
        self.assertNotIn("ontology_changed", outputs)

    def test_the_dispatch_input_says_the_ontology_can_be_released(self):
        description = re.search(r'\n      project:\n        description: "([^"]*)"', _RELEASE).group(1)
        self.assertIn("ontology", description)

    def test_a_cancelled_run_does_not_start_the_ontology_job(self):
        status, outputs, stderr, _ = _run_detect(["ontology/ontology.yaml"])
        self.assertEqual(status, 0, stderr)
        self.assertEqual(_jobs_that_run(outputs), {_ONTOLOGY_JOB})
        self.assertEqual(_jobs_that_run(outputs, cancelled=True), set())

    def test_the_ontology_job_condition_has_no_always(self):
        condition = _condition(_ONTOLOGY_JOB)
        self.assertNotIn("always()", condition)
        self.assertIn("!cancelled()", condition)

    def test_the_project_job_condition_is_unchanged(self):
        self.assertEqual(_condition(_RELEASE_JOB), "needs.detect.outputs.skip != 'true'")

    def test_the_ontology_job_runs_read_only_with_the_oidc_token(self):
        job = _job_text(_RELEASE, _ONTOLOGY_JOB)
        self.assertIn("\n    runs-on: ubuntu-latest\n", job)
        self.assertIn("\n    timeout-minutes: 20\n", job)
        self.assertRegex(job, r"\n    permissions:\n      contents: read\n(?:      #.*\n)?      id-token: write\n")

    def test_the_ontology_file_is_uploaded_under_the_release_before_the_post(self):
        job = _job_text(_RELEASE, _ONTOLOGY_JOB)
        self.assertIn(
            "        env:\n"
            "          AWS_ACCESS_KEY_ID: ${{ secrets.HETZNER_S3_ACCESS_KEY_ID }}\n"
            "          AWS_SECRET_ACCESS_KEY: ${{ secrets.HETZNER_S3_SECRET_ACCESS_KEY }}\n"
            "        run: |\n"
            '          aws s3 cp ontology/ontology.yaml \\\n'
            '            "s3://continuo-dev/ontology/${{ needs.detect.outputs.ontology_release_id }}/ontology.yaml" \\\n'
            "            --endpoint-url https://nbg1.your-objectstorage.com \\\n"
            "            --region eu-central-1\n",
            _step(job, _ONTOLOGY_UPLOAD),
        )
        self.assertLess(job.index(f"- name: {_ONTOLOGY_UPLOAD}\n"), job.index(f"- name: {_ONTOLOGY_POST}\n"))
        self.assertLess(job.index("actions/checkout@v4"), job.index(f"- name: {_ONTOLOGY_UPLOAD}\n"))

    def test_the_ontology_post_names_the_project_the_kind_and_the_release(self):
        job = _job_text(_RELEASE, _ONTOLOGY_JOB)
        step = _step(job, _ONTOLOGY_POST)
        self.assertIn(
            "        env:\n"
            "          CONTINUO_URL: ${{ vars.CONTINUO_URL }}\n"
            "          RELEASE_ID: ${{ needs.detect.outputs.ontology_release_id }}\n"
            "          PROJECT: ontology\n"
            "          IMAGE_TAG: ${{ needs.detect.outputs.tag }}\n"
            "          KIND: ontology\n"
            "          REPO: ${{ github.repository }}\n"
            "          COMMIT_SHA: ${{ github.sha }}\n"
            "        run: bash scripts/release.sh\n",
            step,
        )
        # A step with no status function has an implicit success(): a failed upload stops the POST.
        for function in ("always()", "failure()", "cancelled()", "\n        if:"):
            self.assertNotIn(function, job.split("\n    steps:\n", 1)[1])

    def test_the_ontology_job_fails_early_when_continuo_is_not_configured(self):
        job = _job_text(_RELEASE, _ONTOLOGY_JOB)
        self.assertIn(
            "        env:\n"
            "          CONTINUO_URL: ${{ vars.CONTINUO_URL }}\n"
            "        run: |\n"
            '          if [ -z "${CONTINUO_URL}" ]; then\n',
            job,
        )
        self.assertLess(job.index("CONTINUO_URL }}"), job.index("actions/checkout@v4"))


def _single_project_script(base, head):
    """The shell of check-single-project's check step, with the pull request's two shas filled in."""
    body = _job_text(_CI, "check-single-project").split("        id: check\n        run: |\n", 1)[1]
    values = {"github.event.pull_request.base.sha": base, "github.event.pull_request.head.sha": head}
    return re.sub(r"\$\{\{(.*?)\}\}", lambda match: values[match.group(1).strip()], textwrap.dedent(body))


def _run_single_project(changed):
    with tempfile.TemporaryDirectory() as tmp:
        repo, env, before, git = _commit_range(tmp, changed)
        script = _single_project_script(before, git("rev-parse", "HEAD"))
        return _run_step(tmp, repo, env, script, {})


class OntologyChangeChecksEveryProjectTest(unittest.TestCase):
    def test_a_change_to_the_ontology_file_is_reported_whatever_else_changes(self):
        cases = (
            (["ontology/ontology.yaml"], "true"),
            (["ontology/ontology.yaml", "projects/a/m.sql"], "true"),
            (["projects/a/m.sql"], "false"),
            (["ontology/README.md"], "false"),
        )
        for changed, expected in cases:
            with self.subTest(changed=changed):
                status, outputs, text = _run_single_project(changed)
                self.assertEqual(status, 0, text)
                self.assertEqual(outputs["ontology_changed"], expected)

    def test_the_one_project_rule_is_unchanged_for_a_change_that_names_the_ontology(self):
        status, outputs, text = _run_single_project(["projects/a/m.sql", "ontology/ontology.yaml"])
        self.assertEqual((status, outputs["project"], outputs["kind"]), (0, "a", "dbt"))
        status, outputs, text = _run_single_project(["projects/a/m.sql", "projects/b/m.sql", "ontology/ontology.yaml"])
        self.assertEqual(status, 1)
        self.assertIn("this PR touches 2", text)

    def test_check_single_project_exposes_the_output(self):
        self.assertIn(
            "      ontology_changed: ${{ steps.check.outputs.ontology_changed }}\n",
            _job_text(_CI, "check-single-project"),
        )

    def test_the_estate_job_runs_only_when_the_ontology_file_changed(self):
        job = _job_text(_CI, _ONTOLOGY_PROJECTS)
        self.assertIn("\n    needs: check-single-project\n", job)
        self.assertIn("\n    if: needs.check-single-project.outputs.ontology_changed == 'true'\n", job)
        self.assertNotIn("\n        if:", job)
        self.assertIn("\n    permissions:\n      contents: read\n", job)
        self.assertIn("\n    timeout-minutes: 20\n", job)

    def test_the_estate_job_checks_every_dbt_project_against_the_ontology_of_the_checkout(self):
        step = _step(_CI, "Check every dbt project against the ontology")
        for command in (
            "for dir in projects/*/; do",
            'if compgen -G "${dir}contracts/*.odcs.yaml" > /dev/null; then continue; fi',
            'requirements="$(python3 scripts/image_pins.py dbt-requirements "projects/${project}")"',
            'uv pip install --python "$RUNNER_TEMP/dbt-${project}/bin/python" $requirements',
            'continuo-contracts dbt check "projects/${project}" --dbt "$RUNNER_TEMP/dbt-${project}/bin/dbt" '
            "--ontology ontology/ontology.yaml",
        ):
            with self.subTest(command=command):
                self.assertIn(command, step)
        # One failing project does not hide the others, and the step still fails.
        self.assertIn("|| status=1", step)
        self.assertTrue(step.rstrip().endswith("exit \"$status\""))

    def test_the_estate_job_checks_every_python_project_against_the_ontology_of_the_checkout(self):
        step = _step(_CI, "Check every Python project against the ontology")
        for command in (
            "for dir in projects/*/; do",
            'if ! compgen -G "${dir}contracts/*.odcs.yaml" > /dev/null; then continue; fi',
            'version="$(python3 scripts/image_pins.py runtime-version "projects/${project}")"',
            'uv tool install --force "continuo-python-runtime==${version}"',
            'continuo-runtime validate "projects/${project}/contracts" --dialect postgres --project "${project}" '
            "--ontology ontology/ontology.yaml",
        ):
            with self.subTest(command=command):
                self.assertIn(command, step)
        self.assertIn("|| status=1", step)
        self.assertTrue(step.rstrip().endswith("exit \"$status\""))

    def test_the_estate_job_installs_the_library_and_comes_before_the_scripts_job(self):
        job = _job_text(_CI, _ONTOLOGY_PROJECTS)
        self.assertLess(job.index("actions/checkout@v4"), job.index("astral-sh/setup-uv@v5"))
        self.assertLess(job.index("astral-sh/setup-uv@v5"), job.index(_INSTALL_CONTRACTS))
        self.assertLess(job.index(_INSTALL_CONTRACTS), job.index("Check every dbt project"))
        jobs = re.findall(r"(?m)^  ([a-z][a-z-]*):$", _CI.split("\njobs:\n", 1)[1])
        self.assertEqual(jobs[-1], "scripts")
        self.assertLess(jobs.index(_ONTOLOGY_PROJECTS), jobs.index("scripts"))
