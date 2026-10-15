#!/usr/bin/env bash
# e2e: exercise setup.sh against a STUBBED `hermes`, so no real config is touched.
#
#   bash tests/e2e/test_setup.sh
#
# A stub is the point: the merge path can only be tested by lying to the script
# about the current config, and doing that against the live config would edit it.
set -uo pipefail

REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
SETUP="$REPO/setup.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

pass=0; fail=0
ok()   { echo "  ok    $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL  $1"; echo "        $2"; fail=$((fail+1)); }

# ── the stub `hermes`: answers `config get` from $STUB_GET, logs `config set` ──
mkdir -p "$TMP/bin"
cat > "$TMP/bin/hermes" <<'STUB'
#!/usr/bin/env bash
case "$1 $2" in
  "config get")
    case "$3" in
      skills.external_dirs) printf '%s\n' "${STUB_DIRS:-[]}" ;;
      skills.write_approval) printf '%s\n' "${STUB_APPR:-false}" ;;
    esac ;;
  "config set") printf '%s\n' "$3=$4" >> "${STUB_LOG:?}" ;;
esac
exit 0
STUB
chmod +x "$TMP/bin/hermes"
export PATH="$TMP/bin:$PATH"
export STUB_LOG="$TMP/calls.log"

run() { : > "$STUB_LOG"; bash "$SETUP" "$@" >/dev/null 2>&1; }
calls() { cat "$STUB_LOG" 2>/dev/null; }

# ── 1. syntax ────────────────────────────────────────────────────────────────
bash -n "$SETUP" && ok "syntax valid" || bad "syntax valid" "bash -n failed"
[ -x "$SETUP" ] && ok "executable bit set" || bad "executable bit set" "not +x"

# ── 2. --print is read-only and names both settings ──────────────────────────
out=$(STUB_DIRS='[]' bash "$SETUP" --print 2>&1)
echo "$out" | grep -q 'external_dirs' && echo "$out" | grep -q 'write_approval' \
  && ok "--print names both settings" || bad "--print names both settings" "$out"
[ -s "$STUB_LOG" ] && bad "--print wrote nothing" "it called config set" \
                   || ok "--print wrote nothing"

# ── 3. empty list -> a one-element list ──────────────────────────────────────
STUB_DIRS='[]' run
calls | grep -q 'skills.external_dirs=\["'"$REPO"'/skills"\]' \
  && ok "empty list -> [repo]" || bad "empty list -> [repo]" "$(calls)"

# ── 4. an unrelated entry is MERGED, never clobbered ─────────────────────────
STUB_DIRS='["/tmp/other-skills"]' run
got=$(calls | grep '^skills.external_dirs=')
case "$got" in
  *'/tmp/other-skills'*"$REPO"'/skills'*) ok "merge preserves the other entry" ;;
  *) bad "merge preserves the other entry" "$got" ;;
esac
case "$got" in
  *'["/tmp/other-skills,"'*) bad "merge emits valid JSON" "quote eaten: $got" ;;
  *) ok "merge emits valid JSON" ;;
esac

# ── 5. already present -> idempotent, no write ───────────────────────────────
STUB_DIRS='["'"$REPO"'/skills"]' run
calls | grep -q 'external_dirs' \
  && bad "idempotent when present" "wrote anyway: $(calls)" \
  || ok "idempotent when present"

# ── 6. write_approval drift is corrected ─────────────────────────────────────
STUB_DIRS='["'"$REPO"'/skills"]' STUB_APPR='true' run
calls | grep -q 'skills.write_approval=false' \
  && ok "write_approval true -> false" || bad "write_approval true -> false" "$(calls)"

# ── 7. --check exits 1 on drift, 0 in sync ───────────────────────────────────
STUB_DIRS='[]' STUB_APPR='false' bash "$SETUP" --check >/dev/null 2>&1
[ $? -eq 1 ] && ok "--check exits 1 on drift" || bad "--check exits 1 on drift" "wrong code"
STUB_DIRS='["'"$REPO"'/skills"]' STUB_APPR='false' bash "$SETUP" --check >/dev/null 2>&1
[ $? -eq 0 ] && ok "--check exits 0 in sync" || bad "--check exits 0 in sync" "wrong code"

# ── 8. an unknown flag is refused, not ignored ───────────────────────────────
bash "$SETUP" --bogus >/dev/null 2>&1
[ $? -eq 2 ] && ok "unknown flag exits 2" || bad "unknown flag exits 2" "wrong code"

echo
echo "  $pass passed, $fail failed"
[ "$fail" -eq 0 ]
