"""Pydantic models for people.yaml, teams.yaml and people.archive.yaml.

The models check the shape of each file on its own. Rules that span records or files
(uniqueness, team and group references, seat count, history, Mac profiles) live in
`jml.validate`.
"""

import re
from datetime import date
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    NonNegativeInt,
    field_validator,
    model_validator,
)

ID_PATTERN = re.compile(r"[a-z][a-z0-9.-]{1,38}")
# Plain ASCII addresses only: dot-separated local part, hostname labels, alphabetic TLD.
EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9_+-]+(?:\.[A-Za-z0-9_+-]+)*"
    r"@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}"
)
# GitHub usernames: letters, digits and single hyphens, no leading or trailing hyphen, 1-39 chars.
GITHUB_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")
PROFILE_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*")
# GitHub team slugs: GitHub lowercases a team name and turns other characters into hyphens.
TEAM_SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
ISO_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _iso_date(value: object) -> date:
    if isinstance(value, str) and ISO_DATE_PATTERN.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{value!r} is not a real date") from exc
    raise ValueError(f"{value!r} is not an ISO date (YYYY-MM-DD)")


IsoDate = Annotated[date, BeforeValidator(_iso_date)]


def _github_username(value: str) -> str:
    if not GITHUB_PATTERN.fullmatch(value):
        raise ValueError(f"{value!r} is not a valid GitHub username")
    return value


GithubUsername = Annotated[str, AfterValidator(_github_username)]
NonEmptyStr = Annotated[str, Field(min_length=1)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Person(_Model):
    id: str
    name: NonEmptyStr
    email: str
    team: str
    status: Literal["active", "leaver"]
    start: IsoDate
    end: IsoDate | None = None
    github: GithubUsername | None = None
    extra_groups: list[NonEmptyStr] = []

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if not ID_PATTERN.fullmatch(value):
            raise ValueError(
                f"{value!r} is not a valid id: use 2-39 characters of lowercase letters, "
                "digits, dots and hyphens, starting with a letter"
            )
        return value

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str) -> str:
        if not EMAIL_PATTERN.fullmatch(value):
            raise ValueError(f"{value!r} is not a valid email address")
        return value

    @model_validator(mode="after")
    def _check_dates(self) -> "Person":
        if self.status == "leaver" and self.end is None:
            raise ValueError("status: leaver requires an end date")
        if self.status == "active" and self.end is not None:
            raise ValueError("status: active must not have an end date")
        if self.end and self.end < self.start:
            raise ValueError(f"end {self.end} is before start {self.start}")
        return self


class Seats(_Model):
    """Seats held back from the Okta limit, such as the owner's admin user."""

    reserved: NonNegativeInt = 1


class PeopleFile(_Model):
    company: NonEmptyStr
    seats: Seats = Seats()
    people: list[Person]


class Team(_Model):
    okta_groups: list[NonEmptyStr]
    github_team: NonEmptyStr | None = None
    mac_profile: str

    @field_validator("github_team")
    @classmethod
    def _check_github_team(cls, value: str | None) -> str | None:
        if value is not None and not TEAM_SLUG_PATTERN.fullmatch(value):
            raise ValueError(
                f"{value!r} is not a GitHub team slug: use lowercase letters, digits and "
                "single hyphens, as in the team's URL"
            )
        return value

    @field_validator("mac_profile")
    @classmethod
    def _check_profile(cls, value: str) -> str:
        if not PROFILE_PATTERN.fullmatch(value):
            raise ValueError(
                f"{value!r} is not a valid profile name: use lowercase letters, digits and hyphens"
            )
        return value


class TeamsFile(_Model):
    groups: list[NonEmptyStr]
    teams: dict[str, Team]


class ArchivedPerson(_Model):
    id: str
    deactivated_on: IsoDate
    github: GithubUsername | None = None


class ArchiveFile(_Model):
    archived: list[ArchivedPerson]
