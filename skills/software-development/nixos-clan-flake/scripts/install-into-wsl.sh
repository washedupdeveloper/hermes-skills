#!/bin/sh
# install-into-wsl.sh <windows-src> <wsl-dest> [<windows-src> <wsl-dest> ...]
#
# Copies Windows-staged files into a repo inside a WSL distro, stripping CR, and
# prints a before/after hash per file. The patch/write_file tools cannot write a
# //wsl.localhost/... path, so this is how an edit gets landed.
#
# Run it INSIDE the distro:
#   wsl.exe -d <distro> -- /bin/bash /mnt/c/<scratch>/install-into-wsl.sh src dst ...
set -eu

[ $# -ge 2 ] || { echo "usage: $0 <src> <dest> [<src> <dest> ...]" >&2; exit 2; }
[ $(( $# % 2 )) -eq 0 ] || { echo "error: sources and destinations must pair up" >&2; exit 2; }

while [ $# -gt 0 ]; do
  src="$1"
  dst="$2"
  shift 2

  [ -f "$src" ] || { echo "missing source: $src" >&2; exit 1; }

  if [ -f "$dst" ]; then
    before=$(sha256sum "$dst" | cut -c1-12)
  else
    before="absent"
  fi

  tr -d '\r' < "$src" > "$dst"

  after=$(sha256sum "$dst" | cut -c1-12)
  lines=$(wc -l < "$dst")
  cr=$(grep -c $'\r' "$dst" || true)
  echo "  $dst  $before -> $after  (${lines} lines, CR count: ${cr})"
done
