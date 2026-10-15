# Derivation-backed deployment (a provisioned directory that cannot drift)

For when an app loads a directory of units (skills, plugins, presets) and something
**copies** a repo's tree into that directory. The copy drifts; a derivation cannot.

## Why a derivation, not a copy

A store path is read-only, so nothing can edit the deployed tree in place. Drift stops
being something to *detect* and becomes something the store cannot have — a `--check`
flag and a byte-comparison gate are work spent on an impossible failure. Keep the copier
for hosts without Nix: those are different hosts, not two versions of one host, so two
mechanisms is correct rather than duplication. Say which mechanism each host gets.

Cost to state plainly: the Nix path needs Nix. A host without it keeps the copier and
its drift.

## The derivation's hash covers the WHOLE tree, so unrelated commits report drift

A derivation's store path is a function of everything it takes as input, not of the
files it happens to install. A commit that touches only `docs/`, `.github/` or a README
still moves the store path — and any `--check` that decides drift by comparing the
deployed tree against **the store path** then reports drift while the deployed content is
byte-identical.

Measured: after a documentation-only edit, `council setup skill --check` reported drift,
the re-sync changed **no file**, and the check then reported "in sync". The store path had
moved; nothing had drifted.

Two consequences, both worth acting on:

- **Read a reported drift as "the store path moved", and confirm it with a content diff
  before chasing it** — `diff -rq "$S" "$DEST"` (above). The copier is the mechanism that
  can actually drift; the derivation is the mechanism that cannot, which is the whole
  reason for choosing it.
- **A check that wants to mean "the deployment matches the source" must compare content,
  not identity.** Comparing the store path makes every unrelated commit in the repository
  report drift, and a check that cries wolf on a README edit is one people learn to
  ignore — which costs you the signal when something really does drift.

The same property explains a size difference that looks alarming: an image or tarball
built from the tree changes bytes when only a doc changed, because the store paths inside
it moved. Compare the *content* (the file set, the file count, a diff of the tree) rather
than the byte size of the artifact when deciding whether two builds are equivalent.

## The tree is the copier's OUTPUT, not the source's runtime subset

Diff the derivation against the copier's **live destination**, file by file, before
believing it is equivalent. The two sets are not the same, and both differences are
silent:

- the framework's runtime subset omits modules the deployed **test suite** imports, so
  a "correct" runtime tree yields a deployment whose suite aborts at collection;
- data files a copier names explicitly (a calibration manifest, an eval baseline) are not
  `.py`, so a `*.py` glob misses them — and their absence changes behaviour rather than
  erroring.

```console
$ S=$(nix build --no-link --print-out-paths .#skill)
$ diff -rq "$S" "$DEST" -x '__pycache__' -x '*.pyc'
```

An empty diff is the claim; say so. Then assert the layout in a `checks` entry so it
cannot regress: required files present, and the copier itself **absent** (a copier
excludes its own name, so anything referencing it must say "repository only" — a test
that imports it aborts collection in the deployment).

## Two checks, and why the second is not optional

`nix flake check` skips outputs it does not recognise, so a `homeManagerModules` /
`nixosModules` output is **never evaluated** by it. Evaluate the module yourself against
a stub for the surface it touches:

```nix
evalMode = mode: lib.evalModules {
  modules = [
    stub                                        # declares only what the module reads
    (import ./nix/module.nix)
    { programs.x = { enable = true; inherit mode; }; }
  ];
};
```

Assert that **both** modes produce the setting each promises, rather than trusting the
default. The stub must declare every option the module touches — including `assertions`,
which a module commonly uses and a naive stub lacks. Its failure is
`The option 'assertions' does not exist`, which is the check working.

Two stub details: use a placeholder name from the repo's own allowlist for any
`/home/<name>` default (an invented one trips a portability gate), and write the stub's
attribute sets nested rather than as repeated dotted keys, or the linter fails your new
file.

## A deployed copy's suite must skip repo-side assertions

The deployed tree has no `README.md`, no `docs/`, no copier. A test that reads any of
them raises `FileNotFoundError` and takes the whole deployed suite red. Guard it with
the repo-side helper (`_require_repo()` — skip when the copier is absent) and say why in
the docstring: a suite that is always red is a suite whose real failures get ignored.

A guard must not neuter the check. Re-prove it after adding: append a deliberate failure
in the repo, watch it report, then remove it. Do that in the same session — a guard added
"to fix a red suite" that silently never fires is worse than the failure it replaced.

## Order of work

1. Build the derivation; diff it against the copier's live output until the diff is empty.
2. Add the layout check and the module-evaluation check.
3. Re-sync the copy from source so the two agree at the current revision.
4. Run the deployed suite, not just the repo one — the deployment is where a repo-shaped
   assumption breaks, and it is the suite most likely to be silently not running.
