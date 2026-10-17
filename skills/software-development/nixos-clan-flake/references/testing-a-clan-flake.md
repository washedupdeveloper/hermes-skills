# Testing a clan flake

Unit assertions, VM tests, the deployability checks, the "no undeclared ports"
pair, and the gate/hook wiring. Read this before adding or debugging a test, or
before touching `modules/flake/git-hooks.nix`.

**Three tiers, and the tier is chosen by what the assertion NEEDS.** This is the
organizing rule for every test added to a repo like this:

- **eval** (`lib.runTests`) -- the *value* of an option in the evaluated
  configuration. Milliseconds, no build.
- **build** (`runCommand`) -- the *file or artifact* the configuration produced.
  Seconds. Anything that is a property of a generated file belongs here, because
  a rendered file is evidence on its own.
- **e2e** (`runNixOSTest` + `testScript`) -- what a RUNNING machine does with it:
  a daemon parsing its own config, a socket bound, a command succeeding.

Python is the price of the third tier and nothing else. An assertion that can be
made against a rendered file must not be made by booting a machine to look at it.
The practical consequence is speed: a drift in a generated file fails in seconds
instead of after a VM boot, and the VM is left to the residue that genuinely needs
a kernel. A suite whose `testScript` greps `/etc/...` for content it could have
read from `config.system.build.etc` is paying minutes for nothing.

**Testing a clan flake: `lib.runTests` for eval, clan's `clanTest` for a VM.**
`nix flake check` builds `checks`, so both belong in it. For eval-level
assertions use `lib.runTests { test_x = { expr = ...; expected = ...; }; }` --
the helper clan-core uses for its own `eval-tests`. Two contracts are easy to get
wrong: it returns a **list of failures** (`== [ ]` means pass; it does *not*
return `true`), and it only runs attributes whose name starts with `test`.
Pretty-print a failure with `lib.debug.throwTestFailures { inherit failures; }` --
**not** `lib.throwTestFailures`, which does not exist. The bare name fails with
`attribute 'throwTestFailures' missing`, so a red gate reports the REPORTER
instead of the failing test's name, expected value and result. It hides for as
long as every group passes, because the else branch only runs on a failure -- so
the one part of a green suite that has never executed is the part that explains a
red one. Read a failure on purpose before trusting a suite's red output. One
check per group beats one check for everything: `--keep-going` then reports every
failing group instead of the first.

For a VM test, clan-core exposes the test module at
`clan-core.modules.nixosTest.clanTest` -- **not** `clan.nixosTests`, which lives
in clan-core's `testModule` flake module and drags in clan-core's whole check
suite. Apply it with `pkgs.testers.runNixOSTest`, the API the nix.dev integration-testing
tutorial documents. It accepts `imports`, so `clanTest` drops straight into it:

```nix
pkgs.testers.runNixOSTest ({
  imports = [ inputs.clan-core.modules.nixosTest.clanTest ];
  defaults.imports = [ { _module.args.clan-core = inputs.clan-core; } ];
} // body)
```

`runNixOSTest` is `nixos.runTest` with `hostPkgs` and `node.pkgs` already
supplied, so **do not pass them again** -- a duplicate definition conflicts. That
is why it is preferable to hand-rolling `import (inputs.nixpkgs + "/nixos/lib")`
with an explicit `hostPkgs`: one less thing to get wrong, and it matches the
documented API rather than an internal call.

A module may be a plain attrset, so the `{ ... }:` wrapper is unnecessary (and
statix flags it as an empty pattern). `clan.directory` must be a real path -- a
directory holding the test's `default.nix`; it is copied and has generated vars
materialised into it, so `clan.core.vars.generators` work inside a test.

**A NixOS-WSL machine cannot be a `nixosTest` target.** Its
`system.build.installBootLoader` resolves to `${pkgs.coreutils}/bin/true` -- the
WSL kernel boots it -- so there is no bootloader for QEMU to start. It is not
bootable, not merely awkward to test. Apply the same modules to a plain test
machine instead, and point the test's `clan.modules.<name>` at the real module
file so the module under test is the one that ships.

