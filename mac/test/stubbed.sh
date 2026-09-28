#!/bin/bash
# Run mac/setup.sh end to end against the fakes in mac/test/stub (brew, defaults, killall,
# sw_vers and uname first on PATH), with a temp HOME and a temp state dir. Nothing on the
# real machine changes, so it is safe to run anywhere:
#
#   mac/test/stubbed.sh

set -euo pipefail

MAC=$(cd "$(dirname "$0")/.." && pwd -P)
STUB="$MAC/test/stub"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
unset CI HOMEBREW_BUNDLE_CASK_SKIP
failures=0
scenario=""
out=""
status=0

fail() {
  printf 'FAIL: %s: %s\n' "$scenario" "$*" >&2
  failures=$((failures + 1))
}

# A new, empty machine for the named scenario.
machine() {
  scenario=$1
  HOME="$work/$scenario/home"
  STUB_STATE="$work/$scenario/state"
  JML_APPDIR="$work/$scenario/Applications"
  STUB_BREW_PREFIX=/opt/homebrew
  export HOME STUB_STATE JML_APPDIR STUB_BREW_PREFIX
  mkdir -p "$HOME" "$STUB_STATE" "$JML_APPDIR"
}

# An app in $JML_APPDIR that Homebrew did not install, at the given version.
app_outside_homebrew() {
  mkdir -p "$JML_APPDIR/$1"
  echo "$2" >"$JML_APPDIR/$1/version"
}

# Run setup.sh, keeping its output in $out and its exit status in $status.
run() {
  status=0
  out=$(PATH="$STUB:$PATH" "$MAC/setup.sh" "$@" 2>&1) || status=$?
}

expect_status() {
  [ "$status" = "$1" ] || fail "setup.sh $2 exited $status, want $1"
}

expect_line() {
  printf '%s\n' "$out" | grep -qxF -- "$1" || fail "no line '$1' in output"
}

# The last line is changed=N skipped=M; $1 is "0" or "some" for the changed count.
expect_changed() {
  local last
  last=$(printf '%s\n' "$out" | tail -n 1)
  case "$1:$last" in
    0:changed=0\ skipped=*) ;;
    some:changed=[1-9]*\ skipped=*) ;;
    *) fail "last line '$last', want $1 changed" ;;
  esac
}

expect_file() {
  [ "$(cat "$1" 2>/dev/null)" = "$2" ] || fail "$1 is not: $2"
}

expect_setup_finished() {
  expect_file "$STUB_STATE/defaults/com.apple.finder ShowPathbar" 'boolean 1'
  [ "$(readlink "$HOME/.config/git/ignore")" = "$MAC/dotfiles/config/git/ignore" ] ||
    fail "dotfiles not linked"
}

apple_silicon="eval \"\$(/opt/homebrew/bin/brew shellenv)\""
intel="eval \"\$(/usr/local/bin/brew shellenv)\""

machine fresh-apple-silicon
run engineering
expect_status 0 "pass one"
expect_changed some
expect_line "    changed: $HOME/.zprofile loads Homebrew"
expect_file "$HOME/.zprofile" "$apple_silicon"
expect_setup_finished
expect_file "$STUB_STATE/killall.log" Finder
run engineering
expect_status 0 "pass two"
expect_changed 0
expect_line "    ok: $HOME/.zprofile loads Homebrew"
expect_file "$HOME/.zprofile" "$apple_silicon"

machine intel-with-zprofile
STUB_BREW_PREFIX=/usr/local
printf 'export EDITOR=vim' >"$HOME/.zprofile"
run design
expect_status 0 "pass one"
expect_file "$HOME/.zprofile" "export EDITOR=vim
$intel"
run design
expect_status 0 "pass two"
expect_changed 0
expect_file "$HOME/.zprofile" "export EDITOR=vim
$intel"

# brew bundle always adopts: a same-version app silently, a different-version one as a failure.
machine apps-outside-homebrew
app_outside_homebrew Slack.app 1.0
app_outside_homebrew "Visual Studio Code.app" 0.9
summary=$(printf '%s\n' "==> left alone, already installed outside Homebrew" \
  "    Slack.app" "    Visual Studio Code.app")
for pass in "one" "two" "upgrade"; do
  case "$pass" in
    upgrade) run --upgrade engineering ;;
    *) run engineering ;;
  esac
  expect_status 0 "pass $pass"
  expect_line "    ok: already installed outside Homebrew: Slack.app"
  expect_line "    ok: already installed outside Homebrew: Visual Studio Code.app"
  [ "$(printf '%s\n' "$out" | tail -n 4 | head -n 3)" = "$summary" ] ||
    fail "pass $pass does not list the apps left alone before its last line"
  expect_setup_finished
  if grep -qE '^cask (slack|visual-studio-code) ' "$STUB_STATE/installed"; then
    fail "pass $pass adopted an app installed outside Homebrew"
  fi
  expect_file "$JML_APPDIR/Slack.app/version" 1.0
  expect_file "$JML_APPDIR/Visual Studio Code.app/version" 0.9
  case "$pass" in
    upgrade) expect_line "==> brew bundle upgrade base.Brewfile engineering.Brewfile" ;;
  esac
  case "$pass" in
    one) expect_changed some ;;
    *) expect_changed 0 ;;
  esac
done

machine other-brew-failure
echo node >"$STUB_STATE/broken"
run engineering
expect_status 1 "with a broken formula"
expect_line "setup.sh: brew bundle install failed for engineering.Brewfile"
[ ! -e "$STUB_STATE/defaults" ] || fail "went on to the defaults step"

machine other-failure-beside-app-outside-homebrew
app_outside_homebrew Slack.app 0.9
echo gh >"$STUB_STATE/broken"
run engineering
expect_status 1 "with a broken formula and an app outside Homebrew"
expect_line "setup.sh: brew bundle install failed for base.Brewfile"
[ ! -e "$STUB_STATE/defaults" ] || fail "went on to the defaults step"

if [ "$failures" -gt 0 ]; then
  echo "stubbed: $failures check(s) failed" >&2
  exit 1
fi
echo "stubbed: every scenario passed"
