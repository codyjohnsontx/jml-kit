"""Validate the people file, team definitions and archive in a repository checkout.

Validation needs no credentials. It checks, in order:

1. Each file parses as plain YAML (no anchors, aliases or explicit tags, bounded size and
   nesting), with no duplicate or unknown keys.
2. Ids, emails and GitHub usernames are well formed and unique (emails and GitHub usernames
   case-insensitively), emails are on the company domain, and no active person reuses an
   archived id.
3. Every team exists, and every Okta group is declared in teams.yaml.
4. Leavers have an end date, active people do not, and end is not before start.
5. Active people fit in Okta's 10-user free plan limit minus the reserved seats.
6. Anyone removed from people.yaml since the base revision is in people.archive.yaml.
7. Every team's mac_profile has a mac/profiles/<name>.Brewfile.

Every error names the file and, where the problem has one, the line to change.
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
# The files are small and hand-edited; anything bigger or deeper is a mistake or an attack.
MAX_FILE_BYTES = 256 * 1024
MAX_DEPTH = 10

MERGE_TAG = "tag:yaml.org,2002:merge"
YamlPath = tuple[int | str, ...]


class _Loader(yaml.SafeLoader):
    """SafeLoader restricted to plain YAML a reviewer can read in a diff.

    Rejects anchors, aliases, explicit tags, merge keys, non-scalar keys, duplicate keys
    and deep nesting. Leaves dates as strings for the models to parse.
    """

    _depth = 0

    def compose_node(self, parent: yaml.Node | None, index: Any) -> yaml.Node:
        event = self.peek_event()
        if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None):
            raise yaml.composer.ComposerError(
                None, None, "anchors and aliases are not allowed", event.start_mark
            )
        tag = getattr(event, "tag", None)
        if tag is not None:
            raise yaml.composer.ComposerError(
                None, None, f"explicit tag {tag!r} is not allowed", event.start_mark
            )
        if self._depth >= MAX_DEPTH:
            raise yaml.composer.ComposerError(
                None, None, f"nesting deeper than {MAX_DEPTH} levels", event.start_mark
            )
        self._depth += 1
        try:
            return super().compose_node(parent, index)
        finally:
            self._depth -= 1

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            if not isinstance(key_node, yaml.ScalarNode):
                raise yaml.constructor.ConstructorError(
                    None, None, "mapping keys must be plain values", key_node.start_mark
                )
            if key_node.tag == MERGE_TAG:
                raise yaml.constructor.ConstructorError(
                    None, None, "merge keys (<<) are not allowed", key_node.start_mark
                )
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

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class Source:
    """A parsed file's name and the line each value came from, for error messages."""

    name: str
    lines: dict[YamlPath, int]

    def at(self, *path: int | str) -> str:
        """Return 'people.yaml:12' for the nearest recorded line of `path`."""
        while path and path not in self.lines:
            path = path[:-1]
        line = self.lines.get(path)
        return f"{self.name}:{line}" if line else self.name


def parse_yaml(text: str, name: str) -> tuple[Any, Source]:
    """Parse one YAML document, returning its data and where each value came from."""
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        raise InvalidFile([f"{name}: file is larger than {MAX_FILE_BYTES} bytes"])
    loader = _Loader(text)
    try:
        node = loader.get_single_node()
        data = None if node is None else loader.construct_document(node)
    except yaml.YAMLError as exc:
        raise InvalidFile([_describe_yaml_error(exc, name)]) from exc
    finally:
        loader.dispose()
    lines: dict[YamlPath, int] = {}
    if node is not None:
        _record_lines(node, (), lines)
    return data, Source(name, lines)


def _record_lines(node: yaml.Node, path: YamlPath, lines: dict[YamlPath, int]) -> None:
    lines[path] = node.start_mark.line + 1
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            child = (*path, key_node.value)
            _record_lines(value_node, child, lines)
            lines[child] = key_node.start_mark.line + 1  # point at the key, not its value
    elif isinstance(node, yaml.SequenceNode):
        for index, item in enumerate(node.value):
            _record_lines(item, (*path, index), lines)


def _describe_yaml_error(exc: yaml.YAMLError, name: str) -> str:
    mark = getattr(exc, "problem_mark", None)
    problem = getattr(exc, "problem", None) or str(exc)
    if mark is None:
        return f"{name}: invalid YAML: {problem}"
    return f"{name}:{mark.line + 1}: invalid YAML: {problem} (column {mark.column + 1})"


def _load[M: BaseModel](path: Path, model: type[M]) -> tuple[M, Source]:
    if not path.is_file():
        raise InvalidFile([f"{path.name}: file not found"])
    if path.stat().st_size > MAX_FILE_BYTES:
        raise InvalidFile([f"{path.name}: file is larger than {MAX_FILE_BYTES} bytes"])
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidFile([f"{path.name}: file is not valid UTF-8"]) from exc
    data, source = parse_yaml(text, path.name)
    if data is None:
        raise InvalidFile([f"{path.name}: file is empty"])
    try:
        return model.model_validate(data), source
    except PydanticValidationError as exc:
        raise InvalidFile(_describe_model_errors(exc, source, data)) from exc


