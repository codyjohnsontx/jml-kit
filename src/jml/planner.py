"""Compute the plan: the changes that make Okta and GitHub match the people file.

The planner reads live state once, through the ports, and compares it with the files.
It never writes. `jml plan` renders the result; apply (`jml.apply`) executes the same
changes, so running apply and then planning again gives an empty plan.

Rules:

- A person's Okta user is found by its jmlId profile attribute, never by name or email,
  so a rename is a profile update rather than a leaver plus a joiner. A jmlId on more
  than one Okta user is refused, naming every account, and nothing is planned for it.
- Only declared groups (teams.yaml `groups`) and the teams' GitHub teams are managed.
  Anything else live is listed as unmanaged and left alone, except that a user is
  removed from every group before being deactivated.
- An active person gets their team's groups plus extra_groups, and their team's GitHub
  team when they have a github username. A pending GitHub invitation counts as done.
- A suspended person set back to active is unsuspended only after their groups and
  teams match the file, so stale access is gone before they can sign in.
- A leaver whose end date is in the future is suspended. On or after the end date, they
  are removed from GitHub and every group, then deactivated.
- A user whose block was removed and who is in people.archive.yaml is deleted, but only
  once DEPROVISIONED. Otherwise the plan refuses, since Okta would deactivate instead.
- Users without jmlId are never touched. `prune` deactivates users the kit created that
  are neither in the file nor archived. GitHub accounts carry no jmlId, so members of
  managed teams who are not in the file are listed as unmanaged and never pruned.
- Given the files at the base revision, a change the base files would also need is drift:
  it was needed before the change under review, because someone changed live state
  outside this repository, an end date passed, or an apply has not run.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from jml.changes import (
    ActivateUser,
    AddToGroup,
    AddToTeam,
    Change,
    CreateGroup,
    CreateTeam,
    CreateUser,
    DeactivateUser,
    DeleteUser,
    InviteToOrg,
    RemoveFromGroup,
    RemoveFromOrg,
    RemoveFromTeam,
    SuspendUser,
    UnsuspendUser,
    UpdateProfile,
)
from jml.models import ArchiveFile, PeopleFile, Person, TeamsFile
from jml.ports import GithubOrg, OktaDirectory, OktaUser, UserStatus


@dataclass(frozen=True)
class Files:
    people: PeopleFile
    teams: TeamsFile
    archive: ArchiveFile


@dataclass(frozen=True)
class Unmanaged:
    system: str
    object: str
    name: str
    note: str


@dataclass(frozen=True)
class Plan:
    changes: tuple[Change, ...]
    drift: frozenset[Change]
    unmanaged: tuple[Unmanaged, ...]
    refused: tuple[str, ...]
    drift_checked: bool  # False when there were no base files to tell drift apart
    base_error: str | None = None  # why the base files could not be used, if they were given

    @property
    def empty(self) -> bool:
        return not self.changes and not self.refused


@dataclass(frozen=True)
class Live:
    """A snapshot of Okta and GitHub, read once per plan."""

    users: tuple[OktaUser, ...]
    groups: dict[str, str]  # name to Okta id
    user_groups: dict[str, set[str]]  # Okta id to group names, for users with a jmlId
    teams: set[str]
    team_members: dict[str, set[str]]  # slug to lowercased usernames, for managed teams
    org_members: set[str]  # lowercased
    invitations: dict[str, set[str]]  # lowercased username to team slugs

    @classmethod
    def read(cls, files: Files, okta: OktaDirectory, github: GithubOrg) -> "Live":
        users = tuple(okta.list_users())
        teams = github.list_teams()
        return cls(
            users=users,
            groups={group.name: group.okta_id for group in okta.list_groups()},
            user_groups={
                user.okta_id: {group.name for group in okta.list_user_groups(user.okta_id)}
                for user in users
                if user.jml_id
            },
            teams=teams,
            team_members={
                team: {username.lower() for username in github.list_team_members(team)}
                for team in _managed_teams(files.teams)
                if team in teams
            },
            org_members={username.lower() for username in github.list_members()},
            invitations={
                username.lower(): teams for username, teams in github.list_invitations().items()
            },
        )


def plan(
    files: Files,
    okta: OktaDirectory,
    github: GithubOrg,
    *,
    today: date,
    prune: bool = False,
    base: Files | None = None,
) -> Plan:
    live = Live.read(files, okta, github)
    planned = _Planner(files, live, today, prune)
    drift: frozenset[Change] = frozenset()
    if base is not None:
        # Read live state again with the base's groups and teams, which may differ.
        base_live = Live.read(base, okta, github) if base.teams != files.teams else live
        drift = frozenset(planned.changes) & frozenset(_Planner(base, base_live, today).changes)
    return Plan(
        changes=tuple(sorted(planned.changes, key=Change.sort_key)),
        drift=drift,
        unmanaged=tuple(planned.unmanaged),
        refused=tuple(planned.refused),
        drift_checked=base is not None,
    )


def _managed_teams(teams: TeamsFile) -> list[str]:
    return sorted({team.github_team for team in teams.teams.values() if team.github_team})


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def ambiguous_jml_id(jml_id: str, users: Iterable[OktaUser]) -> str:
    accounts = ", ".join(f"{user.login} ({user.okta_id})" for user in users)
    return (
        f"{jml_id}: jmlId is set on more than one Okta user ({accounts}), so the kit cannot "
        "tell which is this person and changes nothing for them; clear jmlId on every "
        "account but the right one in Okta"
    )


def login_for(person: Person, company: str) -> str:
    return f"{person.id}@{company}.example"


class _Planner:
    def __init__(self, files: Files, live: Live, today: date, prune: bool = False):
        self.files = files
        self.live = live
        self.today = today
        self.prune = prune
        self.changes: list[Change] = []
        self.unmanaged: list[Unmanaged] = []
        self.refused: list[str] = []
        by_jml_id: dict[str, list[OktaUser]] = {}
        for user in live.users:
            if user.jml_id:
                by_jml_id.setdefault(user.jml_id, []).append(user)
        # A jmlId on more than one account is ambiguous: acting on either could hit the
        # wrong person, so nothing is planned for that id until someone fixes Okta.
        self.ambiguous = {jml_id for jml_id, users in by_jml_id.items() if len(users) > 1}
        for jml_id in sorted(self.ambiguous):
            self.refused.append(ambiguous_jml_id(jml_id, by_jml_id[jml_id]))
        self.users_by_jml_id = {
            jml_id: users[0] for jml_id, users in by_jml_id.items() if jml_id not in self.ambiguous
        }

        self._plan_groups_and_teams()
        for person in files.people.people:
            if person.id in self.ambiguous:
                continue
            self._plan_okta(person)
            if person.github:
                self._plan_github(person, person.github)
        self._plan_unlisted_users()
        self._plan_unlisted_github()

    def _plan_groups_and_teams(self) -> None:
        for group in _unique(self.files.teams.groups):
            if group not in self.live.groups:
                self.changes.append(CreateGroup(group))
        for name in sorted(set(self.live.groups) - set(self.files.teams.groups)):
            self.unmanaged.append(Unmanaged("okta", "group", name, "not in teams.yaml"))
        for team in _managed_teams(self.files.teams):
            if team not in self.live.teams:
                self.changes.append(CreateTeam(team))
        for team in sorted(self.live.teams - set(_managed_teams(self.files.teams))):
            self.unmanaged.append(Unmanaged("github", "team", team, "not in teams.yaml"))

    def _gone(self, person: Person) -> bool:
        """A leaver whose end date has arrived."""
        return person.end is not None and person.end <= self.today

    def _groups_of(self, user: OktaUser) -> list[str]:
        """The user's managed groups."""
        joined = self.live.user_groups.get(user.okta_id, set())
        return [name for name in self.files.teams.groups if name in joined]

    def _deactivate(self, jml_id: str, user: OktaUser) -> None:
        """Remove the user from every group, managed or not, then deactivate them."""
        for group in sorted(self.live.user_groups.get(user.okta_id, set())):
            self.changes.append(RemoveFromGroup(jml_id, group))
        self.changes.append(DeactivateUser(jml_id))

    def _plan_okta(self, person: Person) -> None:
        user = self.users_by_jml_id.get(person.id)
        leaving = person.status == "leaver"
        if self._gone(person):
            if user and user.status != UserStatus.DEPROVISIONED:
                self._deactivate(person.id, user)
            return

        wanted = _unique([*self.files.teams.teams[person.team].okta_groups, *person.extra_groups])
        if user is None:
            if leaving:
                return  # never create someone who is already on their way out
            login = login_for(person, self.files.people.company)
            if any(other.login.lower() == login.lower() for other in self.live.users):
                self.refused.append(
                    f"{person.id}: Okta already has a user with login {login} but without "
                    "jmlId, so the kit will not create or adopt it; set its jmlId to "
                    f"{person.id} in Okta to adopt it"
                )
                return
            self.changes.append(CreateUser(person.id, login, person.name, person.email))
            self.changes.append(ActivateUser(person.id))
            self.changes.extend(AddToGroup(person.id, group) for group in wanted)
            return

        match user.status, leaving:
            case UserStatus.DEPROVISIONED, False:
                self.refused.append(
                    f"{person.id}: Okta user is DEPROVISIONED but people.yaml says active; "
                    "the kit does not reactivate deprovisioned users"
                )
                return
            case UserStatus.DEPROVISIONED, True:
                return
            case UserStatus.STAGED, False:
                self.changes.append(ActivateUser(person.id))
            case UserStatus.SUSPENDED, False:
                self.changes.append(UnsuspendUser(person.id))
            case UserStatus.ACTIVE, True:
                self.changes.append(SuspendUser(person.id, str(person.end)))

        for field in ("name", "email"):
            old, new = getattr(user, field), getattr(person, field)
            if old != new:
                self.changes.append(UpdateProfile(person.id, field, old, new))
        current = self._groups_of(user)
        self.changes.extend(AddToGroup(person.id, g) for g in wanted if g not in current)
        self.changes.extend(RemoveFromGroup(person.id, g) for g in current if g not in wanted)

    def _plan_github(self, person: Person, username: str) -> None:
        key = username.lower()
        member = key in self.live.org_members
        invited = self.live.invitations.get(key)
        if self._gone(person):
            if member or invited is not None:
                self.changes.append(RemoveFromOrg(person.id, username))
            return

        wanted = self.files.teams.teams[person.team].github_team
        if member or invited is not None:
            current = [
                team
                for team in _managed_teams(self.files.teams)
                if key in self.live.team_members.get(team, set()) or team in (invited or set())
            ]
            if wanted and wanted not in current:
                self.changes.append(AddToTeam(person.id, username, wanted))
            self.changes.extend(
                RemoveFromTeam(person.id, username, team) for team in current if team != wanted
            )
        elif person.status == "active":
            teams = (wanted,) if wanted else ()
            self.changes.append(InviteToOrg(person.id, username, teams))

    def _plan_unlisted_users(self) -> None:
        listed = {person.id for person in self.files.people.people}
        archived = {entry.id for entry in self.files.archive.archived}
        for user in sorted(self.live.users, key=lambda user: user.login):
            if user.jml_id is None:
                self.unmanaged.append(
                    Unmanaged("okta", "user", user.login, "no jmlId, never touched")
                )
            elif user.jml_id in listed or user.jml_id in self.ambiguous:
                continue
            elif user.jml_id in archived:
                if user.status == UserStatus.DEPROVISIONED:
                    self.changes.append(DeleteUser(user.jml_id))
                else:
                    self.refused.append(
                        f"{user.jml_id}: removed from people.yaml and archived, but the Okta "
                        f"user is {user.status}, not DEPROVISIONED, so it cannot be deleted "
                        "(Okta would deactivate it instead); put the block back with status: "
                        "leaver and an end date, apply, and then remove it"
                    )
            elif user.status == UserStatus.DEPROVISIONED:
                self.unmanaged.append(
                    Unmanaged("okta", "user", user.login, "created by jml-kit, deprovisioned")
                )
            elif self.prune:
                self._deactivate(user.jml_id, user)
                self.unmanaged.append(
                    Unmanaged("okta", "user", user.login, "created by jml-kit, pruned")
                )
            else:
                self.unmanaged.append(
                    Unmanaged(
                        "okta",
                        "user",
                        user.login,
                        "created by jml-kit but not in people.yaml; --prune deactivates it",
                    )
                )

    def _plan_unlisted_github(self) -> None:
        listed = {person.github.lower() for person in self.files.people.people if person.github}
        for username in sorted(self.live.org_members - listed):
            self.unmanaged.append(Unmanaged("github", "member", username, "not in people.yaml"))
        for username in sorted(set(self.live.invitations) - listed):
            self.unmanaged.append(Unmanaged("github", "invitation", username, "not in people.yaml"))
        for team in _managed_teams(self.files.teams):
            for username in sorted(self.live.team_members.get(team, set()) - listed):
                self.unmanaged.append(
                    Unmanaged("github", "team member", f"{team}/{username}", "not in people.yaml")
                )
