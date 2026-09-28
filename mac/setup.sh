#!/bin/bash
# One-command setup for a Pedalworks Mac: Homebrew, the base and team Brewfiles, macOS
# defaults and dotfiles. Every step checks before it changes anything, so running it again
# is safe, and the last line reports changed=N skipped=M.
#
# Plain Bash 3.2, the version macOS ships.

set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: mac/setup.sh [--upgrade] <profile>
       mac/setup.sh [--upgrade] --for <person id>

  <profile>      a Brewfile in mac/profiles, such as engineering, design or ops
  --for <id>     use the mac_profile of that person's team in people.yaml and teams.yaml
  --upgrade      also upgrade what the Brewfiles list (a normal run never upgrades)
USAGE
}

MAC=$(cd "$(dirname "$0")" && pwd -P)
ROOT=$(dirname "$MAC")

# shellcheck source=SCRIPTDIR/lib/log.sh
. "$MAC/lib/log.sh"
# shellcheck source=SCRIPTDIR/lib/brew.sh
. "$MAC/lib/brew.sh"
# shellcheck source=SCRIPTDIR/lib/defaults.sh
. "$MAC/lib/defaults.sh"
# shellcheck source=SCRIPTDIR/lib/dotfiles.sh
. "$MAC/lib/dotfiles.sh"

# The mac_profile for an active person, read from people.yaml and teams.yaml.
profile_for() {
  local id=$1 status team profile
  status=$(ID="$id" yq -e '[.people[] | select(.id == strenv(ID))][0].status' "$ROOT/people.yaml" 2>/dev/null) ||
    die "no one with id $id in people.yaml"
  [ "$status" = active ] || die "$id is a $status, not active"
  team=$(ID="$id" yq -e '[.people[] | select(.id == strenv(ID))][0].team' "$ROOT/people.yaml")
  profile=$(TEAM="$team" yq -e '.teams[strenv(TEAM)].mac_profile' "$ROOT/teams.yaml" 2>/dev/null) ||
    die "team $team has no mac_profile in teams.yaml"
  printf '%s' "$profile"
}

main() {
  local profile="" person="" upgrade=0
  while [ $# -gt 0 ]; do
    case "$1" in
      -h | --help)
        usage
        exit 0
        ;;
      --upgrade) upgrade=1 ;;
      --for)
        [ $# -ge 2 ] || die "--for needs a person id"
        person=$2
        shift
        ;;
      -*) die "unknown option $1 (see --help)" ;;
      *)
        [ -z "$profile" ] || die "one profile at a time (see --help)"
        profile=$1
        ;;
    esac
    shift
  done
  if [ -n "$profile" ] && [ -n "$person" ]; then
    die "give a profile or --for, not both"
  fi
  if [ -z "$profile" ] && [ -z "$person" ]; then
    usage >&2
    exit 1
  fi
  [ "$(uname -s)" = Darwin ] || die "this script sets up macOS"

  brew_ensure
  if [ -n "$person" ]; then
    brew_ensure_yq
    profile=$(profile_for "$person")
    step "profile for $person: $profile"
  fi
  case "$profile" in
    "" | -* | *[!a-z0-9-]*) die "'$profile' is not a profile name" ;;
  esac
  local base="$MAC/profiles/base.Brewfile" team="$MAC/profiles/$profile.Brewfile"
  [ -f "$team" ] || die "no profile $profile: $team does not exist"

  set -- "$base"
  [ "$team" = "$base" ] || set -- "$base" "$team"

  brew_skip_on_ci "$@"
  if [ "$upgrade" = 1 ]; then
    brew_bundle_upgrade "$@"
  else
    local file
    for file in "$@"; do
      brew_bundle "$file"
    done
  fi
  defaults_apply
  dotfiles_link

  printf 'changed=%s skipped=%s\n' "$CHANGED" "$SKIPPED"
}

main "$@"
