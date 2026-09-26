"""Command-line entry point for `jml`."""

import argparse
import sys
from importlib.metadata import version
from pathlib import Path

from jml.validate import BaseRevisionError, read_base_people_ids, validate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jml",
        description="Joiner-mover-leaver automation: people as code for Okta and GitHub.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('jml-kit')}")
    commands = parser.add_subparsers(dest="command", metavar="<command>")

    validate_parser = commands.add_parser(
        "validate",
        help="check people.yaml, teams.yaml and people.archive.yaml",
        description=(
            "Check people.yaml, teams.yaml and people.archive.yaml. Needs no credentials. "
            "Exits 1 and prints every problem found if the files are invalid."
        ),
    )
    validate_parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=Path("."),
        help="directory holding the people file (default: current directory)",
    )
    validate_parser.add_argument(
        "--base",
        metavar="REV",
        help=(
            "git revision to compare against: anyone in people.yaml at REV who is no longer "
            "in the file must be in people.archive.yaml"
        ),
    )
    return parser


def run_validate(root: Path, base: str | None) -> int:
    base_ids = None
    if base:
        try:
            base_ids = read_base_people_ids(root, base)
        except BaseRevisionError as exc:
            print(f"jml validate: {exc}", file=sys.stderr)
            return 2
    result = validate(root, base_ids)
    if not result.ok:
        for error in result.errors:
            print(error, file=sys.stderr)
        print(f"jml validate: {len(result.errors)} problem(s) found", file=sys.stderr)
        return 1
    assert result.people is not None and result.teams is not None
    active = sum(1 for person in result.people.people if person.status == "active")
    print(
        f"ok: {len(result.people.people)} people ({active} active) "
        f"in {len(result.teams.teams)} teams"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate":
        return run_validate(args.root, args.base)
    parser.print_help()
    return 0
