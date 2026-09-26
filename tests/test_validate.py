"""Each validation rule has a passing and a failing fixture under tests/fixtures/cases.

A case directory holds only the files that differ from tests/fixtures/base, which is a
valid people file on its own. A case's base-people.yaml stands in for people.yaml at the
base git revision, for the history check.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from jml.cli import main
from jml.validate import people_ids, validate

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).parent.parent
BASE_PEOPLE = "base-people.yaml"


def build_case(case: str, dest: Path) -> tuple[Path, set[str] | None]:
    shutil.copytree(FIXTURES / "base", dest, dirs_exist_ok=True)
    shutil.copytree(FIXTURES / "cases" / case, dest, dirs_exist_ok=True)
    base_file = dest / BASE_PEOPLE
    if not base_file.exists():
        return dest, None
    base_ids = people_ids(base_file.read_text())
    base_file.unlink()
    return dest, base_ids


def all_cases(kind: str) -> list[str]:
    cases = FIXTURES / "cases"
    return sorted(
        f"{rule.name}/{case.name}"
        for rule in cases.iterdir()
        for case in rule.iterdir()
        if case.name.startswith(kind)
    )


def test_every_rule_has_a_pass_and_a_fail_case():
    rules = sorted(p.name for p in (FIXTURES / "cases").iterdir())
    assert [r.split("-")[0] for r in rules] == ["1", "2", "3", "4", "5", "6", "7"]
    for rule in rules:
        names = [p.name for p in (FIXTURES / "cases" / rule).iterdir()]
        assert "pass" in names, rule
        assert any(n.startswith("fail-") for n in names), rule


def test_base_fixture_is_valid(tmp_path):
    shutil.copytree(FIXTURES / "base", tmp_path, dirs_exist_ok=True)
    assert validate(tmp_path).errors == []


@pytest.mark.parametrize("case", all_cases("pass"))
def test_pass_cases(case, tmp_path):
    root, base_ids = build_case(case, tmp_path)
    assert validate(root, base_ids).errors == []


FAIL_CASES = {
    "1-parse/fail-unknown-key": "people.yaml: people[0] (ana.ruiz).extra_group: unknown key",
    "1-parse/fail-bad-yaml": "people.yaml: invalid YAML: expected <block end>",
    "1-parse/fail-duplicate-key": "people.yaml: invalid YAML: duplicate key 'team' (line 7",
    "1-parse/fail-unknown-team-key": "teams.yaml: teams.engineering.slack_channel: unknown key",
    "2-identity/fail-bad-id": "people.yaml: people[0] (Ana.Ruiz).id: 'Ana.Ruiz' is not a valid id",
    "2-identity/fail-duplicate-id": "people.yaml: id 'ana.ruiz' is used by both ana.ruiz and",
    "2-identity/fail-bad-email": "'ana.ruiz.pedalworks.example' is not a valid email address",
    "2-identity/fail-duplicate-email": (
        "people.yaml: email 'Ana.Ruiz@Pedalworks.example' is used by both ana.ruiz and ana.r"
    ),
    "2-identity/fail-bad-github": "'ana--ruiz-' is not a valid GitHub username",
    "2-identity/fail-duplicate-github": (
        "people.yaml: github 'codyjohnsontx' is used by both ana.ruiz and sam.okafor"
    ),
    "3-references/fail-unknown-team": (
        "people.yaml: ana.ruiz: team 'enginering' is not defined in teams.yaml "
        "(known teams: design, engineering)"
    ),
    "3-references/fail-undeclared-extra-group": (
        "people.yaml: ana.ruiz: extra group 'on-call' is not in the groups list in teams.yaml"
    ),
    "3-references/fail-undeclared-team-group": (
        "teams.yaml: teams.engineering.okta_groups: 'okta-admins' is not in the groups list"
    ),
    "4-dates/fail-leaver-without-end": "(sam.okafor): status: leaver requires an end date",
    "4-dates/fail-active-with-end": "people[0] (sam.okafor): status: active must not have an end",
    "4-dates/fail-end-before-start": "end 2026-11-14 is before start 2026-11-15",
    "4-dates/fail-not-iso": "people[0] (sam.okafor).end: '11/15/2026' is not an ISO date",
    "4-dates/fail-impossible-date": "people[0] (sam.okafor).end: '2026-02-30' is not a real date",
    "5-seats/fail-over-limit": (
        "people.yaml: 10 active people, but only 9 Okta seats are available "
        "(10 limit minus 1 reserved)"
    ),
    "5-seats/fail-over-configured-reserve": "8 active people, but only 7 Okta seats",
    "6-history/fail-removed-not-archived": (
        "people.yaml: sam.okafor was removed but has no entry in people.archive.yaml"
    ),
    "6-history/fail-archive-without-date": (
        "people.archive.yaml: archived[0] (sam.okafor).deactivated_on: required key is missing"
    ),
    "7-mac-profiles/fail-missing-profile": (
        "teams.yaml: teams.design.mac_profile: mac/profiles/designer.Brewfile does not exist"
    ),
    "7-mac-profiles/fail-path-in-profile": "'../../design' is not a valid profile name",
}


def test_fail_cases_match_fixtures():
    assert sorted(FAIL_CASES) == all_cases("fail")


@pytest.mark.parametrize("case", sorted(FAIL_CASES))
def test_fail_cases(case, tmp_path):
    root, base_ids = build_case(case, tmp_path)
    errors = validate(root, base_ids).errors
    assert len(errors) == 1, errors
    assert FAIL_CASES[case] in errors[0]


def test_reports_every_problem_at_once(tmp_path):
    root, _ = build_case("3-references/fail-unknown-team", tmp_path)
    (root / "mac/profiles/design.Brewfile").unlink()
    errors = validate(root).errors
    assert len(errors) == 2
    assert "team 'enginering'" in errors[0]
    assert "design.Brewfile does not exist" in errors[1]


def test_missing_people_file(tmp_path):
    shutil.copytree(FIXTURES / "base", tmp_path, dirs_exist_ok=True)
    (tmp_path / "people.yaml").unlink()
    assert validate(tmp_path).errors == ["people.yaml: file not found"]


def test_archive_file_is_optional(tmp_path):
    shutil.copytree(FIXTURES / "base", tmp_path, dirs_exist_ok=True)
    (tmp_path / "people.archive.yaml").unlink()
    assert validate(tmp_path, base_ids=set()).errors == []


def test_repository_sample_data_is_valid():
    result = validate(REPO_ROOT)
    assert result.errors == []
    assert result.people is not None
    handles = {p.github for p in result.people.people if p.github}
    assert handles == {"codyjohnsontx", "pedalworks-bot"}
    assert all(p.email.endswith("@pedalworks.example") for p in result.people.people)


# CLI


def test_cli_validate_ok(tmp_path, capsys):
    shutil.copytree(FIXTURES / "base", tmp_path, dirs_exist_ok=True)
    assert main(["validate", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "ok: 2 people (2 active) in 2 teams\n"


def test_cli_validate_reports_errors(tmp_path, capsys):
    root, _ = build_case("3-references/fail-unknown-team", tmp_path)
    assert main(["validate", str(root)]) == 1
    err = capsys.readouterr().err
    assert "team 'enginering' is not defined" in err
    assert err.endswith("jml validate: 1 problem(s) found\n")


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t.example", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_cli_validate_base_revision(tmp_path, capsys):
    shutil.copytree(FIXTURES / "base", tmp_path, dirs_exist_ok=True)
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "base")
    people = tmp_path / "people.yaml"
    people.write_text(people.read_text().split("  - id: sam.okafor")[0])

    assert main(["validate", str(tmp_path), "--base", "HEAD"]) == 1
    assert "sam.okafor was removed" in capsys.readouterr().err

    (tmp_path / "people.archive.yaml").write_text(
        "archived:\n  - id: sam.okafor\n    deactivated_on: 2026-11-16\n"
    )
    assert main(["validate", str(tmp_path), "--base", "HEAD"]) == 0


def test_cli_validate_base_without_people_file(tmp_path):
    shutil.copytree(FIXTURES / "base", tmp_path, dirs_exist_ok=True)
    git(tmp_path, "init", "-q")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "empty")
    assert main(["validate", str(tmp_path), "--base", "HEAD"]) == 0


def test_cli_validate_bad_base_revision(tmp_path, capsys):
    shutil.copytree(FIXTURES / "base", tmp_path, dirs_exist_ok=True)
    git(tmp_path, "init", "-q")
    assert main(["validate", str(tmp_path), "--base", "nope"]) == 2
    assert "base revision 'nope' is not a commit" in capsys.readouterr().err
