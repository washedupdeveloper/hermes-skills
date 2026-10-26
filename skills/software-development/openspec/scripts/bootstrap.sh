#!/usr/bin/env bash
# Initialize OpenSpec in a repository: structure, telemetry off, the AGENTS.md rule.
# Idempotent: run it on a repo that already has openspec/ and it changes nothing.
set -euo pipefail

repo="${1:-.}"
cd "$repo"

command -v openspec >/dev/null 2>&1 || {
  echo "openspec: not on PATH; install with: npm install -g --prefix ~/.local/npm @fission-ai/openspec@1.15.0" >&2
  exit 1
}

if [ ! -d openspec ]; then
  openspec init --tools none >/dev/null
  echo "openspec: initialized"
fi

# OpenSpec sends anonymous command-name telemetry by default. Off for this machine.
openspec config set telemetry.enabled false >/dev/null 2>&1 || true

if [ ! -f AGENTS.md ]; then
  printf '# AGENTS.md\n\nRules for an agent working in this repository.\n' > AGENTS.md
  echo "AGENTS.md: created"
fi

if ! grep -q '^## Specs (OpenSpec)' AGENTS.md; then
  cat >> AGENTS.md <<'EOF'

## Specs (OpenSpec)

A behavior change starts in `openspec/changes/<name>/` (proposal, spec delta, tasks), not in
code. `openspec list --specs` before proposing; `openspec validate <name> --strict` before
applying and before archive; `openspec archive <name> --yes` when the work lands.
Procedure: the `openspec` skill. Pure refactors and dependency bumps set `skip_specs: true`.
EOF
  echo "AGENTS.md: rule appended"
fi

echo "openspec: $(find openspec/specs -name spec.md 2>/dev/null | wc -l) spec file(s)"
