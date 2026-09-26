"""Validate the people file, team definitions and archive in a repository checkout.

Validation needs no credentials. It checks, in order:

1. Each file parses as YAML, with no duplicate or unknown keys.
2. Ids, emails and GitHub usernames are well formed and unique, emails are on the
   company domain, and no active person reuses an archived id.
3. Every team exists, and every Okta group is declared in teams.yaml.
4. Leavers have an end date, active people do not, and end is not before start.
5. Active people fit in Okta's 10-user free plan limit minus the reserved seats.
6. Anyone removed from people.yaml since the base revision is in people.archive.yaml.
7. Every team's mac_profile has a mac/profiles/<name>.Brewfile.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from jml.models import ArchiveFile, PeopleFile, TeamsFile

PEOPLE_FILE = "people.yaml"
TEAMS_FILE = "teams.yaml"
ARCHIVE_FILE = "people.archive.yaml"
PROFILES_DIR = Path("mac") / "profiles"
OKTA_SEAT_LIMIT = 10


class _Loader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate keys and leaves dates as strings for the models."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"duplicate key {key!r}", key_node.start_mark
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


_Loader.yaml_implicit_resolvers = {
    first: [(tag, regex) for tag, regex in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


class InvalidFile(Exception):
    """A file could not be parsed or does not match its model."""

    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


class BaseRevisionError(Exception):
    """The base revision for the history check could not be read."""


@dataclass(frozen=True)
class Result:
    errors: list[str]
    people: PeopleFile | None = None
    teams: TeamsFile | None = None
    archive: ArchiveFile | None = None

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_yaml(text: str, name: str) -> Any:
    try:
        return yaml.load(text, Loader=_Loader)
    except yaml.YAMLError as exc:
        raise InvalidFile([f"{name}: invalid YAML: {_describe_yaml_error(exc)}"]) from exc


def _describe_yaml_error(exc: yaml.YAMLError) -> str:
    mark = getattr(exc, "problem_mark", None)
    problem = getattr(exc, "problem", None) or str(exc)
    if mark is None:
        return problem
    return f"{problem} (line {mark.line + 1}, column {mark.column + 1})"


def _load[M: BaseModel](path: Path, model: type[M]) -> M:
    if not path.is_file():
        raise InvalidFile([f"{path.name}: file not found"])
    return load_text(path.read_text(encoding="utf-8"), path.name, model)


def load_text[M: BaseModel](text: str, name: str, model: type[M]) -> M:
    """Parse one file's text into its model, raising InvalidFile with every problem."""
    data = parse_yaml(text, name)
    if data is None:
        raise InvalidFile([f"{name}: file is empty"])
    try:
        return model.model_validate(data)
    except PydanticValidationError as exc:
        raise InvalidFile(_describe_model_errors(exc, name, data)) from exc


def _describe_model_errors(exc: PydanticValidationError, name: str, data: Any) -> list[str]:
    errors = []
    for error in exc.errors():
        where = _describe_location(error["loc"], data)
        match error["type"]:
            case "extra_forbidden":
                message = "unknown key"
            case "missing":
                message = "required key is missing"
            case "value_error":
                message = str(error["ctx"]["error"])
            case _:
                message = error["msg"]
        errors.append(f"{name}: {where}: {message}" if where else f"{name}: {message}")
    return errors


def _describe_location(loc: tuple[int | str, ...], data: Any) -> str:
    """Render ('people', 2, 'team') as 'people[2] (ana.ruiz).team'."""
    parts: list[str] = []
    node = data
    for item in loc:
        if isinstance(item, int):
            parts.append(f"[{item}]")
            node = node[item] if isinstance(node, list) and item < len(node) else None
            if isinstance(node, dict) and isinstance(node.get("id"), str):
                parts.append(f" ({node['id']})")
        else:
            parts.append(f".{item}" if parts else item)
            node = node.get(item) if isinstance(node, dict) else None
    return "".join(parts)


def read_at_revision(root: Path, base: str, name: str) -> str | None:
    """Return file `name` under `root` at git revision `base`, or None if it had none."""

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)

    if git("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}").returncode != 0:
        raise BaseRevisionError(f"base revision {base!r} is not a commit in this repository")
    spec = f"{base}:./{name}"
    if git("cat-file", "-e", spec).returncode != 0:
        return None
    shown = git("show", spec)
    if shown.returncode != 0:
        raise BaseRevisionError(f"cannot read {spec}: {shown.stderr.strip()}")
    return shown.stdout


def read_base_people_ids(root: Path, base: str) -> set[str]:
    """Return the person ids in people.yaml at git revision `base` (empty if it had none)."""
    text = read_at_revision(root, base, PEOPLE_FILE)
    return people_ids(text) if text is not None else set()


