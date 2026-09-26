# jml-kit

Joiner-mover-leaver automation for a small company's IT: people as code.

- A people file in this repository lists everyone, their team, and their access.
- A pull request adds, moves, or removes someone. CI posts a dry-run plan of every account change as a PR comment, and merging applies it.
- Accounts are managed in Okta (users, groups, lifecycle, password resets) and GitHub (organization teams).
- Direct commands handle one-off jobs, such as resetting many passwords at once.
- A one-command Mac setup script installs the tools for each team's laptop profile, tested on GitHub's macOS runners.

The demo uses a fictional company.

Work in progress.

## Development

Requires [uv](https://docs.astral.sh/uv/) at the exact version pinned by `required-version` in [pyproject.toml](pyproject.toml).

```sh
uv sync
uv run jml --help
uv run pytest
uv run ruff check
uv run ruff format --check
```

## License

MIT. See [LICENSE](LICENSE).
