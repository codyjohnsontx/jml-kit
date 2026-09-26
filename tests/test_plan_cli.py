"""`jml plan`, the renderers, and the README's try-it block."""

import json
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from jml import cli
from jml.changes import AddToGroup, CreateUser, RemoveFromGroup
from jml.planner import Plan, Unmanaged
from jml.render import to_json, to_markdown

REPO_ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


def run(args: list[str], capsys) -> tuple[int, str, str]:
    code = cli.main(args)
    out, err = capsys.readouterr()
    return code, out, err


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repository holding the base fixture as its only commit."""
    shutil.copytree(FIXTURES / "base", tmp_path, dirs_exist_ok=True)

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
    return tmp_path


def test_plan_fake_shows_joiner_drift_and_unmanaged(repo, capsys):
    code, out, _ = run(["plan", str(repo), "--fake"], capsys)
    assert code == 0
    assert "### Changes" in out and "create staged" in out
    assert "### Drift (1)" in out
    assert "### Unmanaged" in out and "no jmlId, never touched" in out


def test_plan_fake_json(repo, capsys):
    code, out, _ = run(["plan", str(repo), "--fake", "--format", "json"], capsys)
    assert code == 0
    document = json.loads(out)
    kinds = {change["kind"] for change in document["changes"]}
    assert {"create_user", "activate_user", "add_to_group"} <= kinds
    assert [c["kind"] for c in document["changes"] if c["drift"]] == ["remove_from_group"]
    assert document["refused"] == []


def test_plan_with_base_shows_only_the_edit(repo, capsys):
    people = repo / "people.yaml"
    text = people.read_text()
    assert "team: engineering" in text
    people.write_text(text.replace("team: engineering", "team: design", 1))
    code, out, _ = run(["plan", str(repo), "--fake", "--base", "HEAD", "--format", "json"], capsys)
    assert code == 0
    changes = json.loads(out)["changes"]
    assert {c["kind"] for c in changes if not c["drift"]} == {
        "add_to_group",
        "remove_from_group",
    }
    assert not any(c["kind"] == "create_user" for c in changes)


def test_plan_needs_fake_until_adapters_exist(repo, capsys):
    code, out, err = run(["plan", str(repo)], capsys)
    assert code == 2 and out == ""
    assert "--fake" in err


def test_plan_stops_on_invalid_files(repo, capsys):
    (repo / "teams.yaml").write_text("groups: [\n")
    code, out, err = run(["plan", str(repo), "--fake"], capsys)
    assert code == 1 and out == ""
    assert "teams.yaml: invalid YAML" in err


def test_plan_rejects_an_unknown_base(repo, capsys):
    code, _, err = run(["plan", str(repo), "--fake", "--base", "no-such-rev"], capsys)
    assert code == 2
    assert "not a commit" in err


def test_plan_with_an_unparsable_base_does_not_show_drift_apart(repo, capsys):
    good = (repo / "teams.yaml").read_text()
    (repo / "teams.yaml").write_text("groups: [\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        + ["commit", "-q", "-m", "broken"],
        check=True,
    )
    (repo / "teams.yaml").write_text(good)
    code, out, err = run(["plan", str(repo), "--fake", "--base", "HEAD"], capsys)
    assert code == 0
    assert "do not parse" in err
    assert "### Drift" not in out
    assert "run with `--base` to show it apart" in out


def test_plan_exits_1_when_refused(repo, capsys, monkeypatch):
    # Remove a person and archive them while their fake Okta user is still active.
    people = repo / "people.yaml"
    ids = re.findall(r"- id: (\S+)", people.read_text())
    gone = ids[0]
    kept = re.split(r"\n(?=  - id: )", people.read_text())
    people.write_text("\n".join(block for block in kept if f"- id: {gone}\n" not in block) + "\n")
    (repo / "people.archive.yaml").write_text(
        f"archived:\n  - id: {gone}\n    deactivated_on: 2026-09-01\n"
    )
    code, out, _ = run(["plan", str(repo), "--fake", "--base", "HEAD"], capsys)
    assert code == 1
    assert "### Refused (1)" in out and gone in out


def test_markdown_for_an_empty_plan():
    empty = Plan((), frozenset(), (), (), drift_checked=True)
    assert "No changes." in to_markdown(empty)


def test_markdown_without_base_notes_drift_is_included():
    change = AddToGroup("ana.ruiz", "oncall")
    text = to_markdown(Plan((change,), frozenset(), (), (), drift_checked=False))
    assert "--base" in text
    assert "+ okta group    ana.ruiz -> oncall" in text


def test_markdown_sections_keep_apply_order():
    create = CreateUser("ana.ruiz", "ana.ruiz@p.example", "Ana Ruiz", "ana.ruiz@p.example")
    drift = RemoveFromGroup("sam.okafor", "okta-admins")
    unmanaged = Unmanaged("okta", "group", "Everyone", "not in teams.yaml")
    plan = Plan((create, drift), frozenset({drift}), (unmanaged,), (), drift_checked=True)
    text = to_markdown(plan, "Against a fake.")
    assert text.index("Against a fake.") < text.index("### Changes (1)")
    assert text.index("### Changes (1)") < text.index("### Drift (1)")
    assert "- okta group    sam.okafor -/-> okta-admins" in text
    document = json.loads(to_json(plan))
    assert document["changes"][0] == {
        "kind": "create_user",
        "system": "okta",
        "drift": False,
        "person": "ana.ruiz",
        "login": "ana.ruiz@p.example",
        "name": "Ana Ruiz",
        "email": "ana.ruiz@p.example",
    }
    assert document["unmanaged"] == [
        {"system": "okta", "object": "group", "name": "Everyone", "note": "not in teams.yaml"}
    ]


def readme_try_it_commands() -> list[list[str]]:
    readme = (REPO_ROOT / "README.md").read_text()
    section = readme.split("### Try it", 1)[1]
    block = re.search(r"```sh\n(.*?)```", section, re.DOTALL)
    assert block, "README has no try-it block"
    return [shlex.split(line) for line in block.group(1).splitlines() if line.strip()]


def test_readme_try_it_block_runs(capsys, monkeypatch):
    commands = readme_try_it_commands()
    assert ["uv", "run", "jml", "plan", "--fake"] in commands
    monkeypatch.chdir(REPO_ROOT)
    for command in commands:
        if command[:2] == ["uv", "sync"]:
            continue
        assert command[:3] == ["uv", "run", "jml"], command
        code, out, err = run(command[3:], capsys)
        assert code == 0, (command, err)
        assert out


def test_readme_edit_example_runs(repo, capsys):
    assert "uv run jml plan --fake --base HEAD" in (REPO_ROOT / "README.md").read_text()
    code, out, _ = run(["plan", str(repo), "--fake", "--base", "HEAD"], capsys)
    assert code == 0
    assert "### Changes" not in out  # nothing edited, so only the fake's hand-made drift
    assert "### Drift (1)" in out
