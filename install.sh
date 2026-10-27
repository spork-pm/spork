#!/bin/bash
# Installs spork into ~/.spork (or $SPORK_HOME). No admin rights needed.
#   ./install.sh                  install or upgrade
#   ./install.sh --no-modify-path don't touch your shell startup file
set -e
here=$(cd "$(dirname "$0")" && pwd)
SPORK_HOME=${SPORK_HOME:-$HOME/.spork}

mkdir -p "$SPORK_HOME/libexec" "$SPORK_HOME/bin" "$SPORK_HOME/buckets" "$HOME/Applications"
cp "$here/spork" "$SPORK_HOME/libexec/spork"
chmod +x "$SPORK_HOME/libexec/spork"
ln -sfn "$SPORK_HOME/libexec/spork" "$SPORK_HOME/bin/spork"

# The bundled "main" bucket. Leave it alone if the user pointed main elsewhere.
main=$SPORK_HOME/buckets/main
if [ ! -e "$main" ] || { [ ! -L "$main" ] && [ ! -d "$main/.git" ] && [ ! -f "$main/.spork-source" ]; }; then
  rm -rf "$main"; mkdir -p "$main"
  cp -R "$here/bucket" "$main/bucket"
fi

echo "spork installed in $SPORK_HOME"

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