def people_ids(text: str) -> set[str]:
    """Collect person ids from people.yaml text, tolerating a file that fails validation."""
    try:
        data = parse_yaml(text, PEOPLE_FILE)
    except InvalidFile:
        return set()
    people = data.get("people") if isinstance(data, dict) else None
    if not isinstance(people, list):
        return set()
    return {p["id"] for p in people if isinstance(p, dict) and isinstance(p.get("id"), str)}


def validate(root: Path, base_ids: set[str] | None = None) -> Result:
    """Validate the files under `root`.

    `base_ids` are the person ids at the base revision; the history check runs only when
    they are given.
    """
    errors: list[str] = []
    loaded: dict[str, Any] = {}
    for name, model in (
        (PEOPLE_FILE, PeopleFile),
        (TEAMS_FILE, TeamsFile),
        (ARCHIVE_FILE, ArchiveFile),
    ):
        try:
            loaded[name] = _load(root / name, model)
        except InvalidFile as exc:
            errors.extend(exc.errors)
    if errors:
        return Result(errors)

    people: PeopleFile = loaded[PEOPLE_FILE]
    teams: TeamsFile = loaded[TEAMS_FILE]
    archive: ArchiveFile = loaded[ARCHIVE_FILE]

    errors += _check_unique(people)
    errors += _check_email_domain(people)
    errors += _check_ids_not_reused(people, archive)
    errors += _check_references(people, teams)
    errors += _check_seats(people)
    if base_ids is not None:
        errors += _check_history(people, archive, base_ids)
    errors += _check_profiles(root, teams)
    return Result(errors, people, teams, archive)


def _check_unique(people: PeopleFile) -> list[str]:
    errors = []
    for field, normalize in (
        ("id", str),
        ("email", str.lower),
        ("github", str.lower),
    ):
        seen: dict[str, str] = {}
        for person in people.people:
            value = getattr(person, field)
            if value is None:
                continue
            key = normalize(value)
            if key in seen:
                errors.append(
                    f"{PEOPLE_FILE}: {field} {value!r} is used by both {seen[key]} and {person.id}"
                )
            else:
                seen[key] = person.id
    return errors


def _check_email_domain(people: PeopleFile) -> list[str]:
    domain = f"{people.company}.example".lower()
    return [
        f"{PEOPLE_FILE}: {person.id}: email {person.email!r} is not on the company domain {domain}"
        for person in people.people
        if person.email.rsplit("@", 1)[1].lower() != domain
    ]


def _check_ids_not_reused(people: PeopleFile, archive: ArchiveFile) -> list[str]:
    archived = {entry.id for entry in archive.archived}
    return [
        f"{PEOPLE_FILE}: id {person.id!r} is archived in {ARCHIVE_FILE} and cannot be reused"
        for person in people.people
        if person.status == "active" and person.id in archived
    ]


def _check_references(people: PeopleFile, teams: TeamsFile) -> list[str]:
    errors = []
    declared = set(teams.groups)
    for name, team in teams.teams.items():
        for group in team.okta_groups:
            if group not in declared:
                errors.append(
                    f"{TEAMS_FILE}: teams.{name}.okta_groups: {group!r} is not in the groups list"
                )
    for person in people.people:
        if person.team not in teams.teams:
            known = ", ".join(sorted(teams.teams))
            errors.append(
                f"{PEOPLE_FILE}: {person.id}: team {person.team!r} is not defined in "
                f"{TEAMS_FILE} (known teams: {known})"
            )
        for group in person.extra_groups:
            if group not in declared:
                errors.append(
                    f"{PEOPLE_FILE}: {person.id}: extra group {group!r} is not in the "
                    f"groups list in {TEAMS_FILE}"
                )
    return errors


def _check_seats(people: PeopleFile) -> list[str]:
    available = OKTA_SEAT_LIMIT - people.seats.reserved
    active = sum(1 for person in people.people if person.status == "active")
    if active <= available:
        return []
    return [
        f"{PEOPLE_FILE}: {active} active people, but only {available} Okta seats are available "
        f"({OKTA_SEAT_LIMIT} limit minus {people.seats.reserved} reserved)"
    ]


def _check_history(people: PeopleFile, archive: ArchiveFile, base_ids: set[str]) -> list[str]:
    current = {person.id for person in people.people}
    archived = {entry.id for entry in archive.archived}
    return [
        f"{PEOPLE_FILE}: {removed} was removed but has no entry in {ARCHIVE_FILE}; "
        "offboard with status: leaver and an end date, and remove the block only after "
        "apply has archived them"
        for removed in sorted(base_ids - current - archived)
    ]


def _check_profiles(root: Path, teams: TeamsFile) -> list[str]:
    errors = []
    for name, team in teams.teams.items():
        profile = PROFILES_DIR / f"{team.mac_profile}.Brewfile"
        if not (root / profile).is_file():
            errors.append(f"{TEAMS_FILE}: teams.{name}.mac_profile: {profile} does not exist")
    return errors
