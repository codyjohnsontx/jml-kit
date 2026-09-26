"""Execute a plan's changes against the ports, in plan order."""

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
from jml.planner import Plan, ambiguous_jml_id
from jml.ports import GithubOrg, OktaDirectory, OktaUser


class PlanRefused(Exception):
    """The plan holds changes the kit refuses to make, so nothing was applied."""


def apply(plan: Plan, okta: OktaDirectory, github: GithubOrg) -> None:
    if plan.refused:
        raise PlanRefused("\n".join(plan.refused))
    # Look users up by jmlId once, and remember users created during this run, because
    # Okta search is eventually consistent and may not find them yet.
    by_jml_id: dict[str, list[OktaUser]] = {}
    for user in okta.list_users():
        if user.jml_id:
            by_jml_id.setdefault(user.jml_id, []).append(user)
    # Check again here, so a stale or hand-built plan cannot act on an ambiguous id.
    ambiguous = [
        ambiguous_jml_id(jml_id, found) for jml_id, found in by_jml_id.items() if len(found) > 1
    ]
    if ambiguous:
        raise PlanRefused("\n".join(ambiguous))
    users = {jml_id: found[0].okta_id for jml_id, found in by_jml_id.items()}
    groups = {group.name: group.okta_id for group in okta.list_groups()}
    for change in plan.changes:
        _execute(change, okta, github, users, groups)


def _execute(
    change: Change,
    okta: OktaDirectory,
    github: GithubOrg,
    users: dict[str, str],
    groups: dict[str, str],
) -> None:
    match change:
        case CreateGroup(group=group):
            groups[group] = okta.create_group(group).okta_id
        case CreateTeam(team=team):
            github.create_team(team)
        case CreateUser(person=person, login=login, name=name, email=email):
            users[person] = okta.create_user(person, login, name, email).okta_id
        case ActivateUser(person=person):
            okta.activate_user(users[person])
        case UnsuspendUser(person=person):
            okta.unsuspend_user(users[person])
        case UpdateProfile(person=person, field="name", new=new):
            okta.update_profile(users[person], name=new, email=None)
        case UpdateProfile(person=person, field="email", new=new):
            okta.update_profile(users[person], name=None, email=new)
        case AddToGroup(person=person, group=group):
            okta.add_to_group(groups[group], users[person])
        case RemoveFromGroup(person=person, group=group):
            okta.remove_from_group(groups[group], users[person])
        case InviteToOrg(username=username, teams=teams):
            github.invite_to_org(username, list(teams))
        case AddToTeam(username=username, team=team):
            github.add_to_team(team, username)
        case RemoveFromTeam(username=username, team=team):
            github.remove_from_team(team, username)
        case RemoveFromOrg(username=username):
            github.remove_from_org(username)
        case SuspendUser(person=person):
            okta.suspend_user(users[person])
        case DeactivateUser(person=person):
            okta.deactivate_user(users[person])
        case DeleteUser(person=person):
            okta.delete_user(users[person])
        case _:
            raise TypeError(f"no executor for {type(change).__name__}")
