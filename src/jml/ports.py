"""The two ports the planner and apply talk to: an Okta directory and a GitHub organization.

Each port speaks the kit's terms (a person's jml id, a group name, a team slug) and hides
the SDK behind it. The in-memory fakes in `jml.fakes` implement both; the real adapters,
not built yet, will wrap the Okta and GitHub APIs.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class UserStatus(StrEnum):
    """Okta user statuses the kit acts on. Okta has more (RECOVERY, LOCKED_OUT, ...);
    an adapter maps those that still allow sign-in to ACTIVE."""

    STAGED = "STAGED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEPROVISIONED = "DEPROVISIONED"


@dataclass(frozen=True)
class OktaUser:
    okta_id: str
    login: str
    name: str
    email: str
    status: UserStatus
    jml_id: str | None  # the custom profile attribute jmlId; None for users the kit did not create


@dataclass(frozen=True)
class OktaGroup:
    okta_id: str
    name: str


class OktaDirectory(Protocol):
    def list_users(self) -> list[OktaUser]:
        """Every user, including DEPROVISIONED ones."""
        ...

    def list_groups(self) -> list[OktaGroup]: ...

    def list_user_groups(self, user_id: str) -> list[OktaGroup]:
        """The user's groups, except Okta's built-in Everyone, which nobody can leave."""
        ...

    def create_group(self, name: str) -> OktaGroup: ...

    def create_user(self, jml_id: str, login: str, name: str, email: str) -> OktaUser:
        """Create a STAGED user; activation is a separate call."""
        ...

    def activate_user(self, user_id: str) -> None:
        """Activate without sending the activation email."""
        ...

    def update_profile(self, user_id: str, *, name: str | None, email: str | None) -> None:
        """Partial update: only the fields given change."""
        ...

    def add_to_group(self, group_id: str, user_id: str) -> None: ...

    def remove_from_group(self, group_id: str, user_id: str) -> None: ...

    def suspend_user(self, user_id: str) -> None: ...

    def unsuspend_user(self, user_id: str) -> None: ...

    def deactivate_user(self, user_id: str) -> None: ...

    def delete_user(self, user_id: str) -> None:
        """Delete a DEPROVISIONED user. Okta deactivates anyone else instead."""
        ...


class GithubOrg(Protocol):
    def list_teams(self) -> set[str]:
        """Team slugs."""
        ...

    def list_members(self) -> set[str]:
        """Usernames of organization members."""
        ...

    def list_invitations(self) -> dict[str, set[str]]:
        """Pending invitations: username to the team slugs the invitation adds them to."""
        ...

    def list_team_members(self, team: str) -> set[str]: ...

    def create_team(self, team: str) -> None: ...

    def invite_to_org(self, username: str, teams: list[str]) -> None: ...

    def add_to_team(self, team: str, username: str) -> None: ...

    def remove_from_team(self, team: str, username: str) -> None: ...

    def remove_from_org(self, username: str) -> None:
        """Remove a member from the organization and every team, or cancel their invitation."""
        ...
