"""In-memory Okta and GitHub for tests and `jml plan --fake`.

The fakes keep the API rules the kit depends on: lifecycle calls only work from the right
status, a delete on a user who is not DEPROVISIONED deactivates instead, every user joins
Okta's built-in Everyone group, and adding a non-member to a GitHub team sends an
invitation. Every write is appended to `calls`, so tests can check the order.
"""

import re
from dataclasses import replace

from jml.ports import EVERYONE, OktaGroup, OktaUser, UserStatus


class FakeError(Exception):
    """The fake refused a call that the real API would reject."""


class FakeOktaDirectory:
    def __init__(self) -> None:
        self.users: dict[str, OktaUser] = {}
        self.groups: dict[str, OktaGroup] = {}
        self.members: dict[str, set[str]] = {}
        self.calls: list[str] = []
        self._next_id = 0
        self._everyone = self._add_group(EVERYONE)

    def _new_id(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}{self._next_id:04d}"

    def _add_group(self, name: str) -> OktaGroup:
        group = OktaGroup(okta_id=self._new_id("00g"), name=name)
        self.groups[group.okta_id] = group
        self.members[group.okta_id] = set()
        return group

    def _user(self, user_id: str) -> OktaUser:
        if user_id not in self.users:
            raise FakeError(f"no user {user_id}")
        return self.users[user_id]

    def _group(self, group_id: str) -> OktaGroup:
        if group_id not in self.groups:
            raise FakeError(f"no group {group_id}")
        return self.groups[group_id]

    def _set_status(self, user_id: str, allowed: set[UserStatus], status: UserStatus) -> None:
        user = self._user(user_id)
        if user.status not in allowed:
            raise FakeError(f"cannot move {user.login} from {user.status} to {status}")
        self.users[user_id] = replace(user, status=status)

    def add_user(
        self,
        login: str,
        name: str,
        *,
        email: str | None = None,
        status: UserStatus = UserStatus.ACTIVE,
        jml_id: str | None = None,
    ) -> OktaUser:
        """Seed a user directly, as if someone created it in the Admin Console."""
        user = OktaUser(self._new_id("00u"), login, name, email or login, status, jml_id)
        self.users[user.okta_id] = user
        self.members[self._everyone.okta_id].add(user.okta_id)
        return user

    def group_named(self, name: str) -> OktaGroup:
        return next(group for group in self.groups.values() if group.name == name)

    def list_users(self) -> list[OktaUser]:
        return list(self.users.values())

    def list_groups(self) -> list[OktaGroup]:
        return list(self.groups.values())

    def list_user_groups(self, user_id: str) -> list[OktaGroup]:
        self._user(user_id)
        return [
            group
            for group_id, group in self.groups.items()
            if user_id in self.members[group_id] and group_id != self._everyone.okta_id
        ]

    def create_group(self, name: str) -> OktaGroup:
        if any(group.name == name for group in self.groups.values()):
            raise FakeError(f"group {name} already exists")
        self.calls.append(f"create_group {name}")
        return self._add_group(name)

    def create_user(self, jml_id: str, login: str, name: str, email: str) -> OktaUser:
        if any(user.login == login for user in self.users.values()):
            raise FakeError(f"login {login} already exists")
        self.calls.append(f"create_user {jml_id}")
        return self.add_user(login, name, email=email, status=UserStatus.STAGED, jml_id=jml_id)

    def activate_user(self, user_id: str) -> None:
        self.calls.append(f"activate_user {self._user(user_id).login}")
        self._set_status(user_id, {UserStatus.STAGED}, UserStatus.ACTIVE)

    def update_profile(self, user_id: str, *, name: str | None, email: str | None) -> None:
        user = self._user(user_id)
        self.calls.append(f"update_profile {user.login}")
        self.users[user_id] = replace(user, name=name or user.name, email=email or user.email)

    def add_to_group(self, group_id: str, user_id: str) -> None:
        group, user = self._group(group_id), self._user(user_id)
        self.calls.append(f"add_to_group {group.name} {user.login}")
        self.members[group_id].add(user_id)

    def remove_from_group(self, group_id: str, user_id: str) -> None:
        group, user = self._group(group_id), self._user(user_id)
        if group.okta_id == self._everyone.okta_id:
            raise FakeError("nobody can be removed from Everyone")
        self.calls.append(f"remove_from_group {group.name} {user.login}")
        self.members[group_id].discard(user_id)

    def suspend_user(self, user_id: str) -> None:
        self.calls.append(f"suspend_user {self._user(user_id).login}")
        self._set_status(user_id, {UserStatus.ACTIVE}, UserStatus.SUSPENDED)

    def unsuspend_user(self, user_id: str) -> None:
        self.calls.append(f"unsuspend_user {self._user(user_id).login}")
        self._set_status(user_id, {UserStatus.SUSPENDED}, UserStatus.ACTIVE)

    def deactivate_user(self, user_id: str) -> None:
        self.calls.append(f"deactivate_user {self._user(user_id).login}")
        live = {UserStatus.STAGED, UserStatus.ACTIVE, UserStatus.SUSPENDED}
        self._set_status(user_id, live, UserStatus.DEPROVISIONED)

    def delete_user(self, user_id: str) -> None:
        user = self._user(user_id)
        self.calls.append(f"delete_user {user.login}")
        if user.status != UserStatus.DEPROVISIONED:
            # Okta's documented behaviour, and the reason the planner guards deletes.
            self.users[user_id] = replace(user, status=UserStatus.DEPROVISIONED)
            return
        del self.users[user_id]
        for members in self.members.values():
            members.discard(user_id)


