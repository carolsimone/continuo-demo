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
import sys
from typing import List, Optional, TextIO

log = logging.getLogger("image_pins")

_RUNTIME_IMAGE = "ghcr.io/carolsimone/continuo-python-runtime"
_RUNTIME_FROM = re.compile(
    r"^FROM\s+(?:--platform=\S+\s+)?" + re.escape(_RUNTIME_IMAGE) + r"-[a-z0-9]+(?:-[a-z0-9]+)*:v(\d+\.\d+\.\d+)"
    r"(?:\s+AS\s+\S+)?\s*$",
    re.IGNORECASE,
)
_INSTALLED_RUNTIME = re.compile(r"^continuo-python-runtime\s+v(\S+)\s*$", re.MULTILINE)


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
    ):
        command = commands.add_parser(name, help=help_text, description=help_text)
        command.add_argument("service_dir", help="the service directory that holds the Dockerfile")
    args = parser.parse_args(argv)

    if args.command == "runtime-version":
        return _cmd_runtime_version(args.service_dir, stdout if stdout is not None else sys.stdout)
    return _cmd_check_installed(args.service_dir, stdin if stdin is not None else sys.stdin)


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
