"""The repository says what continuo's glossary says.

continuo's glossary (GLOSSARY.md in carolsimone/continuo) names the unit a team releases a
project, the release continuo validates before promoting it a candidate release, the release
production serves the live release, and a Python project's kind `python`. A team copies this
repository's CI as it is, so a retired name here would travel into every copy. The test reads
every tracked file, and the path of every tracked file, and fails on any retired name it finds.
"""

import pathlib
import re
import subprocess
import unittest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_THIS = pathlib.Path(__file__).resolve().relative_to(_ROOT).as_posix()

# A name counts as a word when no letter or digit touches it, so `services/`, `SERVICE_NAME`,
# `--service` and `service-1` are found while `serviceable` is not.
_EDGE_BEFORE = r"(?<![A-Za-z0-9])"
_EDGE_AFTER = r"(?![A-Za-z0-9])"

# Each retired name, matched whatever its case, and the glossary word that replaces it.
_RETIRED = (
    (r"services?|svc", "project"),
    (r"python-odcs", "the kind python"),
    (r"current[-_ ]?prod", "live release or production pointer"),
    (r"blue/green", "candidate release"),
    (r"release pipeline|verification run|pipeline run", "release check"),
)

# Text where a retired word means something else, kept as it is.
_ALLOWED = (
    "port-forward svc/ui",  # a Kubernetes Service
    "card-service",  # a system outside continuo that writes the card stream
    "purpose: service_operation",  # a data-processing purpose of the ontology
    "continuo_svc",  # the Postgres login continuo's own install creates
)


def _tracked_files():
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=_ROOT, check=True, capture_output=True, text=True
    ).stdout
    return [path for path in listed.split("\0") if path]


def _findings(path, text):
    for allowed in _ALLOWED:
        text = text.replace(allowed, "")
    found = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for pattern, use in _RETIRED:
            for match in re.finditer(_EDGE_BEFORE + f"(?:{pattern})" + _EDGE_AFTER, line, re.IGNORECASE):
                found.append(f'{path}:{line_number}: "{match.group(0)}" is a retired name; use "{use}"')
    return found


class GlossaryWordsTest(unittest.TestCase):
    def test_no_tracked_file_holds_a_retired_name(self):
        found = []
        for path in _tracked_files():
            # Seed data, the licence text and this file's own list are not the repository's words.
            if path.endswith(".csv") or path in ("LICENSE", _THIS):
                continue
            full = _ROOT / path
            if not full.is_file():
                continue
            try:
                text = full.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            found.extend(_findings(path, text))
        self.assertEqual(found, [], "\n" + "\n".join(found))

    def test_no_tracked_path_holds_a_retired_name(self):
        found = [line for path in _tracked_files() for line in _findings("(path)", path)]
        self.assertEqual(found, [], "\n" + "\n".join(found))

    def test_the_check_finds_a_retired_name_in_each_form(self):
        for text in ("services/core", "SERVICE_NAME", "--service x", "service-py", "a python-odcs project",
                     "GET /api/v1/current-prod", "current_prod_release_id", "blue/green", "<svc>"):
            with self.subTest(text=text):
                self.assertNotEqual(_findings("x", text), [])

    def test_the_check_leaves_other_words_and_the_allowed_text_alone(self):
        for text in ("projects/core", "serviceable", "kubectl port-forward svc/ui 8090:8090",
                     "written by card-service", "purpose: service_operation}", "a CD pipeline",
                     "env_var('POSTGRES_USER', 'continuo_svc')"):
            with self.subTest(text=text):
                self.assertEqual(_findings("x", text), [])


if __name__ == "__main__":
    unittest.main()
