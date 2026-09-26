"""The typed changes a plan is made of.

Changes name things in the kit's terms (jml id, group name, team slug, GitHub username),
not by Okta ids, so a plan can be computed, rendered and compared before anything exists.
`ORDER` is the phase apply runs a change in: creates first, then profile and access
changes with additions before removals, and every removal before a user is suspended,
deactivated or deleted.
"""

import re
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class Change:
    ORDER: ClassVar[int]
    SYSTEM: ClassVar[str]
    SYMBOL: ClassVar[str]  # + adds access, ~ changes it, - withdraws it
    OBJECT: ClassVar[str]

    @classmethod
    def kind(cls) -> str:
        return re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()

    def sort_key(self) -> tuple[int, str]:
        return (self.ORDER, self.describe())

    def describe(self) -> str:
        raise NotImplementedError


# 1. Groups and teams the file declares.


@dataclass(frozen=True)
class CreateGroup(Change):
    ORDER, SYSTEM, SYMBOL, OBJECT = 10, "okta", "+", "group"
    group: str

    def describe(self) -> str:
        return f"{self.group}  create"


@dataclass(frozen=True)
class CreateTeam(Change):
    ORDER, SYSTEM, SYMBOL, OBJECT = 11, "github", "+", "team"
    team: str

    def describe(self) -> str:
        return f"{self.team}  create"


# 2. Users: created staged, then activated with no email.


@dataclass(frozen=True)
class CreateUser(Change):
    ORDER, SYSTEM, SYMBOL, OBJECT = 20, "okta", "+", "user"
    person: str
    login: str
    name: str
    email: str

    def describe(self) -> str:
        return f"{self.person}  create staged ({self.name}, {self.email})"


@dataclass(frozen=True)
class ActivateUser(Change):
    ORDER, SYSTEM, SYMBOL, OBJECT = 21, "okta", "+", "user"
    person: str

    def describe(self) -> str:
        return f"{self.person}  activate (no email)"


@dataclass(frozen=True)
class UnsuspendUser(Change):
    ORDER, SYSTEM, SYMBOL, OBJECT = 22, "okta", "+", "user"
    person: str

    def describe(self) -> str:
        return f"{self.person}  unsuspend"


# 3. Profile, by partial update.


@dataclass(frozen=True)
class UpdateProfile(Change):
    ORDER, SYSTEM, SYMBOL, OBJECT = 30, "okta", "~", "profile"
    person: str
    field: str  # name or email
    old: str
    new: str

    def describe(self) -> str:
        return f'{self.person}  {self.field} "{self.old}" -> "{self.new}"'


# 4. Okta groups.


@dataclass(frozen=True)
class AddToGroup(Change):
    ORDER, SYSTEM, SYMBOL, OBJECT = 40, "okta", "+", "group"
    person: str
    group: str

    def describe(self) -> str:
        return f"{self.person} -> {self.group}"


@dataclass(frozen=True)
class RemoveFromGroup(Change):
    ORDER, SYSTEM, SYMBOL, OBJECT = 41, "okta", "-", "group"
    person: str
    group: str

    def describe(self) -> str:
        return f"{self.person} -/-> {self.group}"


# 5. GitHub organization and teams.


@dataclass(frozen=True)
class InviteToOrg(Change):
    ORDER, SYSTEM, SYMBOL, OBJECT = 50, "github", "+", "org"
    person: str
    username: str
    teams: tuple[str, ...]

    def describe(self) -> str:
        into = f" into {', '.join(self.teams)}" if self.teams else ""
        return f"{self.username} ({self.person})  invite{into}"


@dataclass(frozen=True)
class AddToTeam(Change):
    ORDER, SYSTEM, SYMBOL, OBJECT = 51, "github", "+", "team"
    person: str
    username: str
    team: str

    def describe(self) -> str:
        return f"{self.username} ({self.person}) -> {self.team}"


@dataclass(frozen=True)
class RemoveFromTeam(Change):
    ORDER, SYSTEM, SYMBOL, OBJECT = 52, "github", "-", "team"
    person: str
    username: str
    team: str

    def describe(self) -> str:
        return f"{self.username} ({self.person}) -/-> {self.team}"


@dataclass(frozen=True)
class RemoveFromOrg(Change):
    ORDER, SYSTEM, SYMBOL, OBJECT = 53, "github", "-", "org"
    person: str
    username: str

    def describe(self) -> str:
        return f"{self.username} ({self.person})  remove from organization"


# 6-8. Lock, deprovision, delete.


@dataclass(frozen=True)
class SuspendUser(Change):
    ORDER, SYSTEM, SYMBOL, OBJECT = 60, "okta", "-", "user"
    person: str
    end: str

    def describe(self) -> str:
        return f"{self.person}  suspend (leaves {self.end})"


@dataclass(frozen=True)
class DeactivateUser(Change):
    ORDER, SYSTEM, SYMBOL, OBJECT = 70, "okta", "-", "user"
    person: str

    def describe(self) -> str:
        return f"{self.person}  deactivate"


@dataclass(frozen=True)
class DeleteUser(Change):
    ORDER, SYSTEM, SYMBOL, OBJECT = 80, "okta", "-", "user"
    person: str

    def describe(self) -> str:
        return f"{self.person}  delete"
