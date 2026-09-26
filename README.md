# jml-kit

Joiner-mover-leaver automation for a small company's IT: people as code.

- A people file in this repository lists everyone, their team, and their access.
- A pull request adds, moves, or removes someone. CI posts a dry-run plan of every account change as a PR comment, and merging applies it.
- Accounts are managed in Okta (users, groups, lifecycle, password resets) and GitHub (organization teams).
- Direct commands handle one-off jobs, such as resetting many passwords at once.
- A one-command Mac setup script installs the tools for each team's laptop profile, tested on GitHub's macOS runners.

The demo uses a fictional company.

Work in progress.

## The people file

The demo company is Pedalworks, a fictional bike maker. Its emails are on `pedalworks.example`, a reserved domain that can never deliver mail.

- [`people.yaml`](people.yaml) lists everyone: a stable `id`, name, email, team, `status` (`active` or `leaver`), start and end dates, an optional GitHub username, and any Okta groups beyond their team's defaults.
- [`teams.yaml`](teams.yaml) declares every Okta group the kit may assign, and what each team gets by default: Okta groups, a GitHub team, and a Mac setup profile.
- [`people.archive.yaml`](people.archive.yaml) records everyone who has been deactivated. A person's block can leave `people.yaml` only once they are listed there.

Only two people have a GitHub username: the owner's own account and one machine account. GitHub allows each real person one free account, so the other fictional people are Okta only. That is deliberate, not a gap.

`jml validate` checks the files on every pull request, with no credentials:

1. The YAML parses, with no duplicate or unknown keys, so a typo such as `team_:` fails instead of silently doing nothing.
2. Ids, emails and GitHub usernames are well formed and unique. Emails are on the company domain (`<company>.example`), and an archived id is never reused by an active person.
3. Every person's team exists, and every Okta group is in the declared list, so a misspelled group cannot create a stray group in Okta.
4. A leaver has an end date, an active person does not, and no end date is before its start date.
5. Active people fit in Okta's free plan: 10 users, minus 1 reserved for the owner's admin user (the reserve is configurable under `seats.reserved` in `people.yaml`).
6. Anyone removed from `people.yaml` since the base commit is in `people.archive.yaml` (`jml validate --base <rev>`), so nobody vanishes from the audit trail.
7. Every team's Mac profile has a `mac/profiles/<name>.Brewfile`.

Every problem is reported at once, with the file and person it concerns.

## Plan and apply

`jml plan` reads the files, reads live state from Okta and GitHub, and prints the changes that would make them match. Apply runs the same plan and makes those changes, so planning again right after apply shows nothing to do. The plan is a list of typed changes, rendered as Markdown for the PR comment or as JSON.

- Changes run in a fixed order: create groups and teams, create and activate users (with no activation email), update profiles, add access, then withdraw it. A mover joins the new team's groups before leaving the old ones.
- A person's Okta user is found by its `jmlId` attribute, so changing a name or email updates the same user.
- A leaver whose end date is still ahead is suspended and keeps their groups, in case the date moves. On the end date they are removed from GitHub and every group, then deactivated.
- A deactivated person is deleted only after their block leaves `people.yaml` and they are in `people.archive.yaml`. Okta turns a delete of a user who is not deactivated into a deactivation, so the plan refuses it instead.
- Drift is live state that someone changed by hand. Given the base revision (`--base`), the plan lists it apart from the change under review, and apply puts it back.
- Accounts and groups the file does not mention are listed as unmanaged and left alone, such as the owner's super admin user and Okta's Everyone group. `--prune` deactivates only users the kit created (they carry `jmlId`) and removes unlisted members from the kit's GitHub teams, never from the organization.

### Try it

No credentials needed: `--fake` plans against an in-memory Okta and GitHub. The fake starts as if the file had been applied before its newest joiner was added, with the owner's admin user and one hand-made group membership for the plan to report as drift.

```sh
uv sync
uv run jml plan --fake
uv run jml plan --fake --format json
```

To see your own edit planned, change `people.yaml` (move someone to another team, or set `status: leaver` with an `end` date) and run `uv run jml plan --fake --base HEAD`. The fake then starts from the committed file.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run jml --help
uv run jml validate
uv run pytest
uv run ruff check
uv run ruff format --check
```

## License

MIT. See [LICENSE](LICENSE).