**A container test needs `uid-range`; a VM test does not.** clan's harness
defaults to `useContainers = true` (nspawn, much faster). That additionally
requires nix's `uid-range` system feature, advertised only when the builder sets
`auto-allocate-uids`; nixpkgs' default `system-features` is `[ "nixos-test"
"benchmark" "big-parallel" "kvm" ]` and omits it, so the build dies with
`Required features: {kvm, nixos-test, uid-range}`. `useContainers = false` needs
only `kvm` and `nixos-test`, but rename `containers.<n>` to `nodes.<n>`. Check
`nix show-config | grep system-features` before choosing.

**`sshd -T` is the strongest e2e assertion for sshd config, with two traps.** It
is sshd's own parse of the config it will serve, so a Nix option that never
reached a file cannot satisfy it. But it exits 1 with `no hostkeys available --
exiting` when host keys are absent (run `ssh-keygen -A` first -- a no-op once
`sshd-keygen` has run), and it **echoes the config's own casing** while NixOS
writes CamelCase (`PasswordAuthentication no`), so a lowercase comparison never
matches.

**Mutation-test a new suite before trusting it.** A green suite proves nothing
about whether it can fail: break each property in turn, confirm the matching group
reports, then restore. Two traps make this weaker than it looks -- a check that
*errors* rather than failing (`lib.all` over an attrset, a predicate taking two
arguments where it takes one) looks wired and is not, and a `lib.all` over an empty
list is vacuously true, so assert the actual values too. Expect at least one
mutation to be *your* error rather than the test's: mutating `ports` inside
`services.openssh.settings` instead of as its sibling silently changed nothing, and
the "not caught" result was the mutation's fault, not the test's. Confirm the
mutation landed before concluding the test is blind.

**"No undeclared ports open" needs two layers, and they are different claims.**
At evaluation time, assert the *declared* exposure set exactly --
`networking.firewall.allowedTCPPorts` and `allowedUDPPorts` compared against a
literal list, plus `services.openssh.ports` agreeing with its firewall rule. The
value is the exactness: a new service cannot open a port without the list being
edited on purpose. In a VM, enumerate what the kernel is actually listening on
and assert nothing is reachable that the configuration did not declare. Read
`/proc/net/{tcp,tcp6,udp,udp6}` rather than `ss` -- iproute2 is not part of a
minimal system. Field 2 is `ADDR:PORT` in hex, field 4 is the state (`0A` =
TCP LISTEN, `07` = UDP bound), and the address is little-endian: an all-zero
address (`00000000`, or 32 zeros for v6) is "every interface", anything else is
not. Splitting exposed from loopback is the whole point -- loopback is not
exposure, but a new loopback listener is still worth being told about.

**clan-core enables systemd-resolved, and that is three ports.** A machine with
clan-core's networking module runs resolved, which listens on 5353 (mDNS), 5355
(LLMNR) and the loopback DNS stub on 53. That is why clan advertises udp/5353 in
the firewall. If a repository disables it -- `services.resolved.enable =
lib.mkForce false`, which NixOS-WSL needs because WSL supplies its own resolver
-- then a VM test must mirror that setting or it will report three undeclared
listeners that have nothing to do with the repository. Two consequences worth
telling the owner: a non-WSL machine in the same clan would run resolved, and
the udp/5353 firewall allow is then for a service the repo turns off.

**Assert clan deployability against `clan.nix` imported directly, not against
clan's internals.** `clanInternals.inventoryClass.machines` is the raw module
definition, not the resolved inventory, and `config.clan.inventory` per machine
exposes only `assertions`. `import ./clan.nix { inherit inputs; }` gives the
repository's own declaration -- machines, modules, `inventory.machines`,
`inventory.instances` -- which is what the checks should be about. For the
deploy artifact use `clanInternals.machines.<system>.<machine>`.

A clan role is assigned **three** ways -- `tags = [ "x" ]`, `tags.x = { }`, and
`machines.<name> = { }` -- and clan accepts all three, so a check must normalise
them or it will depend on which spelling a given instance happened to use. The
checks worth having: every instance names its `module.input`; every `self`
instance names a module the repo defines; every role is assigned to something (a
role with no tags and no machines never applies and nothing says so); every role
tag is carried by some machine; every role's machine exists; every machine is in
the inventory and carries a tag.

**A module function argument with a default is not optional.** `{ username ?
null, ... }:` in a module does **not** give you an optional argument: the module
system resolves a formal from `_module.args` and errors with `attribute 'x'
missing` when it is absent, bypassing the Nix-level default. So a
`lib.mkIf (arg != null)` guard on such an argument can never be false -- the
default is dead code and the guard is always true. To make the optionality real
the default has to live in `_module.args`. This bites hardest in clan service
modules, where a per-machine `_module.args.<arg>` is the only thing that
supplies it.

**nixpkgs ships ~1500 assertions and a warnings channel; both are free.**
`config.assertions` filtered on `!a.assertion` gives the failed ones with their
own messages, and `config.warnings` is a plain list. A warning does not fail a
build, so nothing else in a gate would catch a deprecation or a
misconfiguration. Asserting both are empty is a few lines and covers ground no
hand-written test reaches.

**Verify a mutation APPLIED before concluding the test is vacuous.** `perl -0pi -e
's|a|b|'` reported success and changed nothing in one repo, so a real mutation read
as "the check did not fire". After mutating, grep for the new text and print it;
if the tool is unreliable, use the editor's patch operation, which reports a diff
or refuses. A mutation that silently no-ops is indistinguishable from a vacuous
assertion once you are filtering build output for `FAIL`.

**A verification loop whose `if` tests a PIPELINE reports success regardless.**

```sh
# WRONG -- the condition is `tail`'s status, which is always 0
if nix build .#checks.$c 2>&1 | grep -E 'FAIL|error' | tail -6; then :; else fail=$((fail+1)); fi
```

That loop printed `### FAILURES: 0 ###` over a run in which every check had
failed. It is the worst kind of false green: the exact shape a human writes to
*prove* a gate is red, reporting clean. Test the command, not the pipeline:

