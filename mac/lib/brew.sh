# shellcheck shell=bash
# Homebrew and brew bundle steps. Needs log.sh.

HOMEBREW_INSTALLER=https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh

# Put an installed but not yet loaded Homebrew on PATH. Apple silicon, then Intel.
brew_load() {
  local candidate
  for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$candidate" ]; then
      eval "$("$candidate" shellenv)"
      return 0
    fi
  done
  return 1
}

brew_ensure() {
  step "Homebrew"
  if command -v brew >/dev/null 2>&1 || brew_load; then
    skipped "Homebrew is installed"
    return
  fi
  /bin/bash -c "$(curl -fsSL "$HOMEBREW_INSTALLER")"
  brew_load || die "Homebrew installed but brew was not found"
  changed "installed Homebrew"
}

# yq reads people.yaml for --for. It is in base.Brewfile too; this only bootstraps it.
brew_ensure_yq() {
  if command -v yq >/dev/null 2>&1; then
    return
  fi
  step "yq, to read people.yaml"
  brew install yq
  changed "installed yq"
}

# Casks marked "# ci-skip" in the given Brewfiles: GUI apps a CI runner does not need.
brew_ci_skips() {
  sed -n 's/^[[:space:]]*cask[[:space:]]*"\([^"]*\)".*#[[:space:]]*ci-skip.*/\1/p' "$@" | tr '\n' ' '
}

# On CI, skip the marked casks so the runner tests the logic without installing the apps.
brew_skip_on_ci() {
  if [ "${CI:-}" = true ]; then
    HOMEBREW_BUNDLE_CASK_SKIP="$(brew_ci_skips "$@")"
    export HOMEBREW_BUNDLE_CASK_SKIP
  fi
}

# Install what the Brewfile lists and is missing. Never upgrades what is already there, so
# a second run changes nothing just because a newer version came out.
brew_bundle() {
  local file=$1
  step "brew bundle $(basename "$file")"
  if brew bundle check --no-upgrade --file="$file" >/dev/null 2>&1; then
    skipped "$(basename "$file") is satisfied"
    return
  fi
  brew bundle install --no-upgrade --file="$file"
  changed "installed missing $(basename "$file") entries"
}

# --upgrade: fetch new Homebrew metadata and upgrade what the Brewfiles list.
brew_bundle_upgrade() {
  local before after
  step "brew bundle upgrade $*"
  brew update
  before=$(brew_installed)
  local file
  for file in "$@"; do
    brew bundle install --upgrade --file="$file"
  done
  after=$(brew_installed)
  if [ "$before" = "$after" ]; then
    skipped "everything was up to date"
  else
    changed "upgraded Brewfile entries"
  fi
}

brew_installed() {
  brew list --formula --versions
  brew list --cask --versions
}