def _describe_model_errors(exc: PydanticValidationError, source: Source, data: Any) -> list[str]:
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
        at = source.at(*error["loc"])
        errors.append(f"{at}: {where}: {message}" if where else f"{at}: {message}")
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


def read_base_people_ids(root: Path, base: str) -> set[str]:
    """Return the person ids in people.yaml at git revision `base` (empty if it had none)."""

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)

    if git("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}").returncode != 0:
        raise BaseRevisionError(f"base revision {base!r} is not a commit in this repository")
    spec = f"{base}:./{PEOPLE_FILE}"
    if git("cat-file", "-e", spec).returncode != 0:
        return set()
    shown = git("show", spec)
    if shown.returncode != 0:
        raise BaseRevisionError(f"cannot read {spec}: {shown.stderr.strip()}")
    return people_ids(shown.stdout)


def people_ids(text: str) -> set[str]:
    """Collect person ids from people.yaml text, tolerating a file that fails validation."""
    try:
        data, _ = parse_yaml(text, PEOPLE_FILE)
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

    people, people_src = loaded[PEOPLE_FILE]
    teams, teams_src = loaded[TEAMS_FILE]
    archive, _ = loaded[ARCHIVE_FILE]

    errors += _check_unique(people, people_src)
    errors += _check_email_domain(people, people_src)
    errors += _check_ids_not_reused(people, people_src, archive)
    errors += _check_references(people, people_src, teams, teams_src)
    errors += _check_seats(people, people_src)
    if base_ids is not None:
        errors += _check_history(people, archive, base_ids)
    errors += _check_profiles(root, teams, teams_src)
    return Result(errors, people, teams)


def _check_unique(people: PeopleFile, src: Source) -> list[str]:
    errors = []
    for field in ("id", "email", "github"):
        seen: dict[str, str] = {}
        for index, person in enumerate(people.people):
            value = getattr(person, field)
            if value is None:
                continue
            key = value.lower()
            if key in seen:
                errors.append(
                    f"{src.at('people', index, field)}: {field} {value!r} is used by both "
                    f"{seen[key]} and people[{index}] ({person.id})"
                )
            else:
                seen[key] = f"people[{index}] ({person.id}) at {src.at('people', index, field)}"
    return errors


def _check_email_domain(people: PeopleFile, src: Source) -> list[str]:
    domain = f"{people.company}.example".lower()
    return [
        f"{src.at('people', index, 'email')}: {person.id}: email {person.email!r} is not on "
        f"the company domain {domain}"
        for index, person in enumerate(people.people)
        if person.email.rsplit("@", 1)[1].lower() != domain
    ]


def _check_ids_not_reused(people: PeopleFile, src: Source, archive: ArchiveFile) -> list[str]:
    archived = {entry.id for entry in archive.archived}
    return [
        f"{src.at('people', index, 'id')}: id {person.id!r} is archived in {ARCHIVE_FILE} "
        "and cannot be reused"
        for index, person in enumerate(people.people)
        if person.status == "active" and person.id in archived
    ]


def _check_references(
    people: PeopleFile, people_src: Source, teams: TeamsFile, teams_src: Source
) -> list[str]:
    errors = []
    declared = set(teams.groups)
    for name, team in teams.teams.items():
        for g, group in enumerate(team.okta_groups):
            if group not in declared:
                errors.append(
                    f"{teams_src.at('teams', name, 'okta_groups', g)}: "
                    f"teams.{name}.okta_groups: {group!r} is not in the groups list"
                )
    for index, person in enumerate(people.people):
        if person.team not in teams.teams:
            known = ", ".join(sorted(teams.teams))
            errors.append(
                f"{people_src.at('people', index, 'team')}: {person.id}: team "
                f"{person.team!r} is not defined in {TEAMS_FILE} (known teams: {known})"
            )
        for g, group in enumerate(person.extra_groups):
            if group not in declared:
                errors.append(
                    f"{people_src.at('people', index, 'extra_groups', g)}: {person.id}: "
                    f"extra group {group!r} is not in the groups list in {TEAMS_FILE}"
                )
    return errors


def _check_seats(people: PeopleFile, src: Source) -> list[str]:
    available = OKTA_SEAT_LIMIT - people.seats.reserved
    active = sum(1 for person in people.people if person.status == "active")
    if active <= available:
        return []
    at = src.at("seats", "reserved") if "seats" in people.model_fields_set else src.at("people")
    return [
        f"{at}: {active} active people, but only {available} Okta seats are available "
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


def _check_profiles(root: Path, teams: TeamsFile, src: Source) -> list[str]:
    errors = []
    for name, team in teams.teams.items():
        profile = PROFILES_DIR / f"{team.mac_profile}.Brewfile"
        if not (root / profile).is_file():
            errors.append(
                f"{src.at('teams', name, 'mac_profile')}: teams.{name}.mac_profile: "
                f"{profile} does not exist"
            )
    return errors
