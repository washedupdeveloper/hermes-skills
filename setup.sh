#!/usr/bin/env bash
# setup.sh — point Hermes at this repo's skills. Run once per machine.
#
#   ./setup.sh            apply the desired state
#   ./setup.sh --check    report drift; change nothing
#   ./setup.sh --print    show the desired state and exit
#
# Declarative: DESIRED STATE below is the whole declaration, and re-running is a no-op
# when in sync. It resolves its own location, so it works from any clone on any OS.
set -euo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_SKILLS="$HERE/skills"

# ─── DESIRED STATE ───────────────────────────────────────────────────────────
# The repo's skills tree is the source of truth, mounted by REFERENCE — never copied.
# Reading is live, so `git pull` is the update mechanism.
# See docs/adr/0001-reference-not-symlink.md.
DESIRED_EXTERNAL_DIR="$REPO_SKILLS"

# No approval prompts. This repo is git-tracked, so a background skill write shows up in
# `git status` / `git diff` and reverts with `git checkout` — the review gate, at no cost
# at the time of the write.
DESIRED_WRITE_APPROVAL="false"

# New agent-created skills are NOT sent here. The profile-local default
# (~/.hermes/skills/) is left alone on purpose: it keeps this repo free of untracked
# files, and promotion into it stays a deliberate act.
# ─────────────────────────────────────────────────────────────────────────────

MODE="${1:-apply}"
case "$MODE" in
  apply|--check|--print) ;;
  *) echo "usage: $0 [--check|--print]" >&2; exit 2 ;;
esac

die() { echo "setup.sh: $*" >&2; exit 1; }

[ -d "$REPO_SKILLS" ] || die "no skills/ next to this script ($REPO_SKILLS)"

command -v hermes >/dev/null 2>&1 || die "hermes not on PATH"

hermes_ok() { hermes "$@" 2>/dev/null | grep -v '^⚠' || true; }

# `hermes config get <key> --json` for a list; plain value otherwise.
current() { hermes_ok config get "$1" --json | tr -d '\r\n'; }

# A JSON list of strings, without a JSON parser (jq/python may be absent).
# `hermes config get --json` may render an entry as `~/x` while this script resolves an
# absolute path, so compare EXPANDED paths, never the raw strings.
dirs_include() { # $1 = json list, $2 = absolute path
  local raw e
  while IFS= read -r raw; do
    [ -n "$raw" ] || continue
    e=${raw#\"}; e=${e%\"}
    case "$e" in
      '~/'*) e="$HOME/${e#\~/}" ;;
    esac
    [ "$e" = "$2" ] && return 0
  done < <(printf '%s' "$1" | grep -o '"[^"]*"' || true)
  return 1
}

if [ "$MODE" = "--print" ]; then
  printf 'external_dirs  += %s\n' "$DESIRED_EXTERNAL_DIR"
  printf 'write_approval  = %s\n' "$DESIRED_WRITE_APPROVAL"
  exit 0
fi

drift=0

# ── external_dirs: merge, never clobber. Another entry may be someone else's. ──
cur_dirs=$(current skills.external_dirs)
[ -n "$cur_dirs" ] || cur_dirs='[]'

if dirs_include "$cur_dirs" "$DESIRED_EXTERNAL_DIR"; then
  echo "  ok       skills.external_dirs already references this repo"
else
  drift=1
  if [ "$MODE" = "--check" ]; then
    echo "  DRIFT    skills.external_dirs does not reference $DESIRED_EXTERNAL_DIR"
  else
    case "$cur_dirs" in
      '[]') new_dirs="[\"$DESIRED_EXTERNAL_DIR\"]" ;;
      *)    new_dirs="${cur_dirs%]},\"$DESIRED_EXTERNAL_DIR\"]" ;;
    esac
    hermes config set skills.external_dirs "$new_dirs" >/dev/null 2>&1 \
      || die "could not set skills.external_dirs (managed install? declare it in Nix instead)"
    echo "  set      skills.external_dirs += $DESIRED_EXTERNAL_DIR"
  fi
fi

# ── write_approval ────────────────────────────────────────────────────────────
cur_appr=$(current skills.write_approval)
if [ "$cur_appr" = "$DESIRED_WRITE_APPROVAL" ]; then
  echo "  ok       skills.write_approval = $DESIRED_WRITE_APPROVAL"
else
  drift=1
  if [ "$MODE" = "--check" ]; then
    echo "  DRIFT    skills.write_approval is '$cur_appr', want '$DESIRED_WRITE_APPROVAL'"
  else
    hermes config set skills.write_approval "$DESIRED_WRITE_APPROVAL" >/dev/null 2>&1 \
      || die "could not set skills.write_approval"
    echo "  set      skills.write_approval = $DESIRED_WRITE_APPROVAL"
  fi
fi

# ── verify: the skills must actually resolve ──────────────────────────────────
if [ "$MODE" = "--check" ]; then
  [ "$drift" -eq 0 ] && echo "  in sync" || echo "  drift above — run ./setup.sh"
  exit "$drift"
fi

n=$(find "$REPO_SKILLS" -name SKILL.md -not -path '*/assets/*' 2>/dev/null | wc -l | tr -d ' ')
echo "  ok       $n skills reachable from $REPO_SKILLS"
echo
echo "Restart Hermes (or run /reload-skills) so the skill index picks them up."
