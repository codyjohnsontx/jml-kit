#!/bin/bash
# Prove mac/setup.sh is idempotent: the first pass changes something, the second pass
# changes nothing and leaves the managed state exactly as the first pass left it.
#
#   mac/test/idempotent.sh <profile> [<person id>]
#
# With a person id, a third pass runs `setup.sh --for <id>`, which must pick the same
# profile and change nothing. Writes a table to $GITHUB_STEP_SUMMARY when it is set.

set -euo pipefail

profile=${1:?usage: mac/test/idempotent.sh <profile> [<person id>]}
person=${2:-}

MAC=$(cd "$(dirname "$0")/.." && pwd -P)
# shellcheck source=SCRIPTDIR/../lib/log.sh
. "$MAC/lib/log.sh"
# shellcheck source=SCRIPTDIR/../lib/brew.sh
. "$MAC/lib/brew.sh"
# shellcheck source=SCRIPTDIR/../lib/defaults.sh
. "$MAC/lib/defaults.sh"
# shellcheck source=SCRIPTDIR/../lib/dotfiles.sh
. "$MAC/lib/dotfiles.sh"

base="$MAC/profiles/base.Brewfile"
team="$MAC/profiles/$profile.Brewfile"
work=$(mktemp -d)
summary=${GITHUB_STEP_SUMMARY:-/dev/null}
failures=0

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  failures=$((failures + 1))
}

# Run setup.sh, keep its log, and print the changed= and skipped= numbers.
pass() {
  local name=$1 status=0
  shift
  "$MAC/setup.sh" "$@" 2>&1 | tee "$work/$name.log" >&2 || status=$?
  sed -n 's/^changed=\([0-9]*\) skipped=\([0-9]*\)$/\1 \2/p' "$work/$name.log" | tail -n 1
  return "$status"
}

# Everything setup.sh manages, as it is now.
snapshot() {
  {
    echo "## brew bundle list"
    brew bundle list --all --file="$base"
    brew bundle list --all --file="$team"
    echo "## brew list --versions"
    brew_installed
    echo "## defaults"
    defaults_snapshot
    echo "## dotfiles"
    dotfiles_snapshot
    echo "## ~/.zprofile"
    cat "$HOME/.zprofile" 2>/dev/null || true
  } >"$1"
}

row() { printf '| %s | %s | %s | %s |\n' "$@" >>"$summary"; }

{
  echo "## mac/setup.sh idempotence: $profile on $(sw_vers -productName) $(sw_vers -productVersion) $(uname -m)"
  echo
  echo "| Pass | changed | skipped | Expected |"
  echo "|---|---|---|---|"
} >>"$summary"

out=$(pass pass1 "$profile") || fail "pass one exited with an error"
read -r changed1 skipped1 <<<"$out"
row "1: setup.sh $profile" "$changed1" "$skipped1" "changed > 0"
[ "${changed1:-0}" -gt 0 ] || fail "pass one changed nothing"
snapshot "$work/snapshot1"

out=$(pass pass2 "$profile") || fail "pass two exited with an error"
read -r changed2 skipped2 <<<"$out"
row "2: setup.sh $profile" "$changed2" "$skipped2" "changed = 0"
[ "${changed2:-}" = 0 ] || fail "pass two changed $changed2 things"
snapshot "$work/snapshot2"

brew_skip_on_ci "$base" "$team"
for file in "$base" "$team"; do
  brew bundle check --no-upgrade --file="$file" || fail "brew bundle check $(basename "$file")"
done

if diff -u "$work/snapshot1" "$work/snapshot2" >"$work/snapshot.diff"; then
  snapshot_result="empty"
else
  snapshot_result="NOT empty"
  fail "the snapshots differ"
  cat "$work/snapshot.diff" >&2
fi

if [ -n "$person" ]; then
  out=$(pass pass3 --for "$person") || fail "pass three exited with an error"
  read -r changed3 skipped3 <<<"$out"
  row "3: setup.sh --for $person" "$changed3" "$skipped3" "profile $profile, changed = 0"
  [ "${changed3:-}" = 0 ] || fail "pass three changed $changed3 things"
  grep -qx "==> profile for $person: $profile" "$work/pass3.log" ||
    fail "--for $person did not pick profile $profile"
fi

{
  echo
  echo "Snapshot diff between pass one and pass two: **$snapshot_result**"
  echo
  echo "<details><summary>Snapshot after pass two</summary>"
  echo
  echo '```'
  cat "$work/snapshot2"
  echo '```'
  echo
  echo "</details>"
  if [ -s "$work/snapshot.diff" ]; then
    echo
    echo '```diff'
    cat "$work/snapshot.diff"
    echo '```'
  fi
} >>"$summary"

if [ "$failures" -gt 0 ]; then
  echo "idempotence: $failures check(s) failed" >&2
  exit 1
fi
echo "idempotence: pass one changed $changed1, pass two changed 0, snapshots match"
