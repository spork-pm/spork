#!/bin/bash
# Installs spork into ~/.spork (or $SPORK_HOME). No admin rights needed.
#   ./install.sh                  install or upgrade
#   ./install.sh --no-modify-path don't touch your shell startup file
#   ./install.sh --link           use this folder as spork itself (for working on
#                                 spork); spork won't update itself
#
# spork is fetched from $SPORK_REPO (default: the official repo) into
# $SPORK_HOME/self, so "spork update" can update it later.
set -e
here=$(cd "$(dirname "$0")" && pwd)
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

self=$SPORK_HOME/self
mkdir -p "$SPORK_HOME/bin" "$SPORK_HOME/drawers" "$HOME/Applications"
if [ -n "$link" ]; then
  [ "$here" -ef "$self" ] && { echo "--link needs a spork folder outside $self" >&2; exit 1; }
  rm -rf "$self"; ln -s "$here" "$self"
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
  "$SPORK_HOME/bin/spork" drawer add "$name" \
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
