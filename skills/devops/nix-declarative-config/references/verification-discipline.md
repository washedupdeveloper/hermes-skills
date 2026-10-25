# Verifying a Nix change, and reporting it honestly

The drvPath oracle and the order of gates are in
`restructuring-a-nix-tree.md`. This file is the discipline around *claims*: what
counts as evidence, and how to avoid asserting more than you ran.

## Pick the oracle for the change

| Change | Oracle |
| --- | --- |
| Pure rename, or a comment outside a string | toplevel drvPath must come back **identical** |
| Anything inside a `''…''` script body | drvPath **will** move -- that is correct, prove the cause by swapping one file |
| Generated config (`/etc/*`, `nix.conf`) | read the generated file out of the derivation chain, do not trust the merge |
| A build result | `nix build --no-link --print-out-paths`, and compare the path |
| A new custom flake output | it is invisible to `nix flake check` unless paired with a `checks` entry |
| Does the running machine match this tree? | `readlink -f /run/current-system` must **equal** `nix build .#nixosConfigurations.<host>.config.system.build.toplevel --no-link --print-out-paths` |
| Is a generator a no-op? | exit 0, no output, `git status --short` still empty, and the file count under its output dir unchanged |

**"A switch happened" and "the machine runs this tree" are different claims.**
`nixos-rebuild list-generations` proves only the former. The equality above is the one that
answers "is the config I just edited live", and it costs one build that is usually already
in the store. Same shape for a generator: silence is not proof of a no-op — an empty
diff plus an unchanged file count is.

## Test a requirement by varying one variable

To decide whether a flag or setting is *required*, remove the ambient source of it
**and** test both with and without it:

```console
env -u NIX_CONFIG nix eval --accept-flake-config …   # flag present
env -u NIX_CONFIG nix eval …                         # flag absent
```

A set environment variable satisfies the requirement regardless of the flag under
test, so a run that leaves it set cannot distinguish the two cases -- and will
read as proof that the flag is unnecessary when the opposite may be true. State
the hypothesis first: if the result would be the same either way, the test is not
evidence.

## Validate a probe before you record it

- **A probe that cannot fail proves nothing.** Run a deliberately bogus input
  through it first and confirm it reports "not found".
- Prefer matching the **diagnostic text** over the exit code: tools commonly
  warn about an unrecognised value and still exit 0, so `cmd && echo yes || echo no`
  reports success for every input including nonsense.
- Derive counts from the probe output. Never restate a number from an earlier
  session's notes -- a wrong figure written into a skill reference will be
trusted and repeated.

## Propagate a corrected claim to every copy

The same fact usually appears in a commit message, a document, and a skill
reference. When one copy is corrected, grep the repo **and** the skill for the
claim and fix all of them. A half-corrected fact is worse than an uncorrected one,
because the surviving copy reads as verified.

## Know what you can actually observe

A docker sandbox cannot see the host's system generation, `/run/current-system`,
or the host's `/etc/nix/nix.conf` -- the sandbox has its own `nix.conf`, and
reading it says nothing about the machine. Do not read a sandbox file as though
it were the host's.

What the sandbox *does* carry is the host's built **derivations**: the image is
built from the host's store, so `grep -rl '<option>' --include='*.drv' /nix/store`
finds the generated file and the text sits in the `.drv`'s `text`/`settings`
attribute (unescape `\\n`, `\\"`). `*-users-groups.json.drv` carries each user's
`"shell"`; `*-nix.conf.drv` carries the merged `nix.conf`; `*-hm-putter.json.drv`
lists every file home-manager installs. That is how the machine's login shell,
its `accept-flake-config`, and a missing `~/.bashrc` become observable without
mounting anything. Two limits: a `.drv` proves the configuration was
*instantiated*, not that it is the running generation, and the image is a
snapshot.

Two failures this exposes, both invisible from the repo alone:

- **A home-manager shell integration is installed for a shell, not for the
  user.** `enableFishIntegration` writes a hook into `~/.config/fish/config.fish`;
  `enableBashIntegration` writes into `programs.bash.initExtra`, which only
  exists when `programs.bash.enable = true`. If `users.users.<name>.shell` is
  never set, the login shell stays bash and every fish-only hook is inert --
  direnv never runs, and `nix develop` is never wrapped by `nix-your-shell`.
- Re-fetching an input the machine already has cached can fail in the sandbox
  with a `narHash` mismatch; `--override-input <name> path:/nix/store/<...>-source`
  against the copy in the store lets evaluation proceed.

When the thing to verify lives on the machine, hand over **discriminating**
commands rather than "please check": each one's output should separate the
hypotheses, and say what each expected result means.

```console
grep experimental-features /etc/nix/nix.conf     # is the feature live in the machine's config?
nix eval --expr '1 |> (x: x + 1)'                # does the syntax actually work here?
nixos-rebuild list-generations | tail -3          # did the switch land?
clan vars list <machine> --flake .                # deep-eval canary: fails on a broken module
```

