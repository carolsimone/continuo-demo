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
        for tag in ("latest", "v0.12", "0.12.0", "v0.12.0-test1", "v0.12.0@sha256:" + "a" * 64):
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
