# Measuring a flake's cost, and deciding its structure

How to answer "what does this flake cost to build and ship, and should its structure
change" with numbers instead of impressions.

## Closure size: the right command, and the one that lies

- `nix path-info -S <path>` prints **one row**: that path's total closure size. This is
  the closure size. Use it.
- `nix path-info -r <path>` prints one row **per path in the closure**. Count with it
  (`| wc -l`).
- `nix path-info -rS <path>` prints one row per path, each carrying **that path's own**
  closure size. Summing them counts every shared dependency once per dependent: a
  983 MB toolchain summed to 27 GB. **Never sum `-rS` rows.**

Sorting `-rS` by size is still useful — it ranks members by footprint and names the
biggest one — but every figure is that path's own closure, and they overlap heavily.

The same toolchain reads as `938M` or `983.3 MB` depending on MiB vs MB; check which
you are printing before calling two numbers a discrepancy.

## Which of it a cold runner must BUILD

The complement of closure size: how much a binary cache already has. Query each path
**on its own** — a batched query over a piped list silently reports misses:

```console
nix path-info -r "$t" | while IFS= read -r p; do
  nix path-info --store https://cache.nixos.org "$p" >/dev/null 2>&1 || echo "MISSING $p"
done
```

Batching it (`… | xargs -n 50 nix path-info --store …`) reported **30** absent paths on
a closure where the true figure was **2**. The error direction is the dangerous one: it
invents a problem, and a conclusion built on it ("this needs a private cache") is
wrong. Sanity-check by re-querying two or three "missing" paths individually — if a
path answers when asked alone, the batch lied.

What genuinely remains is usually the project's own `symlinkJoin`s (near-zero bytes,
seconds to build), which is the argument *against* adding a cache: everything else is a
stock nixpkgs package the default substituter already serves. Re-measure rather than
trusting the numbers in a document — they move with the toolchain.

## One tool added, every derived figure invalidated

Closure bytes, path count, substitutable fraction, image tarball size, layer content, and
every "N analyzers" string in prose are all functions of the same list. Add or remove one
entry and each becomes wrong at once, in a different document, with nothing to warn you.
Enumerate the derived figures before a toolchain change and re-measure each one after it,
in the same commit.

- **The count and the enumeration are two copies, and they drift.** A doc can state "14
  tools" and then list thirteen names, because the number was updated and the list was
  not. When a count changes, grep for the old number **and** for the enumeration
  (`grep -rn 'statix.*deadnix' docs/`), and fix both.
- **Prefer a figure that cannot go stale.** "every analyzer in `toolNames`" beats "all 13
  analyzers" wherever the number is not the point; keep a hard number only where the
  measurement itself is the claim.
- **`which <tool>` inside a devshell resolves to the join, not the tool.** The devshell
  puts the whole `symlinkJoin` on `PATH`, so `nix path-info -Sh $(which <tool>)` reports
  the *toolchain's* closure — 901.8 MiB for one 25 MB linter. Size a single tool from
  nixpkgs directly (`nix path-info -S nixpkgs#<tool>`) or rebuild the list without it.
- **Counting a nix list's entries with a regex over the block counts comments too.** A
  comment containing a quoted string (`"pyjwt~=2.13.0 not satisfied by version 2.14.0"`)
  is a list item to any `"..."` matcher, so a 14-entry list reads as 15. Count with a
  parser that walks lines beginning at the list's own indentation, and cross-check against
  a number the code computes itself.
- **A figure quoted from a source comment is a memory of a measurement.** Container
  "loaded image size" comments, a build log's byte count, an upstream README's number —
  none are re-derivable here. Either measure it or drop it; a number you cannot check is
  a claim you cannot defend.

## A package's marginal cost is not its closure size

Removing one entry frees its closure **minus** whatever the remaining entries already
pull in. Only a rebuild gives the real figure:

```console
nix build .#<attr> --print-out-paths --no-link   # then: nix path-info -S <out>
# drop exactly one entry from the list, rebuild, compare
```

One rebuild per candidate — the entries' closures overlap, so a sum of individual
closures overstates the saving, sometimes enormously. The tell for heavy overlap is an
entry that frees ~0: a formatter package that another entry already provides is the
classic case, and its individual closure looks large.

## Removing a tool that something names is not free

Before deleting an entry, grep the whole tree for its name — the answer decides whether
the change is a cost cut or an edit to the project's own instructions:

```console
grep -rIl --exclude-dir=.git --exclude-dir=<run-dir> "\b<tool>\b" skills/ docs/ bots/
```

A tool named **as a command in a shipped rubric** is part of what the project tells its
users to run. Prefer removing the entry that is not scored, not probed, named only in
prose, and whose config file does not exist — and say which of those checks you ran.

## Timing: never build a timer on a tool that may be absent

`echo "$(date +%s.%N) - $s" | bc` prints **nothing** when `bc` is missing, so every row
reads `0.00s` — a table that looks like "nix is instant" and is pure garbage. Use an
interpreter you know is there, and take best-of-N:

```python
import subprocess, time
def t(cmd):
    s = time.perf_counter()
    subprocess.run(cmd, shell=True, capture_output=True)
    return time.perf_counter() - s
```

Warm flake evaluation is **seconds** per invocation (measured 1.9-3.9 s for
`nix eval` and `nix flake check --no-build` on a ~1,350-line flake), so a 0.00 s result
is always the instrument and never the machine.

## Assert an in-place edit landed before you build

An edit script inside `bash -c` runs only if the command before it succeeded. When it
did not, the edit is silently skipped and the build produces the **unchanged**
derivation, which reads as "my change had no effect" and sends you hunting a logic bug
that is not there. Print a count after the edit and fail on a mismatch, before measuring
anything:

```console
grep -c '<pattern>' <file>   # must be 0 (or the expected number) — prove it, do not assume
```

## Adopting flake-parts or clan: the decision for a TOOL flake

- **Clan prescribes nothing for a flake that deploys no machines.** It is a framework
  for fleets of VPN-connected NixOS machines, and its docs are entirely machine- and
  service-oriented. Importing its flake module forces `clan.meta.name` (no default),
  i.e. naming a clan the repo is not. For a library/tool flake, do not adopt clan; the
  clan-relevant act is publishing a service or a flake module for clan users, which is
  only worth anything if you ship NixOS services. Record the determination so it is not
  silently revisited.
- **flake-parts is a good fit for a tool flake**: module splitting, `perSystem`
  replacing a hand-rolled `forAllSystems`, merge semantics across modules, and none of
  the NixOS machinery that carries the recursion traps.
- **flake-parts has no releases and no tags** — pin it by revision in `flake.lock`.
  "What is its current major version" is not a meaningful question about it.
- **Cost:** two entries in every consumer's `flake.lock` (`flake-parts` and its
  `nixpkgs-lib`), mitigable at the source with
  `flake-parts.inputs.nixpkgs-lib.follows = "nixpkgs"`. Output consumers are unaffected
  — nobody needs flake-parts to `nix build` your packages.
- **`perSystem` is evaluated for every declared system** on
  `nix flake check --all-systems`, so it must stay cheap.
- Only `easyOverlay` is a built-in helper. `easyHosts` is third-party
  (`tgirlcloud/easy-hosts`) and `easyModules` does not exist — the real module is
  `flakeModules.modules`.
- **Size the split from measured line spans, not from the output list.** Find where the
  lines actually are (`awk`/`grep` the top-level `let` bindings and their lengths): one
  binding holding 45% of the file is the reason to split, and a proposed module layout
  should quote those spans so the user can check it.

## Auditing a toolchain for necessity

For "is every dependency here necessary", classify each entry by its **role**. This is
not a matter of taste — each role has evidence:

| role | evidence | verdict |
| --- | --- | --- |
| **scored** | it appears in the set the gate computes coverage from | necessary |
| **executed** | a probe or a build step actually invokes it | necessary |
| **provides** | a flake output execs it (a formatter, a wrapper) | necessary |
| **rubric** | named as a command in a shipped rubric | available on demand |
| **prose** | named only in docs, or nowhere outside the tool list | remove |

Build the table from the tree, not from the list's own comments: grep each name across
the modules that execute things, the flake, and the CI workflows, and read the
project's own tool catalogue if it has one. A name appearing **only in the tool list**
is a declaration nothing reads — remove it, and expect the measured saving to be small
(overlapping closures; see the marginal-cost section above).

Four findings this audit produces, and they point in different directions:

- **A tool the gate expects that nothing probes.** A scored tool with no probe caps the
  score for every repo of that stack, silently. Test the class, not the instance:
  assert that every expected name has a probe, and derive that set from the gate's own
  tables — a hardcoded list of names misses the case it was written for.
- **A tool the project's own catalogue claims but nothing uses.** A comment saying "the
  security dimension uses X" is a claim about behaviour; check it against what runs.
  Either add the probe (a missing signal) or fix the claim (a false one) — never leave
  both standing.
- **The gate's expected set usually mixes two kinds of name:** real tools and internal
  probe names implemented in the harness. Separate them, or a reader cannot tell
  "missing tool" from "probe I already have".
- **Decide what the score does for a stack with no toolchain.** A gate expecting
  JavaScript or Rust analyzers from a Nix/Python-only toolchain caps those repos below
  full coverage for tools never intended to ship. Drop the stack or document the
  degradation; do not leave it implicit.

A tool that ships but is not probed is a defensible middle: available on demand, absent
from the routine path, so nothing pays for it per review. Pin both halves with a test —
assert it is in the tool list **and** absent from the probe table — so neither side
drifts alone, and check the test has teeth by wiring a stub probe in and watching it
fail.

## The shipped set is the QA set; everything else is contributor choice

This user's rule, stated for a toolchain that ships: **the shipped toolchain carries the
centralised quality assurance, and everything else is the contributor's own choice.**
They want to customise their own machine while the project's QA stays independent of what
any individual has installed. So split the list in two rather than pruning to one:

| list | membership test | lands in |
| --- | --- | --- |
| shipped / QA | **scored**, **probed**, or **provides an output** | devshell, container, `nix shell .#<pkg>` |
| contributor DX | anything a human wants while working *on* the repo | devshell only |

Language servers, closure browsers, derivation-diff tools, interactive build
accelerators and density meters are DX: a reviewer does not need them, so they must not
be in the product. Three consequences that are easy to miss:

- **A rubric naming a tool is not sufficient reason to ship it in the container.** A
  rubric command is an option, not a dependency — a review that skips it is still
  complete. Give the shipped set its own justification (scored / probed / provides) and
  move the rubric conveniences to the DX list.
- **When a rubric-named tool moves to DX, say so in the rubric.** A reviewer following
  it inside the container is otherwise sent looking for a binary that is not there. One
  line — "devshell only, not in the shipped toolchain" — is the whole fix.
- **A rubric command naming a tool that is in NO list is a dead procedure, not a
  convenience.** The tool was never shipped and never will be, so every reviewer that
  follows the rubric gets `command not found` and the dimension reports nothing for the
  procedure it documents. Check each rubric command against the shipped set, then either
  ship the tool or rewrite the command to one that already ships — `gnugrep` sits in the
  shell dependencies and covers most `rg` patterns as `grep -rnE`, at zero cost, where
  adding ripgrep costs its whole closure.
- **A shipped tool that is expensive to run goes in the shipped list but out of the
  probe table**: available on demand, never paid for per review. Pin both halves with a
  test, as above.

Measure the split rather than asserting it: the shipped closure size and path count are
the number that justifies the change, and the DX tools must be **absent** from the
container — check a few by name rather than inferring it from the list.

## Measuring a container image with no daemon

A `dockerTools.buildLayeredImage` output is a plain gzipped tarball, so its layer count
and content size are measurable without docker or podman — which are often both absent.

The layers are `<sha256>/layer.tar` **inside** the outer gzip and are themselves
uncompressed, so `grep -c '\.tar\.gz$'` finds nothing and a `gzip -dc` loop over the
extracted directory names reports zero bytes. Take both numbers from the listing:

```console
tar -tzf img.tar.gz | grep -c 'layer.tar$'                             # layer count
tar -tvzf img.tar.gz | awk '$6 ~ /layer\.tar$/ {s+=$3} END {print s}'   # uncompressed
stat -c %s img.tar.gz                                                 # download size
```

Three numbers answer three different questions: the tarball is what a user downloads,
the sum of `layer.tar` sizes is what the layers hold, and the size `docker load`
reports is docker's own accounting. Quote the loaded size only from a run you did — a
number carried over from a comment in the source is a memory of a measurement, and the
layer content is the figure that stays checkable when no daemon is installed.

## Mining a reference repo for conventions

Reading a well-regarded project to learn its structure yields a list of things it does.
Adopt the ones whose benefit you can measure **here**, and record each rejection with the
number that decided it — otherwise the same convention is re-proposed next session, and
an undocumented rejection reads as an oversight rather than a decision.

The questions that actually decide it:

- **Does it remove work, or move it?** A helper that parallelises a check set only pays
  when evaluating the set is slow. Measure yours first: `nix flake check --no-build` is
  seconds on a mid-size flake and a cached full gate is tens of seconds, so a "build only
  the uncached derivations" wrapper has nothing to accelerate. The reference repo needs it
  because its check set is an order of magnitude larger — that is the whole difference.
- **Is the pattern about being a library?** `default.nix` / `shell.nix` back-compat in a
  library repo is a `pkgs.callPackage ./lib` entry point. A tool that ships a CLI and a
  flake has no such consumer, so the shim is a fourth style to maintain. Read what the
  file actually returns before copying it — the filename is the misleading part.
- **Is the thing it optimises already solved here?** A private binary cache earns its
  secret and its CI job only when the closure is not already substitutable. Measure the
  fraction first; when nearly all of it is on the default substituter, a cache would carry
  only your own `symlinkJoin`s.
- **Does the extra matrix pay for itself?** Testing two nixpkgs channels doubles CI cost;
  for a toolchain pinned to one revision by design it tests a combination you do not
  support.

Then put the table in the docs — convention, where it came from, adopted or rejected, and
why. A rejection with its measurement is a decision; a rejection with an opinion is a
future argument. Adopted conventions that need a guard (a template, a schema, a generated
file) get one in the same commit, because they are the artifacts nothing else in the gate
can see.

## A linter is not a gate until it passes the tree it gates

Before adding a linter to the shipped set or to a check, run it against the repo's own
tree. A linter that fails the existing tree is not a gate — it is a config-file project:
either you spend the session reformatting unrelated files, or you add a config whose only
purpose is to make the linter agree with the code it is judging, at which point the gate
asserts nothing. Test it before adopting it, and record the result either way. Prefer the
purpose-built tool over the general one: for CI workflow YAML that is `actionlint` (which
checks the schema and the expressions), not a generic YAML style linter.
