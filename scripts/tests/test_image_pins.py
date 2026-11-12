"""Tests for scripts/image_pins.py, which reads the pins a service image declares."""

import importlib.util
import io
import pathlib
import tempfile
import unittest

_MOD_PATH = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "image_pins.py"
_spec = importlib.util.spec_from_file_location("image_pins", _MOD_PATH)
image_pins = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(image_pins)

_RUNTIME = "ghcr.io/carolsimone/continuo-python-runtime-postgres"
_SERVICE_PY = f"# The python service image.\nFROM {_RUNTIME}:v0.12.0\nCOPY contracts/ /app/contracts/\n"
_UV_TOOL_LIST = "continuo-python-runtime v0.12.0\n- continuo-runtime\n"


def _service_dir(**files: str) -> pathlib.Path:
    """A temporary service directory; the keyword Dockerfile_local writes Dockerfile.local."""
    path = pathlib.Path(tempfile.mkdtemp())
    for name, text in files.items():
        (path / name.replace("_local", ".local")).write_text(text)
    return path


class RuntimeVersionTest(unittest.TestCase):
    def test_reads_the_version_of_the_runtime_base_image(self):
        self.assertEqual(image_pins.runtime_version(_SERVICE_PY), "0.12.0")

    def test_accepts_platform_flag_stage_name_lowercase_keyword_and_crlf(self):
        text = "from --platform=linux/amd64 ghcr.io/carolsimone/continuo-python-runtime-trino:v1.2.3 AS base\r\n"
        self.assertEqual(image_pins.runtime_version(text), "1.2.3")

    def test_refuses_a_tag_that_is_not_an_exact_release(self):
        for tag in ("latest", "v0.12", "0.12.0", "V0.12.0", "v0.12.0-test1", "v0.12.0@sha256:" + "a" * 64):
            with self.subTest(tag=tag):
                with self.assertRaisesRegex(image_pins.PinError, r"continuo-python-runtime-<engine>:v<X\.Y\.Z>"):
                    image_pins.runtime_version(f"FROM {_RUNTIME}:{tag}\n")

    def test_refuses_a_dockerfile_without_the_runtime_base_image(self):
        text = f"FROM python:3.12-slim\n# FROM {_RUNTIME}:v0.12.0\n"
        with self.assertRaisesRegex(image_pins.PinError, "no FROM line names"):
            image_pins.runtime_version(text)

    def test_refuses_two_runtime_base_images(self):
        with self.assertRaisesRegex(image_pins.PinError, "2 FROM lines"):
            image_pins.runtime_version(_SERVICE_PY + f"FROM {_RUNTIME}:v0.11.0\n")


class InstalledRuntimeVersionTest(unittest.TestCase):
    def test_reads_the_runtime_line_among_other_tools(self):
        listing = "black v24.1.0\n- black\n" + _UV_TOOL_LIST
        self.assertEqual(image_pins.installed_runtime_version(listing), "0.12.0")

    def test_is_none_when_the_runtime_is_not_installed(self):
        self.assertIsNone(image_pins.installed_runtime_version("No tools installed\n"))


class RuntimeCommandsTest(unittest.TestCase):
    def test_runtime_version_prints_only_the_version(self):
        out = io.StringIO()
        code = image_pins.main(["runtime-version", str(_service_dir(Dockerfile=_SERVICE_PY))], stdout=out)
        self.assertEqual((code, out.getvalue()), (0, "0.12.0\n"))

    def test_runtime_version_logs_the_reason_and_prints_nothing(self):
        service = _service_dir(Dockerfile=f"FROM {_RUNTIME}:latest\n")
        out = io.StringIO()
        with self.assertLogs("image_pins", "ERROR") as logs:
            code = image_pins.main(["runtime-version", str(service)], stdout=out)
        self.assertEqual((code, out.getvalue()), (1, ""))
        self.assertIn(f"{service}/Dockerfile: FROM must name", logs.output[0])

    def test_a_service_without_a_dockerfile_fails(self):
        service = _service_dir()
        with self.assertLogs("image_pins", "ERROR") as logs:
            code = image_pins.main(["runtime-version", str(service)], stdout=io.StringIO())
        self.assertEqual(code, 1)
        self.assertIn(f"{service}/Dockerfile: no such file", logs.output[0])

    def test_check_installed_passes_when_the_cli_is_the_image_version(self):
        service = _service_dir(Dockerfile=_SERVICE_PY)
        code = image_pins.main(["check-installed", str(service)], stdin=io.StringIO(_UV_TOOL_LIST))
        self.assertEqual(code, 0)

    def test_check_installed_fails_naming_both_versions(self):
        service = _service_dir(Dockerfile=_SERVICE_PY)
        with self.assertLogs("image_pins", "ERROR") as logs:
            code = image_pins.main(
                ["check-installed", str(service)], stdin=io.StringIO("continuo-python-runtime v0.11.0\n")
            )
        self.assertEqual(code, 1)
        self.assertIn("continuo-python-runtime 0.11.0 is installed but", logs.output[0])
        self.assertIn("names 0.12.0", logs.output[0])

    def test_check_installed_fails_when_the_cli_is_missing(self):
        service = _service_dir(Dockerfile=_SERVICE_PY)
        with self.assertLogs("image_pins", "ERROR") as logs:
            code = image_pins.main(["check-installed", str(service)], stdin=io.StringIO("No tools installed\n"))
        self.assertEqual(code, 1)
        self.assertIn("continuo-python-runtime is not installed", logs.output[0])


