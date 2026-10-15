# Verifying generated shell when you cannot evaluate the flake

Use when the agent side has no `nix` and no network, so `nix build` / `nix eval` are impossible. The flake stays unverified; the shell it generates does not have to. This is worth the effort because the bugs live in the shell: string escaping, `set -e` interaction, and quoting all survive careful reading.

## 1. Extract the generated body

The body of a `writeShellScript` / `writeShellScriptBin` is a Nix indented string. Pull it out and undo the escapes before running anything:

```python
import re
src = open("modules/<mod>.nix").read()
body = re.search(r'writeShellScript "<name>" \'\'\n(.*?)\n  \'\';', src, re.S).group(1)
script = body.replace("''${", "${")        # Nix escape -> shell parameter expansion
script = script.replace("${username}", "testuser")   # Nix-level interpolation
```

Then replace the `lib.makeBinPath` block with a literal PATH (it is a Nix expression, not shell), write it to a file, and `bash -n` it. Run `bash -n` as its own step: a syntax error is a different bug class from a logic error.

To see exactly what you are dealing with, list every `''` and every `${` in the extracted body and confirm each one is the escaped form. A stray unescaped `${` interpolates at build time and is invisible until the script runs.

## 2. Stub the binaries and drive every branch

Put a fake `nix` first on `PATH`. It answers from files the test controls, so each branch is reachable:

```bash
#!/bin/bash
case "$1" in
  build)
    n=$(cat $COUNTER 2>/dev/null || echo 0); echo $((n+1)) > $COUNTER
    if [ "$MODE" = fail ] && [ "$n" = 1 ]; then echo "error: build failed" >&2; exit 1; fi
    if [ "$MODE" = oldbroken ] && [ "$n" = 0 ]; then echo "error: nope" >&2; exit 1; fi
    if [ "$n" = 0 ]; then echo "$OLD_OUT"; else echo "$NEW_OUT"; fi ;;
  flake) [ "$MODE" = norev ] && exit 0
    python3 -c "import json,pathlib;p=pathlib.Path('$LOCK');d=json.loads(p.read_text());d.setdefault('nodes',{})['<input>']={'locked':{'rev':'newrev111'}};p.write_text(json.dumps(d))" ;;
esac
exit 0
```

Build the input tree as plain directories (`$OLD_OUT/<skill>/SKILL.md`) rather than real store paths — `find`, `comm`, `diff` and `cp` do not care.

Branch matrix to cover, asserting exit code, the lock's resulting revision, and the report body each time:

| branch | expected |
|---|---|
| normal refresh | rc 0, lock advanced, report lists added/removed/changed |
| upstream unchanged | rc 0, lock untouched, no report written |
| new revision fails to build | rc 1, **lock restored**, report explains the restore |
| previous revision unbuildable | rc 0, refresh still happens, report notes the diff was skipped |
| empty result set | rc 0, report shows everything removed, no crash |
| input absent from the lock | rc 0, no bogus revision reported |

Re-run `bash -n` inside the harness too, and reset the counter and state dir between cases or the branches stop being independent.

## 3. Exercise a `runCommand` body the same way

Extract the body, substitute `$out` and the source path for real directories, and run it under `bash -c` against a replica of the upstream tree. Assert on the *contents* of the output directory, not just the exit code:

- every expected child is present and still holds its nested `references/` / `scripts/`
- no non-artifact sibling leaked in (`registry.json`, `*.mjs`, `native/`, `generated/`)
- a sibling directory without the marker file is excluded

## 4. Cross-check an authored config artifact

For a file the app loads rather than a script it runs (a bundle YAML, a JSON
manifest, an index), parse it and check every identifier it names against the set
that actually ships. An unknown name is skipped at runtime, so a typo reads as
success and the only symptom is the feature quietly not existing.

## 5. Report the residue

Say plainly which half is verified: the generated shell ran against stubs and covered its branches; the Nix itself was never evaluated or built. Then give the exact commands the user runs to close the gap (`nix flake lock`, `nh os switch`, the timer's `systemctl --user start`, the app's list command).
