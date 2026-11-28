#!/usr/bin/env bash
# Plant a violation, require the gate to reject it, restore the tree.
#
#   source plant-and-reject.sh
#   expect_reject "a duplicate trigger" "sed -i 's/^scope_out: .*/scope_out: [x]/' skills/a/SKILL.md" \
#       "python scripts/validate.py" "already claimed by"
#
# Call it once per rule. A gate is proven by the violations it rejects, not by the ones it happens
# to pass.
#
# Mechanics that matter, each of which produced a false verdict before it was fixed here:
#   * the gate's whole output is captured, never piped to `tail` — the violation message is above
#     the summary line, and a one-line helper greps the summary;
#   * matching uses `case`, never `cmd | grep -q` — under `pipefail` a matching grep exits early,
#     the writer takes SIGPIPE, and the pipeline reports 141 exactly when the gate was right;
#   * the plant is verified to have changed something, or the run proves the baseline again;
#   * the restore is verified, because a harness that leaves the tree broken is worse than none.

set -uo pipefail

PR_PASS=0
PR_FAIL=0

_pr_clean() {
  [ -z "$(git status --porcelain)" ]
}

_pr_restore() {
  git checkout -q -- . || return 1
  _pr_clean
}

# expect_reject <label> <plant command> <gate command> <expected output fragment>
expect_reject() {
  local label=$1 plant=$2 gate=$3 want=$4 before after out

  if ! _pr_clean; then
    printf '  SKIP  %s — tree not clean before the plant\n' "$label"
    PR_FAIL=$((PR_FAIL + 1))
    return 1
  fi

  before=$(git diff | sha1sum)
  eval "$plant"
  after=$(git diff | sha1sum)
  if [ "$before" = "$after" ]; then
    printf '  FAIL  %s — the plant changed nothing; this run proves the baseline\n' "$label"
    PR_FAIL=$((PR_FAIL + 1))
    _pr_restore >/dev/null
    return 1
  fi

  out=$(eval "$gate" 2>&1)
  case "$out" in
    *"$want"*)
      printf '  PASS  %s — rejected with: %s\n' "$label" "$want"
      PR_PASS=$((PR_PASS + 1)) ;;
    *)
      printf '  FAIL  %s — the gate accepted it (wanted %s)\n' "$label" "$want"
      printf '%s\n' "$out" | tail -5 | sed 's/^/        /'
      PR_FAIL=$((PR_FAIL + 1)) ;;
  esac

  if ! _pr_restore; then
    printf '  FAIL  %s — the tree did not restore; stop and fix that first\n' "$label"
    PR_FAIL=$((PR_FAIL + 1))
  fi
}

pr_summary() {
  printf '\nrejected: %d   accepted: %d\n' "$PR_PASS" "$PR_FAIL"
  [ "$PR_FAIL" -eq 0 ]
}
