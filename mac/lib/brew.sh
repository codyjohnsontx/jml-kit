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

# New login shells load Homebrew too, the way the Homebrew installer suggests.
brew_shell_profile() {
  local profile="$HOME/.zprofile" line
  line="eval \"\$($(brew --prefix)/bin/brew shellenv)\""
  step "Homebrew in new shells"
  if [ -f "$profile" ] && grep -qxF "$line" "$profile"; then
    skipped "$profile loads Homebrew"
    return
  fi
  if [ -s "$profile" ] && [ -n "$(tail -c 1 "$profile")" ]; then
    echo >>"$profile"
  fi
  printf '%s\n' "$line" >>"$profile"
  changed "$profile loads Homebrew"
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

# Where casks put their apps. mac/test/stubbed.sh points it at a temp dir.
JML_APPDIR=${JML_APPDIR:-/Applications}

# Apps a cask would install that were already in $JML_APPDIR, installed some other way.
BREW_OUTSIDE_APPS=""

# brew bundle always installs casks with --adopt, which takes over a hand-installed app of
# the same version and fails on any other. So skip, and report, every cask in the Brewfile
# that Homebrew has not installed but whose app is already there.
brew_skip_outside_apps() {
  local file=$1 ours cask app
  ours=" $(brew list --cask --versions | awk '{ print $1 }' | tr '\n' ' ') "
  while read -r cask; do
    case "$ours ${HOMEBREW_BUNDLE_CASK_SKIP:-} " in
      *" $cask "*) continue ;;
    esac
    while IFS= read -r app; do
      if [ -z "$app" ] || [ ! -e "$JML_APPDIR/$app" ]; then
        continue
      fi
      skipped "already installed outside Homebrew: $app"
      BREW_OUTSIDE_APPS="$BREW_OUTSIDE_APPS$app
"
      HOMEBREW_BUNDLE_CASK_SKIP="${HOMEBREW_BUNDLE_CASK_SKIP:-} $cask"
      export HOMEBREW_BUNDLE_CASK_SKIP
    done <<EOF_APPS
$(brew info --cask "$cask" | sed -n 's/ (App)$//p' | sed 's/.* -> //')
EOF_APPS
  done <<EOF_CASKS
$(sed -n 's/^[[:space:]]*cask[[:space:]]*"\([^"]*\)".*/\1/p' "$file")
EOF_CASKS
}

brew_bundle_install() {
  local file=$1
  shift
  brew bundle install "$@" --file="$file" || die "brew bundle install failed for $(basename "$file")"
}

# Install what the Brewfile lists and is missing. Never upgrades what is already there, so
# a second run changes nothing just because a newer version came out.
brew_bundle() {
  local file=$1 before
  step "brew bundle $(basename "$file")"
  brew_skip_outside_apps "$file"
  if brew bundle check --no-upgrade --file="$file" >/dev/null 2>&1; then
    skipped "$(basename "$file") is satisfied"
    return
  fi
  before=$(brew_installed)
  brew_bundle_install "$file" --no-upgrade
  if [ "$(brew_installed)" != "$before" ]; then
    changed "installed missing $(basename "$file") entries"
  fi
}

# --upgrade: fetch new Homebrew metadata and upgrade what the Brewfiles list.
brew_bundle_upgrade() {
  local before after file names=""
  for file in "$@"; do
    names="$names $(basename "$file")"
  done
  step "brew bundle upgrade${names}"
  for file in "$@"; do
    brew_skip_outside_apps "$file"
  done
  brew update
  before=$(brew_installed)
  for file in "$@"; do
    brew_bundle_install "$file" --upgrade
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