```sh
nix build .#checks.$c >/tmp/out 2>&1; status=$?    # sound
set -o pipefail; nix build ... | tail -6; status=${PIPESTATUS[0]}   # sound
```

Two corollaries, both measured:

- **`nix build --rebuild` is the wrong tool for a check that never built.** It
  errors `some outputs ... are not valid, so checking is not possible` -- a falsy
  failure that reads like a broken check. Drop `--rebuild` for a fresh build; the
  derivation is new, so a plain build already executes it.
- **`nix flake check` prints `running 0 flake checks` when every result is
  cached, then `all checks passed!`.** A green summary over zero executions is
  not evidence anything ran. Force re-execution per attribute and say which mode
  produced the verdict.

**A check that asserts "X is discovered" must know the product's own filters.**
When a discovery check reports something missing, look for a declared relevance
gate before calling it a defect: an `environments:`-style filter is an *offer-time*
rule, so an entry gated to `[s6]` is CORRECTLY absent on every host that is not
one. Teach the check the gate and assert both directions -- an ungated entry that
is absent fails, and a gated entry that IS offered also fails, or the gate is
decorative. Deleting the filter to make the check pass breaks the product to
satisfy the test, which is the one repair that must never be chosen.

**A comparison loosened for display truncation must loosen in exactly one
direction.** A listing column truncated with an ellipsis makes a LISTED name a
prefix of the real one, so `listed.startswith(expected)` is the only valid
tolerance. Writing it as `expected.startswith(listed) or listed.startswith(expected)`
makes the check vacuous: a skill renamed `caveman-renamed` then satisfies
`caveman`, which is precisely the drift the check exists to catch. Prove it with a
rename mutation, not by reading the code.

**Parsing a human-readable table needs a shape check on the parsed rows.** A
multi-line cell emits continuation rows whose first column holds a box character;
counted as records they inflate the total and hide a missing entry. Require every
parsed name to match the identifier's shape (a slug regex) and cross-check the
count in BOTH directions against what was expected.

**A `runTests` group fails as an EVAL ERROR when an assertion's `expr` throws, and
that error wins over every named failure in the group.** Asserting a nested key
(`home.file."<path>".source`) means a renamed path produces
`error: attribute '"<path>"' missing` and the group never reports which test
failed. Split it: assert the KEYS with `builtins.attrNames` (a clean failure with
both values), then the VALUE with `... or null` so a missing key reports as a
failed test instead of aborting the group. Measured: a drifted link path failed
three named tests once both were in place, and only an opaque eval error before.