def team_slug(name: str) -> str:
    """The slug GitHub gives a team: lowercase, with other characters turned to hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class FakeGithubOrg:
    """GitHub usernames are case-insensitive, so the fake stores and compares them
    lowercased. Teams are addressed by slug, as in the API's URLs."""

    def __init__(self) -> None:
        self.teams: dict[str, set[str]] = {}
        self.members: set[str] = set()
        self.invitations: dict[str, set[str]] = {}
        self.calls: list[str] = []

    def _team(self, team: str) -> set[str]:
        if team not in self.teams:
            raise FakeError(f"no team with slug {team}")
        return self.teams[team]

    def add_member(self, username: str, *teams: str) -> None:
        """Seed an organization member, as if someone added them on github.com."""
        self.members.add(username.lower())
        for team in teams:
            self._team(team).add(username.lower())

    def accept_invitation(self, username: str) -> None:
        """Act as the invitee accepting: they become a member of the org and its teams."""
        key = username.lower()
        for team in self.invitations.pop(key):
            self._team(team).add(key)
        self.members.add(key)

    def list_teams(self) -> set[str]:
        return set(self.teams)

    def list_members(self) -> set[str]:
        return set(self.members)

    def list_invitations(self) -> dict[str, set[str]]:
        return {username: set(teams) for username, teams in self.invitations.items()}

    def list_team_members(self, team: str) -> set[str]:
        return set(self._team(team))

    def create_team(self, team: str) -> None:
        slug = team_slug(team)
        if slug in self.teams:
            raise FakeError(f"team {slug} already exists")
        self.calls.append(f"create_team {team}")
        self.teams[slug] = set()

    def invite_to_org(self, username: str, teams: list[str]) -> None:
        key = username.lower()
        if key in self.members or key in self.invitations:
            raise FakeError(f"{username} is already a member or invited")
        for team in teams:
            self._team(team)
        self.calls.append(f"invite_to_org {username} {','.join(teams)}".rstrip())
        self.invitations[key] = set(teams)

    def add_to_team(self, team: str, username: str) -> None:
        key = username.lower()
        members = self._team(team)
        self.calls.append(f"add_to_team {team} {username}")
        if key in self.members:
            members.add(key)
        else:
            self.invitations.setdefault(key, set()).add(team)

    def remove_from_team(self, team: str, username: str) -> None:
        key = username.lower()
        self.calls.append(f"remove_from_team {team} {username}")
        self._team(team).discard(key)
        if key in self.invitations:
            self.invitations[key].discard(team)

    def remove_from_org(self, username: str) -> None:
        key = username.lower()
        self.calls.append(f"remove_from_org {username}")
        self.members.discard(key)
        self.invitations.pop(key, None)
        for members in self.teams.values():
            members.discard(key)
