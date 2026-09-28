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
- [`people.archive.yaml`](people.archive.yaml) records everyone who has been deactivated, with their GitHub username if they had one. A person's block can leave `people.yaml` only once they are listed there.

Only two people have a GitHub username: the owner's own account and one machine account. GitHub allows each real person one free account, so the other fictional people are Okta only. That is deliberate, not a gap.

`jml validate` checks the files on every pull request, with no credentials:

1. The YAML parses, with no duplicate or unknown keys, so a typo such as `team_:` fails instead of silently doing nothing. Only plain YAML is accepted: anchors, aliases, explicit tags and merge keys are refused, so every value reads exactly as it appears in the diff, and file size and nesting depth are capped.
2. Ids, emails and GitHub usernames are well formed and unique, with emails and GitHub usernames compared case-insensitively. Emails are plain ASCII addresses. Emails are on the company domain (`<company>.example`), and an archived id is never reused by an active person.
3. Every person's team exists, and every Okta group is in the declared list, so a misspelled group cannot create a stray group in Okta. No group is declared twice (names are compared ignoring case) or is Okta's built-in Everyone group, and each `github_team` is a GitHub team slug, as in the team's URL.
4. A leaver has an end date, an active person does not, and no end date is before its start date.
5. Active people fit in Okta's free plan: 10 users, minus 1 reserved for the owner's admin user (the reserve is configurable under `seats.reserved` in `people.yaml`).
6. Anyone removed from `people.yaml` since the base commit is in `people.archive.yaml` (`jml validate --base <rev>`), so nobody vanishes from the audit trail.
7. Every team's Mac profile has a `mac/profiles/<name>.Brewfile`.

Every problem is reported at once, as `file:line: message` (or `file: message` when there is no single line to change, such as a removed person), naming the person or team it concerns.

## Plan and apply

`jml plan` reads the files, reads live state from Okta and GitHub, and prints the changes that would make them match. Apply runs the same plan and makes those changes, so planning again right after apply shows nothing to do. The plan is a list of typed changes, rendered as Markdown for the PR comment or as JSON.

- Changes run in a fixed order: create groups and teams, create and activate users (with no activation email), update profiles, add access, then withdraw it. A mover joins the new team's groups before leaving the old ones. A suspended person set back to active is unsuspended last, once stale access is gone.
- A person's Okta user is found by its `jmlId` attribute, so changing a name or email updates the same user. If more than one Okta user carries the same `jmlId`, the plan refuses to touch any of them and names every account, and apply checks again before making any change.
- A leaver whose end date is still ahead is suspended and keeps their groups, in case the date moves. On the end date they are removed from GitHub and from every Okta group they belong to, declared in `teams.yaml` or not, then deactivated.
- A deactivated person is deleted only after their block leaves `people.yaml` and they are in `people.archive.yaml`. Okta turns a delete of a user who is not deactivated into a deactivation, so the plan refuses it instead.
- Given the base revision (`--base`), changes the files at that revision need too are listed apart from the change under review, as already needed before this change (`"drift": true` in JSON). The plan cannot tell why: someone changed Okta or GitHub outside this repository, an end date has passed, or an apply has not run yet. Apply makes them match either way. If the files at that revision are not valid, the plan says so and lists everything under Changes.
- Accounts and groups the file does not mention are listed as unmanaged and left alone, such as the owner's super admin user and Okta's Everyone group. `--prune` deactivates only users the kit created (they carry `jmlId`). GitHub accounts carry no `jmlId`, so `--prune` removes a member of the kit's GitHub teams only when the username belongs to someone in `people.archive.yaml`. Any other member who is not in `people.yaml`, such as an org admin added by hand, is listed as unmanaged and never removed.

### Try it

No credentials needed: `--fake` plans against an in-memory Okta and GitHub. The fake starts as if the file had been applied before its newest joiner was added, with the owner's admin user and one hand-made group membership for the plan to show as already needed.

```sh
uv sync
uv run jml plan --fake
uv run jml plan --fake --format json
```

To see your own edit planned, change `people.yaml` (move someone to another team, or set `status: leaver` with an `end` date) and run `uv run jml plan --fake --base HEAD`. The fake then starts from the committed file.

## Mac setup

One command sets up a Pedalworks laptop for its owner's team:

```sh
mac/setup.sh engineering          # by profile
mac/setup.sh --for priya.natarajan  # by person: their team's mac_profile in teams.yaml
```

- It installs Homebrew if it is missing and has `~/.zprofile` load it in new shells. Then it installs `mac/profiles/base.Brewfile` (git, gh, jq, yq, 1Password CLI, Rectangle, Slack) and the team's Brewfile:
  - engineering: uv, Node.js, Docker Desktop, Visual Studio Code
  - design: Figma, ImageOptim
  - ops: Okta AWS CLI, Terraform (from HashiCorp's tap), Ansible, and uv to run this kit
- An app that is already in `/Applications`, installed without Homebrew, is left alone and listed at the end, and the run goes on. Any other install failure stops it.
- It sets a few macOS defaults, such as showing file extensions and not writing `.DS_Store` files to network shares, and links the files in `mac/dotfiles` into the home folder (a global gitignore). A file already in the way is kept as `<name>.pre-jml`.
- Every step checks before it changes anything, so running it again is safe. The last line reports `changed=N skipped=M`.
- A normal run never upgrades what is already installed. `mac/setup.sh --upgrade <profile>` does.
- It is plain Bash 3.2, the version every Mac ships with. `--for` reads the people file with `yq`, installing it first if needed, and only sets up active people.

The [mac workflow](.github/workflows/mac.yml) proves the script is idempotent on GitHub's `macos-15` and `macos-26` runners with `mac/test/idempotent.sh`: the first pass must change something, the second must change nothing and leave an identical snapshot of the installed packages, defaults and links, and `--for` must pick the same profile. The job summary shows the counts. CI skips the GUI apps marked `# ci-skip` in the Brewfiles, so it tests the logic without installing gigabytes of apps. `mac/test/stubbed.sh` runs the script against a fake `brew` and `defaults` with a temporary home folder, for the cases a runner cannot stage, and is safe to run on any machine. `shellcheck` lints every script.

## Development

Requires [uv](https://docs.astral.sh/uv/) at the exact version pinned by `required-version` in [pyproject.toml](pyproject.toml).

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