**A Nix build sandbox has no `/usr/bin/env`, so a script whose shebang is
`#!/usr/bin/env bash` cannot be spawned at all.** The error is
`FileNotFoundError: [Errno 2] No such file or directory: '<the script>'` -- it
names the script, not the interpreter, so it reads as a missing file in a tree
where `ls` shows the file. `patchShebangs $out` fixes a copied tree, but it only
rewrites the FIRST line of each file: a stub created inside a heredoc keeps its
`#!/usr/bin/env bash` and still fails. A second targeted
`sed -i -E "s|^#![[:space:]]*/usr/bin/env[[:space:]]+bash\$|#!${pkgs.bash}/bin/bash|"`
on the copy fixes that one, and it belongs in the CHECK's copy rather than the
repo's test -- the sandbox limitation is the harness's, not the test's.

**A build tier needs a REAL consumer. Do not simulate the artifact.** The build
tier is worth having when something actually copies or packages the tree: build the
artifact that consumer produces -- marker file plus its support directories -- and
assert self-containment against it. Every pointer must resolve INSIDE the shipped
directory, and none may climb out with `../`: that rule is the one a source-tree
check cannot make, because `../x` resolves in the source and breaks once the
directory ships alone. Pair it with a count parity between source and artifact so a
copier that silently drops an entry fails too.

**But check that the copier exists before building one.** If delivery is a live
read -- an app pointed at the tree through an extra search path, with no copy, no
symlink and no installer -- then there is no artifact, and a check that simulates
one is testing fiction. It will pass forever while proving nothing about the
product, which is worse than having no middle tier: it spends the trust a real test
earns. Say plainly that the repo has no build tier and why. The one rule worth
keeping from it (`../` escapes) moves down into the source-tier pointer test, next
to the write-verb heuristic it needs.

**An untracked file is the most common cause of a build-tier failure that looks
like a content bug.** A skill pointing at `references/new-file.md` that exists on
disk but was never `git add`ed fails the artifact check with a path `ls` confirms is
present, because the store copy carries tracked files only. Report it as the git
problem it is -- `git status` first, `git add` the fix.

**`nix flake check` already runs the pre-commit hooks, via `checks.pre-commit`.**
git-hooks.nix's `check.enable = true` makes `checks.pre-commit` a derivation that
does `git init` in a temp dir, commits, and runs `pre-commit run --all-files`
(or `--hook-stage manual --all-files` when *every* hook's stage is `manual`).
So one command covers the linters, the machine toplevel, the topology and any
`checks` the tests contribute. You rarely need a second command.

**A `pre-commit`-stage hook that runs `nix flake check` calls itself.** The gate
runs the hooks, so a hook in the default stage runs *inside* the gate; if that
hook is `nix flake check`, the gate invokes the gate, and the nested build waits
on a derivation the outer one is already building. Guard the entry:

```nix
entry = ''
  sh -c 'if [ -n "$NIX_BUILD_TOP" ]; then exit 0; fi; exec nix flake check'
'';
```

`NIX_BUILD_TOP` is set inside a Nix build and unset in a shell -- **measured**.
`IN_NIX_SANDBOX` is the obvious-looking signal and is **unset even in a
sandboxed build** on current Nix, so it cannot be used. Keeping the hook at
`pre-push` also avoids the recursion but means the gate never runs on commit.

**A hook added to `git-hooks.nix` is written down and never installed.**
`.pre-commit-config.yaml` is a symlink into the store, and `.git/hooks/*` are
written only by git-hooks.nix's install script, which the devshell startup
runs. Editing `git-hooks.nix` without re-entering the devshell leaves the
installed config pointing at the *previous* store path: the new hook exists in
the file, does not exist in `.git/hooks`, and runs never. This is silent -- a
`pre-push` hook sat inert this way for weeks. `nix develop --command true`
reinstalls, and it is worth diffing `readlink -f .pre-commit-config.yaml`
against the file's hooks whenever a hook seems not to fire.

**`nix flake check` does see uncommitted work**, so a pre-commit hook validates
the right content -- verified by introducing a real violation and watching the
gate fail both unstaged and staged. Budget for the cost, though, because a
changed tree means rebuilt checks. Measured on one machine, warm store:
nothing ~45s, a comment ~45s, a changed system closure ~49s, a changed *shared
module* (which the VM tests apply, so their nodes rebuild and both VMs re-run)
~114s. A minutes-long commit loop is a real cost; say the numbers out loud
rather than promising "it's fast".

