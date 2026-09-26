"""The planner and apply, against the in-memory fakes."""

from datetime import date

import pytest

from jml.apply import PlanRefused, apply
from jml.changes import (
    ActivateUser,
    AddToGroup,
    AddToTeam,
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
from jml.fakes import FakeGithubOrg, FakeOktaDirectory
from jml.models import ArchiveFile, PeopleFile, TeamsFile
from jml.planner import Files, Plan, Unmanaged, plan
from jml.ports import UserStatus

TODAY = date(2026, 10, 1)

TEAMS = {
    "groups": ["all-staff", "engineering", "design", "github-users", "okta-admins", "oncall"],
    "teams": {
        "engineering": {
            "okta_groups": ["all-staff", "engineering", "github-users"],
            "github_team": "engineering",
            "mac_profile": "engineering",
        },
        "design": {
            "okta_groups": ["all-staff", "design"],
            "github_team": "design",
            "mac_profile": "design",
        },
    },
}


def person(id: str, team: str = "engineering", **fields) -> dict:
    return {
        "id": id,
        "name": id.replace(".", " ").title(),
        "email": f"{id}@pedalworks.example",
        "team": team,
        "status": "active",
        "start": "2025-01-06",
        **fields,
    }


def files(*people: dict, archived: tuple[str, ...] = (), teams: dict = TEAMS) -> Files:
    return Files(
        PeopleFile.model_validate({"company": "pedalworks", "people": list(people)}),
        TeamsFile.model_validate(teams),
        ArchiveFile.model_validate(
            {"archived": [{"id": id, "deactivated_on": "2026-09-01"} for id in archived]}
        ),
    )


ANA = person("ana.ruiz", github="aruiz-demo")
SAM = person("sam.okafor", "design")


class Org:
    """A fake Okta and GitHub, with helpers to plan and apply against them."""

    def __init__(self) -> None:
        self.okta = FakeOktaDirectory()
        self.github = FakeGithubOrg()

    def plan(self, f: Files, **kwargs) -> Plan:
        return plan(f, self.okta, self.github, today=TODAY, **kwargs)

    def apply(self, f: Files, **kwargs) -> Plan:
        result = self.plan(f, **kwargs)
        apply(result, self.okta, self.github)
        return result

    def converge(self, f: Files) -> "Org":
        """Apply the files, accept every GitHub invitation, and forget the calls."""
        self.apply(f)
        for username in list(self.github.invitations):
            self.github.accept_invitation(username)
        self.okta.calls.clear()
        self.github.calls.clear()
        return self

    def user(self, jml_id: str):
        return next(user for user in self.okta.list_users() if user.jml_id == jml_id)

    def groups_of(self, jml_id: str) -> set[str]:
        okta_id = self.user(jml_id).okta_id
        return {
            self.okta.groups[group_id].name
            for group_id, members in self.okta.members.items()
            if okta_id in members
        }


def test_empty_org_creates_groups_and_teams_first():
    result = Org().plan(files(ANA))
    creates = [CreateGroup(g) for g in sorted(TEAMS["groups"])] + [
        CreateTeam("design"),
        CreateTeam("engineering"),
    ]
    assert list(result.changes[: len(creates)]) == creates


def test_joiner():
    org = Org().converge(files(SAM))
    result = org.plan(files(SAM, ANA))
    assert result.changes == (
        CreateUser("ana.ruiz", "ana.ruiz@pedalworks.example", "Ana Ruiz", ANA["email"]),
        ActivateUser("ana.ruiz"),
        AddToGroup("ana.ruiz", "all-staff"),
        AddToGroup("ana.ruiz", "engineering"),
        AddToGroup("ana.ruiz", "github-users"),
        InviteToOrg("ana.ruiz", "aruiz-demo", ("engineering",)),
    )
    apply(result, org.okta, org.github)
    assert org.user("ana.ruiz").status == UserStatus.ACTIVE
    assert org.groups_of("ana.ruiz") == {"Everyone", "all-staff", "engineering", "github-users"}
    assert org.github.invitations == {"aruiz-demo": {"engineering"}}


def test_joiner_extra_groups_are_added_once():
    org = Org().converge(files())
    result = org.plan(files(person("ana.ruiz", extra_groups=["oncall", "all-staff"])))
    added = [c.group for c in result.changes if isinstance(c, AddToGroup)]
    assert added == ["all-staff", "engineering", "github-users", "oncall"]


def test_mover_adds_new_access_before_removing_old():
    org = Org().converge(files(ANA))
    result = org.plan(files({**ANA, "team": "design"}))
    assert result.changes == (
        AddToGroup("ana.ruiz", "design"),
        RemoveFromGroup("ana.ruiz", "engineering"),
        RemoveFromGroup("ana.ruiz", "github-users"),
        AddToTeam("ana.ruiz", "aruiz-demo", "design"),
        RemoveFromTeam("ana.ruiz", "aruiz-demo", "engineering"),
    )


def test_leaver_with_future_end_is_suspended_and_keeps_access():
    org = Org().converge(files(ANA))
    result = org.plan(files({**ANA, "status": "leaver", "end": "2026-11-15"}))
    assert result.changes == (SuspendUser("ana.ruiz", "2026-11-15"),)
    apply(result, org.okta, org.github)
    assert org.user("ana.ruiz").status == UserStatus.SUSPENDED
    assert "engineering" in org.groups_of("ana.ruiz")
    assert org.github.teams["engineering"] == {"aruiz-demo"}


@pytest.mark.parametrize("end", ["2026-09-30", "2026-10-01"])
def test_leaver_on_or_after_end_loses_access_then_is_deactivated(end):
    org = Org().converge(files(ANA, SAM))
    result = org.plan(files({**ANA, "status": "leaver", "end": end}, SAM))
    assert result.changes == (
        RemoveFromGroup("ana.ruiz", "all-staff"),
        RemoveFromGroup("ana.ruiz", "engineering"),
        RemoveFromGroup("ana.ruiz", "github-users"),
        RemoveFromOrg("ana.ruiz", "aruiz-demo"),
        DeactivateUser("ana.ruiz"),
    )
    apply(result, org.okta, org.github)
    assert org.okta.calls[-1] == "deactivate_user ana.ruiz@pedalworks.example"
    assert org.github.calls == ["remove_from_org aruiz-demo"]
    assert org.user("ana.ruiz").status == UserStatus.DEPROVISIONED
    assert org.groups_of("ana.ruiz") == {"Everyone"}
    assert "aruiz-demo" not in org.github.members


def test_leaver_leaves_groups_the_file_does_not_declare():
    org = Org().converge(files(ANA, SAM))
    marketing = org.okta.create_group("marketing")
    org.okta.add_to_group(marketing.okta_id, org.user("ana.ruiz").okta_id)  # by hand, in Okta
    assert org.plan(files(ANA, SAM)).changes == ()

    leaver = files({**ANA, "status": "leaver", "end": "2026-09-30"}, SAM)
    result = org.apply(leaver)
    assert RemoveFromGroup("ana.ruiz", "marketing") in result.changes
    assert result.changes[-1] == DeactivateUser("ana.ruiz")
    assert org.groups_of("ana.ruiz") == {"Everyone"}
    assert org.plan(leaver).empty


def test_leaver_who_was_never_created_is_left_alone():
    result = Org().converge(files()).plan(files({**ANA, "status": "leaver", "end": "2026-11-15"}))
    assert result.changes == ()


def test_leaver_brought_back_is_unsuspended():
    org = Org().converge(files(ANA))
    org.apply(files({**ANA, "status": "leaver", "end": "2026-11-15"}))
    assert org.plan(files(ANA)).changes == (UnsuspendUser("ana.ruiz"),)


def test_staged_user_is_activated():
    org = Org().converge(files())
    org.okta.add_user(
        "ana.ruiz@pedalworks.example", "Ana Ruiz", status=UserStatus.STAGED, jml_id="ana.ruiz"
    )
    changes = org.plan(files(SAM, person("ana.ruiz"))).changes
    assert ActivateUser("ana.ruiz") in changes
    assert not any(isinstance(c, CreateUser) and c.person == "ana.ruiz" for c in changes)


def test_rename_updates_the_same_user():
    org = Org().converge(files(ANA))
    okta_id = org.user("ana.ruiz").okta_id
    renamed = {**ANA, "name": "Ana Ruiz-Diaz", "email": "ana.ruizdiaz@pedalworks.example"}
    result = org.apply(files(renamed))
    assert result.changes == (
        UpdateProfile("ana.ruiz", "email", ANA["email"], renamed["email"]),
        UpdateProfile("ana.ruiz", "name", "Ana Ruiz", "Ana Ruiz-Diaz"),
    )
    user = org.user("ana.ruiz")
    assert (user.okta_id, user.name, user.email) == (okta_id, "Ana Ruiz-Diaz", renamed["email"])
    assert user.login == "ana.ruiz@pedalworks.example"


def test_drift_is_told_apart_from_the_change_under_review():
    org = Org().converge(files(ANA, SAM))
    admins = org.okta.group_named("okta-admins").okta_id
    org.okta.add_to_group(admins, org.user("sam.okafor").okta_id)  # by hand, in Okta

    base = files(ANA, SAM)
    result = org.plan(files({**ANA, "team": "design"}, SAM), base=base)
    assert result.drift_checked
    assert result.drift == {RemoveFromGroup("sam.okafor", "okta-admins")}
    assert AddToGroup("ana.ruiz", "design") in result.changes
    assert RemoveFromGroup("ana.ruiz", "engineering") not in result.drift


def test_a_passed_end_date_is_already_needed_at_base():
    org = Org().converge(files(ANA, SAM))
    leaver = {**ANA, "status": "leaver", "end": "2026-10-01"}
    base = files(leaver, SAM)
    apply(plan(base, org.okta, org.github, today=date(2026, 9, 20)), org.okta, org.github)
    assert org.user("ana.ruiz").status == UserStatus.SUSPENDED

    result = org.plan(files(leaver, {**SAM, "extra_groups": ["oncall"]}), base=base)
    assert set(result.changes) - result.drift == {AddToGroup("sam.okafor", "oncall")}
    assert result.drift == {
        RemoveFromGroup("ana.ruiz", "all-staff"),
        RemoveFromGroup("ana.ruiz", "engineering"),
        RemoveFromGroup("ana.ruiz", "github-users"),
        RemoveFromOrg("ana.ruiz", "aruiz-demo"),
        DeactivateUser("ana.ruiz"),
    }


def test_without_base_every_change_is_listed_as_a_change():
    org = Org().converge(files(ANA))
    org.okta.add_to_group(org.okta.group_named("okta-admins").okta_id, org.user("ana.ruiz").okta_id)
    result = org.plan(files(ANA))
    assert result.changes == (RemoveFromGroup("ana.ruiz", "okta-admins"),)
    assert not result.drift_checked
    assert result.drift == frozenset()


def test_github_drift_is_fixed():
    org = Org().converge(files(ANA))
    org.github.add_to_team("design", "aruiz-demo")
    org.github.remove_from_team("engineering", "aruiz-demo")
    assert org.plan(files(ANA)).changes == (
        AddToTeam("ana.ruiz", "aruiz-demo", "engineering"),
        RemoveFromTeam("ana.ruiz", "aruiz-demo", "design"),
    )


def seed_unmanaged(org: Org) -> None:
    org.okta.add_user("owner@pedalworks.example", "Org Owner")
    org.okta.create_group("marketing")
    org.github.members.add("someone-else")
    org.github.invitations["new-hire"] = set()
    org.github.teams["random"] = {"someone-else"}


def test_unmanaged_accounts_and_groups_are_listed_and_left_alone():
    org = Org().converge(files(ANA))
    seed_unmanaged(org)
    result = org.plan(files(ANA))
    assert result.changes == ()
    assert set(result.unmanaged) == {
        Unmanaged("okta", "group", "Everyone", "not in teams.yaml"),
        Unmanaged("okta", "group", "marketing", "not in teams.yaml"),
        Unmanaged("okta", "user", "owner@pedalworks.example", "no jmlId, never touched"),
        Unmanaged("github", "team", "random", "not in teams.yaml"),
        Unmanaged("github", "member", "someone-else", "not in people.yaml"),
        Unmanaged("github", "invitation", "new-hire", "not in people.yaml"),
    }


def test_unmanaged_member_of_a_managed_group_is_left_alone():
    org = Org().converge(files(ANA))
    owner = org.okta.add_user("owner@pedalworks.example", "Org Owner")
    org.okta.add_to_group(org.okta.group_named("okta-admins").okta_id, owner.okta_id)
    assert org.plan(files(ANA), prune=True).changes == ()


def test_prune_touches_only_what_the_kit_created():
    org = Org().converge(files(ANA, SAM))
    seed_unmanaged(org)
    marketing = org.okta.group_named("marketing").okta_id
    org.okta.add_to_group(marketing, org.user("sam.okafor").okta_id)
    org.github.members.add("org-admin")  # an org admin added to a managed team by hand
    org.github.teams["engineering"].add("org-admin")

    without = org.plan(files(ANA))
    assert without.changes == ()
    assert Unmanaged(
        "okta",
        "user",
        "sam.okafor@pedalworks.example",
        "created by jml-kit but not in people.yaml; --prune deactivates it",
    ) in set(without.unmanaged)

    pruned = org.apply(files(ANA), prune=True)
    assert pruned.changes == (
        RemoveFromGroup("sam.okafor", "all-staff"),
        RemoveFromGroup("sam.okafor", "design"),
        RemoveFromGroup("sam.okafor", "marketing"),
        DeactivateUser("sam.okafor"),
    )
    team_member = Unmanaged("github", "team member", "engineering/org-admin", "not in people.yaml")
    assert team_member in set(pruned.unmanaged)
    assert org.user("sam.okafor").status == UserStatus.DEPROVISIONED
    assert org.groups_of("sam.okafor") == {"Everyone"}
    assert "org-admin" in org.github.teams["engineering"]
    assert org.plan(files(ANA), prune=True).changes == ()


def test_delete_guard_refuses_a_user_that_is_not_deprovisioned():
    org = Org().converge(files(ANA, SAM))
    result = org.plan(files(ANA, archived=("sam.okafor",)))
    assert result.changes == ()
    assert len(result.refused) == 1
    assert "sam.okafor" in result.refused[0] and "not DEPROVISIONED" in result.refused[0]
    with pytest.raises(PlanRefused):
        apply(result, org.okta, org.github)
    assert org.okta.calls == []


def test_delete_after_deactivation():
    org = Org().converge(files(ANA, SAM))
    org.apply(files(ANA, {**SAM, "status": "leaver", "end": "2026-09-30"}))
    result = org.apply(files(ANA, archived=("sam.okafor",)))
    assert result.changes == (DeleteUser("sam.okafor"),)
    assert all(user.jml_id != "sam.okafor" for user in org.okta.list_users())


def test_fake_okta_deactivates_instead_of_deleting_a_live_user():
    okta = FakeOktaDirectory()
    user = okta.add_user("ana.ruiz@pedalworks.example", "Ana Ruiz")
    okta.delete_user(user.okta_id)
    assert okta.users[user.okta_id].status == UserStatus.DEPROVISIONED


def test_active_person_with_deprovisioned_user_is_refused():
    org = Org().converge(files(ANA))
    org.okta.deactivate_user(org.user("ana.ruiz").okta_id)
    result = org.plan(files(ANA))
    assert result.refused and "DEPROVISIONED" in result.refused[0]


def test_login_taken_by_a_user_without_jml_id_is_refused():
    org = Org().converge(files())
    org.okta.add_user("ana.ruiz@pedalworks.example", "Ana Ruiz")
    result = org.plan(files(ANA))
    assert not any(isinstance(c, CreateUser) for c in result.changes)
    assert result.refused and "without jmlId" in result.refused[0]


def test_pending_invitation_counts_as_done():
    org = Org()
    org.apply(files(ANA))
    assert org.github.invitations == {"aruiz-demo": {"engineering"}}
    assert org.plan(files(ANA)).changes == ()


SCENARIOS = {
    "joiners": [files(ANA, SAM)],
    "mover": [files(ANA, SAM), files({**ANA, "team": "design"}, SAM)],
    "rename": [files(ANA), files({**ANA, "name": "Ana R. Ruiz"})],
    "future leaver": [files(ANA), files({**ANA, "status": "leaver", "end": "2026-12-01"})],
    "past leaver": [files(ANA, SAM), files({**ANA, "status": "leaver", "end": "2026-09-01"}, SAM)],
    "delete": [
        files(ANA, SAM),
        files(ANA, {**SAM, "status": "leaver", "end": "2026-09-01"}),
        files(ANA, archived=("sam.okafor",)),
    ],
    "github handle added": [files(SAM), files({**SAM, "github": "sokafor-demo"})],
}


@pytest.mark.parametrize("steps", SCENARIOS.values(), ids=SCENARIOS.keys())
@pytest.mark.parametrize("accept_invitations", [False, True])
def test_apply_then_plan_is_empty(steps, accept_invitations):
    org = Org()
    for step in steps:
        org.apply(step)
        if accept_invitations:
            for username in list(org.github.invitations):
                org.github.accept_invitation(username)
        assert org.plan(step).empty, org.plan(step)
