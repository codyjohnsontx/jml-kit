# shellcheck shell=bash
# Symlink mac/dotfiles into the home folder: mac/dotfiles/config/git/ignore becomes
# ~/.config/git/ignore. Needs log.sh and MAC set to the mac/ folder.

dotfiles_list() {
  (cd "$MAC/dotfiles" && find . -type f | sed 's|^\./||' | sort)
}

dotfiles_link() {
  step "dotfiles"
  local rel src target
  for rel in $(dotfiles_list); do
    src="$MAC/dotfiles/$rel"
    target="$HOME/.$rel"
    if [ -L "$target" ] && [ "$(readlink "$target")" = "$src" ]; then
      skipped "$target"
      continue
    fi
    if [ -L "$target" ]; then
      rm "$target" # a link to somewhere else, such as an old checkout, holds nothing to keep
    elif [ -e "$target" ]; then
      [ ! -e "$target.pre-jml" ] || die "$target and $target.pre-jml both exist; move one away"
      mv "$target" "$target.pre-jml"
      printf '    kept the old %s as %s.pre-jml\n' "$target" "$target"
    fi
    mkdir -p "$(dirname "$target")"
    ln -s "$src" "$target"
    changed "$target"
  done
}

dotfiles_snapshot() {
  local rel
  for rel in $(dotfiles_list); do
    printf '%s -> %s\n' "$HOME/.$rel" "$(readlink "$HOME/.$rel" || true)"
  done
}