## Driving an interactive shell to test its config

A shell config cannot be validated by reading it, and `fish -c '<the line>'` runs
non-interactively, where the thing under test may not apply. Drive a real shell
in a pty.

- **`TERM=dumb` is the enabler.** With a normal `TERM`, fish's reader blocks on
  terminal-capability probes (`\x1b[?u`, `\x1b[6n`, ...) waiting for replies a
  bare pty never sends, and the keystrokes you write get consumed as probe
  responses -- nothing fires and the config looks inert.
- **Point `XDG_CONFIG_HOME` at a temp dir holding `fish/config.fish` and run
  `fish -i`.** That is what makes `fish_user_key_bindings` actually get called.
  `--no-config -C '<commands>'` does not reproduce a real session.
- **Bind the key to a marker command** (`bind <key> 'echo FIRED >> /tmp/log'`)
  and assert on the file. Include a control with no binding and a positive
  control on a printable key -- without them an empty log proves nothing.
- **Reproduce the symptom first.** The old file has to produce the user's exact
  output before the new file's silence means anything.

Three `bind` traps, each silent:

- `bind --key-names` / `-K` is a **listing mode** with its own synopsis form: it
  ignores the arguments after it and prints the key names. A line meant to bind
  prints a 31-line list at every shell start instead.
- `nul` is **not** a key name. An unrecognised word is read as that literal
  sequence of characters (`bind nul` binds `n`,`u`,`l`). The named keys are the
  arrows, backspace, comma, delete, end, enter, escape, f1-f12, home, insert,
  menu, minus, pageup, pagedown, printscreen, space and tab -- the same list
  `bind --key-names` prints.
- `-M insert` is vi's insert mode and is **inert** unless vi key bindings are
  enabled (`bind --list-modes` then reports `default` alone). Omitting `-M` means
  `default`, the mode actually in use.

For Ctrl+Space (the terminal sends NUL), only the spelling `ctrl-space` matches
the byte; `\c@` and `\x00` register a binding that lists as `''` and never fires.

## Reproduce an upstream defect against the pinned revision

An upstream bug is a claim like any other, and its fix is rarely obvious from the source.
Reproduce it in one file against the exact revisions in `flake.lock`, so the repro is a fact
about what this machine runs rather than about `main`.

- **Take the inputs from the store, not from GitHub.** Every locked input already sits at
  `/nix/store/<hash>-source`, so `builtins.getFlake "path:/nix/store/<hash>-source"` pins the
  same revision with no refetch and no change to `flake.lock`. Find the path with
  `nix eval --impure --raw --expr 'builtins.toString (builtins.getFlake "/path/to/repo").inputs.<name>.outPath'`.
- **Force the failing option, not the whole system.** `nix eval --impure --json --file repro.nix`
  over the smallest expression that reaches the defect — one node's service block, one
  `home.file` source, `config.system.build.etc` — reproduces it in seconds and prints the
  value once it evaluates.
- **Isolate by varying one input.** Set the offending option to a literal and re-run: if the
  expression now evaluates, the defect is that option and not the module around it.
- **Verify the proposed fix on a copy of the upstream source**, never by reasoning about it:
  `cp -r /nix/store/<hash>-source ./upstream-fixed`, `chmod -R u+w ./upstream-fixed`, edit,
  and point the repro flake at the copy. A store path is read-only, so a copy is the only way
  to test a patch before it exists upstream.
- **Then move the expectation into the repo's own test and mutate it until it fails**: the
  hardcoded value, the plausible-but-wrong coercion, and removing the workaround entirely. An
  assertion that survives all three is measuring nothing — the `mkForce` pitfall in `SKILL.md`
  records one that had to be deleted for exactly that reason.

## Count what the gate ran

`nix flake check` prints one line per check. **A zero count is ambiguous; name its cause.**
`running 0 flake checks` followed by `all checks passed!` usually means every check
derivation was already built for this exact source — a cache hit, not a skipped gate.
`nix eval .#checks.<system> --apply builtins.attrNames` proves the set is not empty, and
`nix build --no-link --rebuild .#checks.<system>.<name>` re-runs one for real. The vacuous
case is a selector or filter that matched nothing. Either way the evidence is the count plus
its reason; `absence is not cleanliness` belongs to `deterministic-quality-gates`.

## Report what you ran

- Name the check and its result. Do not compress several checks into "verified".
- Say plainly when a build could not be completed, and why, rather than letting a
  passing evaluation imply that it did.
- **Do not change system config to work around a verification limit.** When a
  build cannot complete for environment reasons, report the limitation and hand
  the user the command to run; editing `/etc/nix/nix.conf` or similar mid-session
  is a system change nobody sanctioned, and it can leave the environment in a
  state you did not document. Writing those files during an initial install is a
  different, sanctioned case.
- A caveat that a user must act on belongs in the summary, not only in a document
  they may not open.
