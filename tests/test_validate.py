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
from jml.validate import MAX_FILE_BYTES, identity_key, people_ids, validate

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
    "1-parse/fail-anchor-alias": (
        "people.yaml:6: invalid YAML: anchors and aliases are not allowed (column 11)"
    ),
    "1-parse/fail-bad-yaml": (
        "people.yaml:5: invalid YAML: expected <block end>, but found '<block mapping "
        "start>' (column 4)"
    ),
    "1-parse/fail-complex-key": (
        "people.yaml:2: invalid YAML: mapping keys must be plain values (column 3)"
    ),
    "1-parse/fail-duplicate-key": "people.yaml:7: invalid YAML: duplicate key 'team' (column 5)",
    "1-parse/fail-explicit-tag": (
        "people.yaml:4: invalid YAML: explicit tag 'tag:yaml.org,2002:binary' is not "
        "allowed (column 11)"
    ),
    "1-parse/fail-merge-key": (
        "people.yaml:6: invalid YAML: merge keys (<<) are not allowed (column 5)"
    ),
    "1-parse/fail-too-deep": (
        "people.yaml:9: invalid YAML: nesting deeper than 10 levels (column 26)"
    ),
    "1-parse/fail-unknown-key": "people.yaml:9: people[0] (ana.ruiz).extra_group: unknown key",
    "1-parse/fail-unknown-team-key": "teams.yaml:6: teams.engineering.slack_channel: unknown key",
    "2-identity/fail-archived-id-reused": (
        "people.yaml:9: id 'sam.okafor' is archived in people.archive.yaml and cannot be reused"
    ),
    "2-identity/fail-bad-email": (
        "people.yaml:5: people[0] (ana.ruiz).email: 'ana.ruiz.pedalworks.example' is not "
        "a valid email address"
    ),
    "2-identity/fail-bad-github": (
        "people.yaml:9: people[0] (ana.ruiz).github: 'ana--ruiz-' is not a valid GitHub username"
    ),
    "2-identity/fail-bad-id": (
        "people.yaml:3: people[0] (Ana.Ruiz).id: 'Ana.Ruiz' is not a valid id: use 2-39 "
        "characters of lowercase letters, digits, dots and hyphens, starting with a "
        "letter"
    ),
    "2-identity/fail-duplicate-email": (
        "people.yaml:11: email 'Ana.Ruiz@Pedalworks.example' is used by both ana.ruiz and ana.r"
    ),
    "2-identity/fail-duplicate-github": (
        "people.yaml:16: github 'codyjohnsontx' is used by both ana.ruiz and sam.okafor"
    ),
    "2-identity/fail-duplicate-id": (
        "people.yaml:9: id 'ana.ruiz' is used by both ana.ruiz and ana.ruiz"
    ),
    "2-identity/fail-email-consecutive-dots": (
        "people.yaml:5: people[0] (ana.ruiz).email: 'ana..ruiz@pedalworks.example' is not"
        " a valid email address"
    ),
    "2-identity/fail-email-non-ascii": (
        "people.yaml:5: people[0] (ana.ruiz).email: 'café@pedalworks.example' is not a "
        "valid email address"
    ),
    "2-identity/fail-email-off-domain": (
        "people.yaml:5: ana.ruiz: email 'ana.ruiz@gmail.com' is not on the company domain"
        " pedalworks.example"
    ),
    "3-references/fail-undeclared-extra-group": (
        "people.yaml:9: ana.ruiz: extra group 'on-call' is not in the groups list in teams.yaml"
    ),
    "3-references/fail-undeclared-team-group": (
        "teams.yaml:4: teams.engineering.okta_groups: 'okta-admins' is not in the groups list"
    ),
    "3-references/fail-unknown-team": (
        "people.yaml:6: ana.ruiz: team 'enginering' is not defined in teams.yaml (known "
        "teams: design, engineering)"
    ),
    "4-dates/fail-active-with-end": (
        "people.yaml:3: people[0] (sam.okafor): status: active must not have an end date"
    ),
    "4-dates/fail-end-before-start": (
        "people.yaml:3: people[0] (sam.okafor): end 2026-11-14 is before start 2026-11-15"
    ),
    "4-dates/fail-impossible-date": (
        "people.yaml:9: people[0] (sam.okafor).end: '2026-02-30' is not a real date"
    ),
    "4-dates/fail-leaver-without-end": (
        "people.yaml:3: people[0] (sam.okafor): status: leaver requires an end date"
    ),
    "4-dates/fail-missing-start": (
        "people.yaml:3: people[0] (sam.okafor).start: required key is missing"
    ),
    "4-dates/fail-not-iso": (
        "people.yaml:9: people[0] (sam.okafor).end: '11/15/2026' is not an ISO date (YYYY-MM-DD)"
    ),
    "5-seats/fail-over-configured-reserve": (
        "people.yaml:2: 8 active people, but only 7 Okta seats are available (10 limit "
        "minus 3 reserved)"
    ),
    "5-seats/fail-over-limit": (
        "people.yaml:2: 10 active people, but only 9 Okta seats are available (10 limit "
        "minus 1 reserved)"
    ),
    "6-history/fail-archive-without-date": (
        "people.archive.yaml:2: archived[0] (sam.okafor).deactivated_on: required key is missing"
    ),
    "6-history/fail-removed-not-archived": (
        "people.yaml: sam.okafor was removed but has no entry in people.archive.yaml; "
        "offboard with status: leaver and an end date, and remove the block only after "
        "apply has archived them"
    ),
    "7-mac-profiles/fail-missing-profile": (
        "teams.yaml:8: teams.design.mac_profile: mac/profiles/designer.Brewfile does not exist"
    ),
    "7-mac-profiles/fail-path-in-profile": (
        "teams.yaml:8: teams.design.mac_profile: '../../design' is not a valid profile "
        "name: use lowercase letters, digits and hyphens"
    ),
}


