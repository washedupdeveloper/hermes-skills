#!/usr/bin/env bash
# The per-clone half of the LF rule in AGENTS.md. Git does not track its own
# config, so a fresh clone runs this once.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

git config core.hooksPath .githooks
git config core.autocrlf false
git config core.eol lf
git config core.safecrlf true

printf 'core.hooksPath = %s\n' "$(git config --get core.hooksPath)"
printf 'core.autocrlf  = %s\n' "$(git config --get core.autocrlf)"
printf 'core.eol       = %s\n' "$(git config --get core.eol)"
printf 'core.safecrlf  = %s\n' "$(git config --get core.safecrlf)"
printf '\nLF is now enforced at git add (safecrlf) and at commit (.githooks/pre-commit).\n'
