#!/bin/bash
# Installs spork into ~/.spork (or $SPORK_HOME). No admin rights needed.
#   ./install.sh                  install or upgrade
#   ./install.sh --no-modify-path don't touch your shell startup file
#   ./install.sh --link           use this folder as spork itself (for working on
#                                 spork); spork won't update itself
#
# It also works on its own, without a copy of the repo:
#   curl -fsSL https://raw.githubusercontent.com/spork-pm/spork/main/install.sh | bash
#   curl -fsSL …/install.sh | bash -s -- --no-modify-path
#
# spork is fetched from $SPORK_REPO (default: the official repo) into
# $SPORK_HOME/self, so "spork update" can update it later. $SPORK_REPO can also
# be a .tar.gz URL, e.g. an internal mirror of the repo's archive.

# Everything is in a function, so that when this script is piped into bash, bash
# reads all of it before running anything (git or curl could read the rest of the
# script from stdin otherwise).
main() {
set -e
SPORK_HOME=${SPORK_HOME:-$HOME/.spork}
SPORK_REPO=${SPORK_REPO:-https://github.com/spork-pm/spork}
export SPORK_HOME SPORK_REPO

modify_path=1 link=
for a in "$@"; do
  case $a in
    --no-modify-path) modify_path= ;;
    --link) link=1 ;;
    *) echo "unknown option: $a" >&2; exit 1 ;;
  esac
done

# The folder this script is in, if it's a copy of the repo (has spork next to it).
# Piped into bash, the script has no file, so there's no copy to fall back on.
here=
if [ -n "${BASH_SOURCE[0]}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
  [ -f "$here/spork" ] || here=
fi

self=$SPORK_HOME/self
mkdir -p "$SPORK_HOME/bin" "$SPORK_HOME/drawers" "$HOME/Applications"
if [ -n "$link" ]; then
  [ -n "$here" ] || { echo "--link needs a copy of the spork repo: run ./install.sh --link from it" >&2; exit 1; }
  [ "$here" -ef "$self" ] && { echo "--link needs a spork folder outside $self" >&2; exit 1; }
  rm -rf "$self"; ln -s "$here" "$self"
elif [ -z "$here" ]; then
  download_self "$SPORK_HOME/self.new" \
    || { rm -rf "$SPORK_HOME/self.new"; echo "Couldn't download spork from $SPORK_REPO" >&2; exit 1; }
  rm -rf "$self"; mv "$SPORK_HOME/self.new" "$self"
elif ! "$here/spork" _self-install; then
  # Install this copy. Its .spork-source lets "spork update" try again later.
  echo "Couldn't fetch spork from $SPORK_REPO; installing the copy in $here instead."
  cp "$here/spork" "$SPORK_HOME/spork.tmp"   # $here may be $self
  rm -rf "$self"; mkdir -p "$self"
  mv "$SPORK_HOME/spork.tmp" "$self/spork"
  echo "$SPORK_REPO" > "$self/.spork-source"
fi
chmod +x "$self/spork"
ln -sfn "$self/spork" "$SPORK_HOME/bin/spork"
rm -rf "$SPORK_HOME/libexec"   # where older versions of this script put spork

echo "spork installed in $SPORK_HOME"

# The official drawers: main (CLI tools) and apps (GUI apps). A drawer that's a
# plain folder is a copy from older spork versions, so it's replaced. Drawers
# that are links, git clones or downloads are left alone.
for name in main apps; do
  d=$SPORK_HOME/drawers/$name
  if [ -e "$d" ] && { [ -L "$d" ] || [ -d "$d/.git" ] || [ -f "$d/.spork-source" ]; }; then
    continue
  fi
  rm -rf "$d"
  "$SPORK_HOME/bin/spork" drawer add "$name" </dev/null \
    || echo "Couldn't add the '$name' drawer. Check that you can reach its URL, then run: spork drawer add $name"
done

line='eval "$('"$SPORK_HOME"'/bin/spork shellenv)"'
case "$modify_path:${SHELL##*/}" in
  1:zsh)  rc=$HOME/.zshrc ;;
  1:bash) rc=$HOME/.bash_profile ;;
  *)      rc= ;;
esac
if [ -n "$rc" ]; then
  if ! grep -qF "$line" "$rc" 2>/dev/null; then
    printf '\n# spork\n%s\n' "$line" >> "$rc"
    echo "Added spork to PATH in $rc. Open a new terminal, or run:"
    echo "    $line"
  fi
else
  echo "Add this line to your shell startup file to put spork on PATH:"
  echo "    $line"
fi
}

has_git() {
  local g; g=$(command -v git) || return 1
  # /usr/bin/git is only a stub until the Command Line Tools are installed.
  [ "$g" != /usr/bin/git ] || xcode-select -p >/dev/null 2>&1
}

# Download spork from $SPORK_REPO into $1, as "spork _self-install" would: a git
# clone, or else an archive with a .spork-source file so "spork update" works.
download_self() {
  local dest=$1 url p
  rm -rf "$dest"
  case $SPORK_REPO in
    *.tar.gz|*.tgz) url=$SPORK_REPO ;;
    *)
      if has_git; then
        git -c http.proxyAuthMethod=negotiate clone -q --depth 1 "$SPORK_REPO" "$dest" </dev/null || return 1
      else
        case $SPORK_REPO in
          https://github.com/*)
            p=${SPORK_REPO#https://github.com/}; p=${p%.git}; p=${p%/}
            url=https://codeload.github.com/$p/tar.gz/HEAD ;;
          *) echo "git isn't available and $SPORK_REPO isn't a GitHub or .tar.gz URL" >&2; return 1 ;;
        esac
      fi ;;
  esac
  if [ -n "$url" ]; then
    mkdir -p "$dest"
    curl --proxy-negotiate -fsSL "$url" </dev/null | tar -xzf - -C "$dest" --strip-components 1 || return 1
    echo "$SPORK_REPO" > "$dest/.spork-source"
  fi
  [ -f "$dest/spork" ] && bash -n "$dest/spork" || { echo "the downloaded spork looks broken" >&2; return 1; }
}

main "$@"
