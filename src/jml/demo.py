"""The fake organization `jml plan --fake` plans against, so the planner runs with no
credentials.

The fake starts as if apply had already run for the base files and everyone had accepted
their GitHub invitation. On top of that it holds the owner's own super admin user (no
jmlId, so unmanaged) and one hand-made change for the plan to show apart: the first
active person the kit manages is added to a group they lack, an admin group if
one exists.
"""

from dataclasses import replace
from datetime import date

from jml.apply import apply
from jml.fakes import FakeGithubOrg, FakeOktaDirectory
from jml.planner import Files, plan
from jml.ports import UserStatus


def demo_base(files: Files) -> Files:
    """Stand-in base files when none is given: the current file without its newest
    joiner, so the demo plan shows someone being onboarded."""
    active = [person for person in files.people.people if person.status == "active"]
    if not active:
        return files
    joiner = max(active, key=lambda person: person.start)
    people = [person for person in files.people.people if person is not joiner]
    return replace(files, people=files.people.model_copy(update={"people": people}))


def fake_org(base: Files, today: date) -> tuple[FakeOktaDirectory, FakeGithubOrg]:
    okta, github = FakeOktaDirectory(), FakeGithubOrg()
    okta.add_user(f"owner@{base.people.company}.example", "Org Owner (super admin)")
    apply(plan(base, okta, github, today=today), okta, github)
    for username in list(github.invitations):
        github.accept_invitation(username)
    _add_drift(base, okta)
    okta.calls.clear()
    github.calls.clear()
    return okta, github


def _add_drift(base: Files, okta: FakeOktaDirectory) -> None:
    """Add the first active managed user to a declared group they lack, admin groups first."""
    groups = sorted(base.teams.groups, key=lambda group: "admin" not in group)
    users = [user for user in okta.list_users() if user.jml_id and user.status == UserStatus.ACTIVE]
    for group in groups:
        members = okta.members[okta.group_named(group).okta_id]
        for user in users:
            if user.okta_id not in members:
                members.add(user.okta_id)
                return
