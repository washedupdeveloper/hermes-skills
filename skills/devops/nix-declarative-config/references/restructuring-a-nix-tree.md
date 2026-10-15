# Restructuring a Nix tree without changing behaviour

For extraction, ownership moves and renames. The rule that makes all of it safe:
capture a behaviour oracle before the first edit and re-run it after.

## The oracle

```console
nix eval --raw '.#nixosConfigurations.<host>.config.system.build.toplevel.drvPath'
```

An identical path is hard evidence the deployed system is unaffected -- stronger
than "the check passed". It is a *sound* oracle only when no derivation text
changed: comments and code inside a `writeShellScript` / `runCommand` body are
part of the derivation, so an edit there legitimately moves the path. When the
path moves for a supposedly inert edit, prove the cause by swapping just that one
file back and forth and re-evaluating, rather than assuming something functional
changed.

For a pure rename or a comment outside a string, the path must come back
**identical**. If it does not, something else changed too.

## Order of gates

1. Capture the oracle.
2. Make the edit.
3. `nix fmt` -- nixfmt is a parser, so it reports `syntax error` before any
   evaluation and a structural mistake costs seconds instead of a full eval.
4. Re-run the oracle.
5. Full `nix flake check`, not just an eval. deadnix, statix, treefmt and
   gitleaks only run inside the check.

## Moving a `let` binding into a standalone file

- The binding is `name = <expr>;`; the standalone file is `<expr>`. The trailing
  `;` is the binding separator and must go, or you get
  `syntax error, unexpected ';'`. A `''…''` string that ended `'';` inside the
  binding ends `''` at top level.
- Dedent by the binding's indentation and nothing more. A `let` binding at module
  top level is indented 2 columns, so remove exactly 2 from each moved line.
  Nested lines keep their relative indentation -- do not assert "every line starts
  with exactly N spaces", because that check is wrong for nested content and
  fails on correct data.
- Prove the moved text is **byte-identical** by diffing the extracted body
  against the original after removing the dedent. "Looks the same" is not the
  claim being made.
- Pass values in as arguments and `callPackage` from the module:
  `{ pkgs, lib, username }:` in the new file,
  `pkgs.callPackage ./<file>.nix { inherit username; }` in the module -- matching
  the shape the repo already uses for its other derivations.
- A lambda argument whose only use moved with the code is now unused, and deadnix
  fails the check on it. Moving the only use of `lib` leaves `lib,` in the
  module's argument set.

## Renaming a file

- `git mv` so history follows.
- Grep for the basename across **every** file type, not just Nix. `docs/`, YAML,
  ADRs and reference files name paths, and a stale pointer is a silent lie.
- Do not miss relative-path *comments*: a path in a comment resolves against the
  file's own directory, so `# see ./topology.nix` inside
  `machines/<host>/configuration.nix` points at the machine directory, not the
  repo root. It needs `../../topology.nix`.
- Fixing the pointers and the docs that named the old location is part of the
  move, not polish.

## Scope

One ownership boundary per commit, and say which candidate was deliberately left
alone. A candidate you decided against is a result; report it rather than
silently dropping it.
