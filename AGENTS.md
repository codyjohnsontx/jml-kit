# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- jml-kit is a public showcase: joiner-mover-leaver automation for the fictional company Pedalworks (emails on `pedalworks.example`), with people as code for Okta and GitHub plus a one-command Mac setup. See `README.md`.
- Python 3.12, managed with uv. The CLI is the `jml` console script (`src/jml/cli.py`). Project config, lint rules and pytest settings live in `pyproject.toml`; `uv.lock` is committed and CI installs with `uv sync --locked`.
- The uv version is pinned twice and must be bumped together: `tool.uv.required-version` in `pyproject.toml` and the `version` input to `astral-sh/setup-uv` in `validate.yml`. Workflow actions are pinned to full commit SHAs with a version comment.
- The checks CI runs are the steps in `.github/workflows/validate.yml`; run the same `uv run ...` commands locally before pushing.
- `validate.yml` must stay secret-free with `permissions: contents: read`, because it is the only workflow fork PRs run. Anything needing Okta or GitHub credentials goes in a separate workflow.
- The CLI uses stdlib `argparse`. Propose any new dependency before adding it.
- `jml validate` (`src/jml/validate.py`, models in `src/jml/models.py`) owns the people-file rules listed in its module docstring. Each rule has a passing and a failing fixture under `tests/fixtures/cases/<rule>/`; a case holds only the files that differ from `tests/fixtures/base/`. A new rule needs both.
- Sample data is fictional. Only `codyjohnsontx` and `pedalworks-bot` may appear as `github` handles; everyone else is Okta only (a test enforces this).

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
