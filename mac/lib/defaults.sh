# shellcheck shell=bash
# macOS defaults, each read before it is written. Needs log.sh.

# One per line: domain, key, type (bool, int or string) and value. Values have no spaces.
JML_DEFAULTS='NSGlobalDomain AppleShowAllExtensions bool true
NSGlobalDomain NSDocumentSaveNewDocumentsToCloud bool false
com.apple.finder ShowPathbar bool true
com.apple.finder ShowStatusBar bool true
com.apple.finder FXPreferredViewStyle string Nlsv
com.apple.desktopservices DSDontWriteNetworkStores bool true'

# What `defaults read` and `defaults read-type` print for a setting that is already right.
defaults_expected() {
  local type=$1 value=$2
  case "$type:$value" in
    bool:true) printf 'boolean 1' ;;
    bool:false) printf 'boolean 0' ;;
    int:*) printf 'integer %s' "$value" ;;
    string:*) printf 'string %s' "$value" ;;
    *) die "unknown defaults type $type" ;;
  esac
}

defaults_current() {
  local domain=$1 key=$2 type value
  type=$(defaults read-type "$domain" "$key" 2>/dev/null) || return 0
  value=$(defaults read "$domain" "$key")
  printf '%s %s' "${type#Type is }" "$value"
}

defaults_apply() {
  step "macOS defaults"
  local domain key type value any_changed=0
  while read -r domain key type value; do
    if [ "$(defaults_current "$domain" "$key")" = "$(defaults_expected "$type" "$value")" ]; then
      skipped "$domain $key"
      continue
    fi
    defaults write "$domain" "$key" "-$type" "$value"
    changed "$domain $key = $value"
    any_changed=1
  done <<EOF_DEFAULTS
$JML_DEFAULTS
EOF_DEFAULTS
  if [ "$any_changed" = 1 ]; then
    killall Finder >/dev/null 2>&1 || true
  fi
}

# Every setting this script manages, as it is now.
defaults_snapshot() {
  local domain key type value
  while read -r domain key type value; do
    printf '%s %s = %s\n' "$domain" "$key" "$(defaults_current "$domain" "$key")"
  done <<EOF_DEFAULTS
$JML_DEFAULTS
EOF_DEFAULTS
}
