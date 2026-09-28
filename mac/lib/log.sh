# shellcheck shell=bash
# Step output and the changed/skipped counters that setup.sh reports as its last line.

CHANGED=0
SKIPPED=0

step() { printf '==> %s\n' "$*"; }

changed() {
  CHANGED=$((CHANGED + 1))
  printf '    changed: %s\n' "$*"
}

skipped() {
  SKIPPED=$((SKIPPED + 1))
  printf '    ok: %s\n' "$*"
}

die() {
  printf 'setup.sh: %s\n' "$*" >&2
  exit 1
}