_DBT = (
    "FROM python:3.12-slim\n"
    'RUN pip install --no-cache-dir "dbt-core==1.12.0b1" "dbt-postgres==1.10.0" '
    '"dbt-adapters==1.24.5" "dbt-common==1.39.0"\n'
)
_DBT_TODAY = 'FROM python:3.12-slim\nRUN pip install --no-cache-dir "dbt-core==1.12.0b1" "dbt-postgres==1.10.0"\n'
_PINS = {"dbt-core": "1.12.0b1", "dbt-postgres": "1.10.0", "dbt-adapters": "1.24.5", "dbt-common": "1.39.0"}


class DbtPinsTest(unittest.TestCase):
    def test_reads_every_pinned_dbt_package(self):
        self.assertEqual(image_pins.dbt_pins(_DBT), _PINS)

    def test_reads_an_instruction_continued_over_several_lines(self):
        text = (
            "RUN pip install --no-cache-dir \\\r\n"
            "    dbt-core==1.12.0b1 \\\n"
            '    "dbt-postgres==1.10.0" \\\n'
            "    'dbt-adapters==1.24.5' dbt-common==1.39.0\n"
        )
        self.assertEqual(image_pins.dbt_pins(text), _PINS)

    def test_leaves_out_a_package_the_instruction_does_not_install(self):
        self.assertEqual(image_pins.dbt_pins(_DBT_TODAY), {"dbt-core": "1.12.0b1", "dbt-postgres": "1.10.0"})

    def test_refuses_a_package_not_pinned_with_double_equals(self):
        for spec in (
            "dbt-adapters>=1.24.5",
            "dbt-adapters",
            "dbt-adapters~=1.24",
            "dbt-adapters==1.24.*",
            "dbt-adapters==${ADAPTERS}",
        ):
            with self.subTest(spec=spec):
                with self.assertRaises(image_pins.PinError) as caught:
                    image_pins.dbt_pins(_DBT_TODAY.rstrip("\n") + f' "{spec}"\n')
                self.assertEqual(str(caught.exception), f"dbt-adapters must be pinned with == (got '{spec}')")

    def test_refuses_a_package_pinned_twice(self):
        text = _DBT_TODAY.rstrip("\n") + ' "dbt-postgres==1.9.0"\n'
        with self.assertRaises(image_pins.PinError) as caught:
            image_pins.dbt_pins(text)
        self.assertEqual(
            str(caught.exception), "dbt-postgres is pinned twice (got 'dbt-postgres==1.10.0' and 'dbt-postgres==1.9.0')"
        )

    def test_refuses_a_dockerfile_that_installs_no_dbt(self):
        with self.assertRaisesRegex(image_pins.PinError, "no RUN pip install instruction installs dbt-core"):
            image_pins.dbt_pins("FROM python:3.12-slim\nRUN pip install --no-cache-dir pyyaml==6.0.3\n")


class CheckDbtServiceTest(unittest.TestCase):
    def test_a_service_whose_dockerfiles_pin_the_same_versions_passes(self):
        self.assertEqual(image_pins.check_dbt_service(_service_dir(Dockerfile=_DBT, Dockerfile_local=_DBT)), [])

    def test_reports_each_missing_pin_of_each_dockerfile(self):
        service = _service_dir(Dockerfile=_DBT_TODAY, Dockerfile_local=_DBT_TODAY)
        self.assertEqual(
            image_pins.check_dbt_service(service),
            [
                f'{service}/Dockerfile: dbt-adapters is not pinned (add "dbt-adapters==<version>")',
                f'{service}/Dockerfile: dbt-common is not pinned (add "dbt-common==<version>")',
                f'{service}/Dockerfile.local: dbt-adapters is not pinned (add "dbt-adapters==<version>")',
                f'{service}/Dockerfile.local: dbt-common is not pinned (add "dbt-common==<version>")',
            ],
        )

    def test_reports_dockerfiles_that_disagree(self):
        local = _DBT.replace("dbt-adapters==1.24.5", "dbt-adapters==1.24.4")
        service = _service_dir(Dockerfile=_DBT, Dockerfile_local=local)
        self.assertEqual(
            image_pins.check_dbt_service(service),
            [f"{service}/Dockerfile.local pins dbt-adapters==1.24.4 but {service}/Dockerfile pins dbt-adapters==1.24.5"],
        )

    def test_a_service_without_a_dockerfile_fails(self):
        service = _service_dir(Dockerfile_local=_DBT)
        self.assertEqual(image_pins.check_dbt_service(service), [f"{service}/Dockerfile: no such file"])

    def test_check_dbt_logs_the_pins_and_passes(self):
        service = _service_dir(Dockerfile=_DBT)
        with self.assertLogs("image_pins", "INFO") as logs:
            self.assertEqual(image_pins.main(["check-dbt", str(service)]), 0)
        self.assertIn(
            f"{service} pins dbt-core==1.12.0b1 dbt-postgres==1.10.0 dbt-adapters==1.24.5 dbt-common==1.39.0",
            logs.output[-1],
        )

    def test_check_dbt_logs_every_problem_and_fails(self):
        service = _service_dir(Dockerfile=_DBT_TODAY)
        with self.assertLogs("image_pins", "ERROR") as logs:
            self.assertEqual(image_pins.main(["check-dbt", str(service)]), 1)
        self.assertEqual(len(logs.output), 2)
