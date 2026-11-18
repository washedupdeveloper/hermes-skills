#!/usr/bin/env bash
# ci-local.sh — run the CI jobs on this machine, and name the ones it cannot run.
#
#   ./scripts/ci-local.sh
#
# The workflow's jobs are commands, not magic: this runs the same ones in the same order.
# What it cannot reproduce is the matrix — a macOS leg needs a macOS host, and the Windows
# leg needs a Windows one — and the `cost` job, which reads a GitHub run id.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PY="$candidate"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "ci-local: no python3 on PATH. With Nix: nix develop -c ./scripts/ci-local.sh" >&2
  exit 2
fi
echo "ci-local: using $($PY --version 2>&1)"

fail=0
run() {
  name=$1
  shift
  printf '\n== %s ==\n' "$name"
  if "$@"; then
    echo "  PASS  $name"
  else
    echo "  FAIL  $name"
    fail=1
  fi
}

run "validate" "$PY" scripts/validate.py
run "tests" "$PY" -m pytest tests/ -q -p no:cacheprovider
run "claim audit" "$PY" scripts/claim-audit.py

if command -v actionlint >/dev/null 2>&1; then
  run "actionlint" actionlint
else
  echo
  echo "== actionlint == skipped (not on PATH; nix shell nixpkgs#actionlint -c actionlint)"
fi

if command -v nix >/dev/null 2>&1; then
  run "nix gate" nix flake check
else
  echo
  echo "== nix gate == skipped (no nix; the portable jobs above are the gate)"
fi

cat <<'EOF'

Not runnable from one machine:
  - the macOS leg of `validate` and `tests` (needs a macOS host)
  - the Windows leg, unless you are on Windows
  - `cost`, which reads a GitHub run id and a token
EOF

exit "$fail"