def test_fail_cases_match_fixtures():
    assert sorted(FAIL_CASES) == all_cases("fail")


@pytest.mark.parametrize("case", sorted(FAIL_CASES))
def test_fail_cases(case, tmp_path):
    root, base_ids = build_case(case, tmp_path)
    errors = validate(root, base_ids).errors
    assert errors == [FAIL_CASES[case]]


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


def test_missing_archive_file(tmp_path):
    shutil.copytree(FIXTURES / "base", tmp_path, dirs_exist_ok=True)
    (tmp_path / "people.archive.yaml").unlink()
    assert validate(tmp_path).errors == ["people.archive.yaml: file not found"]


def test_repository_sample_data_is_valid():
    result = validate(REPO_ROOT)
    assert result.errors == []
    assert result.people is not None
    handles = {p.github for p in result.people.people if p.github}
    assert handles == {"codyjohnsontx", "pedalworks-bot"}
    assert all(p.email.endswith("@pedalworks.example") for p in result.people.people)


def test_unicode_equivalent_emails_are_rejected(tmp_path):
    # The same visible address written with a precomposed and a combining accent.
    shutil.copytree(FIXTURES / "base", tmp_path, dirs_exist_ok=True)
    people = tmp_path / "people.yaml"
    text = (
        people.read_text().replace("ana.ruiz@", "caf\u00e9@").replace("sam.okafor@", "cafe\u0301@")
    )
    people.write_text(text)
    errors = validate(tmp_path).errors
    assert len(errors) == 2
    assert all("is not a valid email address" in error for error in errors)


def test_identity_key_normalizes_unicode_and_case():
    assert identity_key("caf\u00e9") == identity_key("cafe\u0301")
    assert identity_key("Stra\u00dfe") == identity_key("STRASSE")
    assert identity_key("CodyJohnsonTX") == identity_key("codyjohnsontx")


def test_value_with_trailing_newline_is_rejected(tmp_path):
    shutil.copytree(FIXTURES / "base", tmp_path, dirs_exist_ok=True)
    people = tmp_path / "people.yaml"
    people.write_text(people.read_text().replace("id: ana.ruiz", 'id: "ana.ruiz\\n"'))
    assert validate(tmp_path).errors == [
        "people.yaml:3: people[0] (ana.ruiz\n).id: 'ana.ruiz\\n' is not a valid id: use 2-39 "
        "characters of lowercase letters, digits, dots and hyphens, starting with a letter"
    ]


def test_oversized_file_is_rejected_before_parsing(tmp_path):
    shutil.copytree(FIXTURES / "base", tmp_path, dirs_exist_ok=True)
    teams = tmp_path / "teams.yaml"
    teams.write_text(teams.read_text() + "#" * MAX_FILE_BYTES)
    assert validate(tmp_path).errors == [f"teams.yaml: file is larger than {MAX_FILE_BYTES} bytes"]


def test_non_utf8_file_is_rejected(tmp_path):
    shutil.copytree(FIXTURES / "base", tmp_path, dirs_exist_ok=True)
    (tmp_path / "people.archive.yaml").write_bytes(b"archived: []\n# \xff\n")
    assert validate(tmp_path).errors == ["people.archive.yaml: file is not valid UTF-8"]


# CLI


def test_cli_validate_ok(tmp_path, capsys):
    shutil.copytree(FIXTURES / "base", tmp_path, dirs_exist_ok=True)
    assert main(["validate", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "ok: 2 people (2 active) in 2 teams\n"


def test_cli_validate_reports_errors(tmp_path, capsys):
    root, _ = build_case("3-references/fail-unknown-team", tmp_path)
    assert main(["validate", str(root)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("people.yaml:6: ana.ruiz: team 'enginering' is not defined")
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
