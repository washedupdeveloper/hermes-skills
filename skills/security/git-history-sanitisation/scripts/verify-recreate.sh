#!/usr/bin/env bash
# verify-recreate.sh — is a history rewrite actually gone from the host?
#
# A force-push moves a branch pointer; it deletes no objects. The host keeps every
# superseded commit and serves it BY SHA to anyone with access to the repository, so
# "one commit on the branch" does not mean "one commit on the server". Only recreating
# the repository removes the old objects. This script answers whether that happened.
#
# USAGE
#   verify-recreate.sh <owner> <repo>=<sha>[,<sha>...] [<repo>=<sha>[,<sha>...] ...]
#
# Substitute your own owner and SHAs — these are placeholders:
#
#   verify-recreate.sh acme \
#     website=1f0e5c9a7b3d2e4f6a8b0c1d2e3f4a5b6c7d8e9f \
#     api=9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b
#
# SHAs must be the FULL 40 hex characters. An abbreviated SHA fails to fetch whether or
# not the host still holds the object, so a list of abbreviations reports "gone" for
# everything and returns a false all-clear on the exact question this answers. The
# script refuses them rather than let that happen.
#
# EXIT  0 = no superseded object served and no leftover repo. Safe to make public.
#       1 = still serving something, or a leftover repository exists.
#       2 = bad input.
#
# Every check reads $? from a redirection, never through a pipe: $? through a pipe
# reports the pipe's last stage, not git's, so a piped probe reports success for a
# fetch that failed.
set -uo pipefail

if [ "$#" -lt 2 ]; then
  sed -n '2,30p' "$0" | sed 's/^# \?//'
  exit 2
fi

OWNER="$1"; shift
leaked=0
leftover=0
bad_input=0

for spec in "$@"; do
  repo_bad=0
  repo="${spec%%=*}"
  shas="${spec#*=}"
  if [ "$repo" = "$spec" ] || [ -z "$shas" ]; then
    echo "bad argument (want repo=sha[,sha...]): $spec" >&2
    bad_input=1
    continue
  fi

  echo "=== $OWNER/$repo"

  # Validate every SHA before using any: an abbreviated one silently fails to fetch.
  for sha in ${shas//,/ }; do
    if ! printf '%s' "$sha" | grep -qE '^[0-9a-f]{40}$'; then
      echo "  INVALID SHA: '$sha' (need 40 lowercase hex chars)" >&2
      echo "    an abbreviated SHA fails to fetch even when the host serves it," >&2
      echo "    which reads as 'gone' and is a false all-clear." >&2
      repo_bad=1
      bad_input=1
    fi
  done
  # Per-repo, not the global: one bad SHA must not skip the repositories after it.
  [ "$repo_bad" -eq 0 ] || continue

  work=$(mktemp -d)
  if ! git clone -q --bare "git@github.com:$OWNER/$repo.git" "$work/r.git" 2>/dev/null; then
    echo "  cannot clone — repository gone, renamed, or no access from here"
    rm -rf "$work"
    continue
  fi

  echo "  advertised refs:"
  git -C "$work/r.git" for-each-ref --format='    %(objectname:short)  %(refname)' 2>/dev/null

  echo "  superseded objects still fetchable?"
  for sha in ${shas//,/ }; do
    out=$(git -C "$work/r.git" fetch -q origin "$sha" 2>&1); rc=$?
    if [ "$rc" -eq 0 ]; then
      printf '    %s  exit=%s  LEAKED\n' "${sha:0:10}" "$rc"
      leaked=$((leaked+1))
    else
      printf '    %s  exit=%s  gone\n' "${sha:0:10}" "$rc"
    fi
  done
  rm -rf "$work"
  echo

done

echo "================================================"

# A rename-and-recreate leaves the OLD repository alive under a new name, still serving
# the old objects. That is the step people skip, so check it explicitly.
#
# GitHub also keeps a REDIRECT from the old name, so after renaming X -> X-old the plain
# name X still resolves and a push to X lands in X-old while reporting success — and the
# refs then "verify", because they agree with the wrong repository. The tell is that the
# two names advertise IDENTICAL refs, so compare them rather than trusting that X points
# at the repository you think it does.
echo "leftover renamed repositories?"
for spec in "$@"; do
  repo="${spec%%=*}"
  plain_refs=$(timeout 60 git ls-remote "git@github.com:$OWNER/$repo.git" 2>/dev/null | sort)
  for suffix in old backup; do
    if timeout 60 git ls-remote "git@github.com:$OWNER/$repo-$suffix.git" >/dev/null 2>&1; then
      echo "  STILL EXISTS: $OWNER/$repo-$suffix  (delete it — it still serves the old objects)"
      leftover=$((leftover+1))
      suffix_refs=$(timeout 60 git ls-remote "git@github.com:$OWNER/$repo-$suffix.git" 2>/dev/null | sort)
      if [ -n "$plain_refs" ] && [ "$plain_refs" = "$suffix_refs" ]; then
        echo "    REDIRECT: $OWNER/$repo advertises the same refs as $OWNER/$repo-$suffix."
        echo "    A push to $OWNER/$repo goes into $OWNER/$repo-$suffix. Do not push until"
        echo "    the new $OWNER/$repo exists, and confirm which repository received it."
      fi
    fi
  done
done
[ "$leftover" -eq 0 ] && echo "  none"

echo "================================================"
if [ "$bad_input" -ne 0 ]; then
  echo "BAD INPUT — fix the SHAs above and re-run. No verdict is possible."
  exit 2
fi
if [ "$leaked" -eq 0 ] && [ "$leftover" -eq 0 ]; then
  echo "RECREATE CONFIRMED — no superseded object is served by the host."
  echo "  Safe to: make the repository public."
  echo "  Safe to: delete the pre-rewrite bundles (they were the only other copy)."
  exit 0
else
  echo "NOT SAFE — $leaked superseded object(s) still fetchable, $leftover leftover repo(s)."
  echo "  Do NOT make the repository public."
  echo "  Do NOT delete the pre-rewrite bundles yet."
  exit 1
fi
