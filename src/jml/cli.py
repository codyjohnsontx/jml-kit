"""Command-line entry point for `jml`."""

import argparse
import sys
from datetime import date
from importlib.metadata import version
from pathlib import Path

from jml import demo, render
from jml.models import PeopleFile, TeamsFile
from jml.planner import Files, plan
from jml.validate import (
    PEOPLE_FILE,
    TEAMS_FILE,
    BaseRevisionError,
    InvalidFile,
    check_plannable,
    load_text,
    read_at_revision,
    read_base_people_ids,
    validate,
)


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

    plan_parser = commands.add_parser(
        "plan",
        help="show the changes that make Okta and GitHub match the people file",
        description=(
            "Validate the files, read live state, and print the changes apply would make, "
            "those already needed before this change, and unmanaged accounts. Exits 1 if the "
            "files are invalid or the plan holds a change the kit refuses to make."
        ),
    )
    plan_parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=Path("."),
        help="directory holding the people file (default: current directory)",
    )
    plan_parser.add_argument(
        "--fake",
        action="store_true",
        help=(
            "plan against an in-memory Okta and GitHub, needing no credentials. The fake "
            "starts as if the base files were applied (without --base: the file minus its "
            "newest joiner), plus an unmanaged admin user and one hand-made group membership"
        ),
    )
    plan_parser.add_argument(
        "--base",
        metavar="REV",
        help=(
            "git revision the change is based on: changes the files at REV would need too "
            "are shown apart as already needed, and anyone removed since REV must be archived"
        ),
    )
    plan_parser.add_argument(
        "--prune",
        action="store_true",
        help=(
            "also deactivate Okta users the kit created (they carry jmlId) that are not in "
            "the file. GitHub accounts carry no jmlId, so they are never pruned"
        ),
    )
    plan_parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="output format (default: markdown)",
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


def read_base_files(root: Path, base: str, files: Files) -> Files | None:
    """The files at revision `base`, or None if they do not parse or break a rule the
    planner relies on. A file missing at `base` means no people yet, or the current team
    definitions."""
    try:
        people_text = read_at_revision(root, base, PEOPLE_FILE)
        teams_text = read_at_revision(root, base, TEAMS_FILE)
        people = (
            load_text(people_text, PEOPLE_FILE, PeopleFile)
            if people_text is not None
            else files.people.model_copy(update={"people": []})
        )
        teams = (
            load_text(teams_text, TEAMS_FILE, TeamsFile) if teams_text is not None else files.teams
        )
    except InvalidFile:
        return None
    if check_plannable(people, teams):
        return None
    return Files(people, teams, files.archive)


def run_plan(args: argparse.Namespace, today: date) -> int:
    root: Path = args.root
    base_ids = None
    if args.base:
        try:
            base_ids = read_base_people_ids(root, args.base)
        except BaseRevisionError as exc:
            print(f"jml plan: {exc}", file=sys.stderr)
            return 2
    result = validate(root, base_ids)
    if not result.ok:
        for error in result.errors:
            print(error, file=sys.stderr)
        print(f"jml plan: {len(result.errors)} problem(s) found", file=sys.stderr)
        return 1
    assert result.people and result.teams and result.archive
    files = Files(result.people, result.teams, result.archive)

    base = None
    if args.base:
        base = read_base_files(root, args.base, files)
        if base is None:
            print(
                f"jml plan: the files at {args.base} are not valid, so drift is not shown apart",
                file=sys.stderr,
            )
    if not args.fake:
        print(
            "jml plan: the Okta and GitHub adapters are not built yet; run with --fake",
            file=sys.stderr,
        )
        return 2
    seed = base or demo.demo_base(files)
    okta, github = demo.fake_org(seed, today)
    drift_base = None if args.base and base is None else seed
    result_plan = plan(files, okta, github, today=today, prune=args.prune, base=drift_base)
    if args.format == "json":
        print(render.to_json(result_plan), end="")
    else:
        print(render.to_markdown(result_plan, "Against a fake Okta and GitHub."), end="")
    return 1 if result_plan.refused else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate":
        return run_validate(args.root, args.base)
    if args.command == "plan":
        return run_plan(args, date.today())
    parser.print_help()
    return 0
