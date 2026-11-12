#!/usr/bin/env python3
"""Read the pins a service image declares.

Subcommands, each taking a service directory:

  runtime-version  print the continuo-python-runtime version the FROM line of
                   <dir>/Dockerfile names (stdout carries only that version).
  check-installed  read `uv tool list` from stdin and succeed when it lists the
                   continuo-python-runtime version <dir>/Dockerfile names.
  check-dbt        succeed when <dir>/Dockerfile (and <dir>/Dockerfile.local, when
                   present) pin every dbt package with ==, to the same versions.

Diagnostics go to stderr through logging; the exit status is 0 on success and 1
on a failed check. The module uses the standard library only.
"""

from __future__ import annotations

import argparse
import logging
import re
import pathlib
import sys
from typing import Dict, List, Optional, TextIO, Tuple, Union

log = logging.getLogger("image_pins")

_RUNTIME_IMAGE = "ghcr.io/carolsimone/continuo-python-runtime"
_RUNTIME_FROM = re.compile(
    r"^(?i:FROM)\s+(?:--platform=\S+\s+)?" + re.escape(_RUNTIME_IMAGE) + r"-[a-z0-9]+(?:-[a-z0-9]+)*:v(\d+\.\d+\.\d+)"
    r"(?:\s+(?i:AS)\s+\S+)?\s*$"
)
_INSTALLED_RUNTIME = re.compile(r"^continuo-python-runtime\s+v(\S+)\s*$", re.MULTILINE)

DBT_PACKAGES = ("dbt-core", "dbt-postgres", "dbt-adapters", "dbt-common")
_PIP_INSTALL = re.compile(r"^RUN\s.*\bpip\s+install\b", re.IGNORECASE)
_EXACT_PIN = re.compile(r"^==([A-Za-z0-9][A-Za-z0-9.+!_-]*)$")


class PinError(ValueError):
    """A Dockerfile does not declare a pin the way the release process reads it."""


def runtime_version(dockerfile_text: str) -> str:
    """The X.Y.Z of the one FROM line that names the continuo-python-runtime image."""
    candidates = []
    for raw in dockerfile_text.splitlines():
        line = raw.replace("\r", "").strip()
        words = line.split()
        if words and words[0].upper() == "FROM" and "continuo-python-runtime" in line:
            candidates.append(line)
    if not candidates:
        raise PinError(f"no FROM line names {_RUNTIME_IMAGE}-<engine>")
    if len(candidates) > 1:
        raise PinError(f"{len(candidates)} FROM lines name {_RUNTIME_IMAGE}-<engine>; keep one")
    match = _RUNTIME_FROM.match(candidates[0])
    if match is None:
        raise PinError(f"FROM must name {_RUNTIME_IMAGE}-<engine>:v<X.Y.Z> (got '{candidates[0]}')")
    return match.group(1)


def installed_runtime_version(uv_tool_list: str) -> Optional[str]:
    """The version on the `continuo-python-runtime vX.Y.Z` line of `uv tool list`, or None."""
    match = _INSTALLED_RUNTIME.search(uv_tool_list)
    return match.group(1) if match else None


def _instructions(dockerfile_text: str) -> List[str]:
    """The instructions of a Dockerfile, each line ending in a backslash joined to the next."""
    instructions: List[str] = []
    pending = ""
    for raw in dockerfile_text.splitlines():
        line = raw.replace("\r", "").strip()
        if line.endswith("\\"):
            pending += line[:-1].rstrip() + " "
            continue
        instructions.append((pending + line).strip())
        pending = ""
    if pending:
        instructions.append(pending.strip())
    return instructions


def _package_token(token: str, package: str) -> bool:
    """Whether a pip argument names the package, alone or with a version specifier."""
    return re.match(re.escape(package) + r"(?:[=<>~!]|$)", token) is not None


def dbt_pins(dockerfile_text: str) -> Dict[str, str]:
    """The version of each dbt package the dbt `RUN pip install` instruction pins with ==."""
    installs = []
    for instruction in _instructions(dockerfile_text):
        if not _PIP_INSTALL.match(instruction):
            continue
        tokens = [word.strip("\"'") for word in instruction.split()]
        if any(_package_token(token, DBT_PACKAGES[0]) for token in tokens):
            installs.append(tokens)
    if not installs:
        raise PinError(f"no RUN pip install instruction installs {DBT_PACKAGES[0]}")
    if len(installs) > 1:
        raise PinError(f"{len(installs)} RUN pip install instructions install {DBT_PACKAGES[0]}; keep one")
    pins: Dict[str, str] = {}
    pinned_by: Dict[str, str] = {}
    for token in installs[0]:
        for package in DBT_PACKAGES:
            if not _package_token(token, package):
                continue
            pin = _EXACT_PIN.match(token[len(package):])
            if pin is None:
                raise PinError(f"{package} must be pinned with == (got '{token}')")
            if package in pins:
                raise PinError(f"{package} is pinned twice (got '{pinned_by[package]}' and '{token}')")
            pins[package] = pin.group(1)
            pinned_by[package] = token
    return pins


