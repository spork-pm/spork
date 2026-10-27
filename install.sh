#!/bin/bash
# Installs spork into ~/.spork (or $SPORK_HOME). No admin rights needed.
#   ./install.sh                  install or upgrade
#   ./install.sh --no-modify-path don't touch your shell startup file
set -e
here=$(cd "$(dirname "$0")" && pwd)
SPORK_HOME=${SPORK_HOME:-$HOME/.spork}
export SPORK_HOME

mkdir -p "$SPORK_HOME/libexec" "$SPORK_HOME/bin" "$SPORK_HOME/drawers" "$HOME/Applications"
cp "$here/spork" "$SPORK_HOME/libexec/spork"
chmod +x "$SPORK_HOME/libexec/spork"
ln -sfn "$SPORK_HOME/libexec/spork" "$SPORK_HOME/bin/spork"

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
case "$1:${SHELL##*/}" in
  --no-modify-path:*) rc= ;;
  *:zsh)  rc=$HOME/.zshrc ;;
  *:bash) rc=$HOME/.bash_profile ;;
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