def _dbt_service_report(service_dir: Union[pathlib.Path, str]) -> Tuple[List[str], Dict[str, str]]:
    """The problems of a dbt service's Dockerfiles, and the pins of its Dockerfile."""
    dockerfile = f"{service_dir}/Dockerfile"
    local = f"{service_dir}/Dockerfile.local"
    text = _read_dockerfile(dockerfile)
    if text is None:
        return [f"{dockerfile}: no such file"], {}
    files = [(dockerfile, text)]
    local_text = _read_dockerfile(local)
    if local_text is not None:
        files.append((local, local_text))

    problems: List[str] = []
    pins_by_path: Dict[str, Dict[str, str]] = {}
    for path, file_text in files:
        try:
            pins = dbt_pins(file_text)
        except PinError as err:
            problems.append(f"{path}: {err}")
            continue
        pins_by_path[path] = pins
        for package in DBT_PACKAGES:
            if package not in pins:
                problems.append(f'{path}: {package} is not pinned (add "{package}==<version>")')
    if dockerfile in pins_by_path and local in pins_by_path:
        for package in DBT_PACKAGES:
            wanted = pins_by_path[dockerfile].get(package)
            found = pins_by_path[local].get(package)
            if wanted is not None and found is not None and wanted != found:
                problems.append(f"{local} pins {package}=={found} but {dockerfile} pins {package}=={wanted}")
    return problems, pins_by_path.get(dockerfile, {})


def check_dbt_service(service_dir: Union[pathlib.Path, str]) -> List[str]:
    """The problems of <dir>/Dockerfile and, when present, <dir>/Dockerfile.local; empty when the service passes."""
    return _dbt_service_report(service_dir)[0]


def _read_dockerfile(path: str) -> Optional[str]:
    """The text of a Dockerfile, or None when the file does not exist."""
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except FileNotFoundError:
        return None


def _wanted_runtime(service_dir: str) -> Optional[str]:
    """The runtime version <service_dir>/Dockerfile names, logging an error and returning None when it names none."""
    path = f"{service_dir}/Dockerfile"
    text = _read_dockerfile(path)
    if text is None:
        log.error("%s: no such file", path)
        return None
    try:
        return runtime_version(text)
    except PinError as err:
        log.error("%s: %s", path, err)
        return None


def _cmd_runtime_version(service_dir: str, stdout: TextIO) -> int:
    wanted = _wanted_runtime(service_dir)
    if wanted is None:
        return 1
    stdout.write(wanted + "\n")
    return 0


def _cmd_check_installed(service_dir: str, stdin: TextIO) -> int:
    wanted = _wanted_runtime(service_dir)
    if wanted is None:
        return 1
    installed = installed_runtime_version(stdin.read())
    path = f"{service_dir}/Dockerfile"
    if installed is None:
        log.error(
            "continuo-python-runtime is not installed (uv tool list has no continuo-python-runtime line); %s names %s",
            path,
            wanted,
        )
        return 1
    if installed != wanted:
        log.error("continuo-python-runtime %s is installed but %s names %s", installed, path, wanted)
        return 1
    log.info("continuo-python-runtime %s is the version %s names", installed, path)
    return 0


def _cmd_check_dbt(service_dir: str) -> int:
    problems, pins = _dbt_service_report(service_dir)
    if problems:
        for problem in problems:
            log.error("%s", problem)
        return 1
    log.info("%s pins %s", service_dir, " ".join(f"{package}=={pins[package]}" for package in DBT_PACKAGES))
    return 0


def main(
    argv: Optional[List[str]] = None,
    stdin: Optional[TextIO] = None,
    stdout: Optional[TextIO] = None,
) -> int:
    """Run one subcommand and return its exit status."""
    parser = argparse.ArgumentParser(prog="image_pins.py", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("runtime-version", "print the continuo-python-runtime version the FROM line names"),
        ("check-installed", "check the installed continuo-python-runtime (uv tool list on stdin) against the FROM line"),
        ("check-dbt", "check that the Dockerfiles pin every dbt package with == to the same versions"),
    ):
        command = commands.add_parser(name, help=help_text, description=help_text)
        command.add_argument("service_dir", help="the service directory that holds the Dockerfile")
    args = parser.parse_args(argv)

    if args.command == "runtime-version":
        return _cmd_runtime_version(args.service_dir, stdout if stdout is not None else sys.stdout)
    if args.command == "check-dbt":
        return _cmd_check_dbt(args.service_dir)
    return _cmd_check_installed(args.service_dir, stdin if stdin is not None else sys.stdin)


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
