# Testing a clan flake

Unit assertions, VM tests, the deployability checks, the "no undeclared ports"
pair, and the gate/hook wiring. Read this before adding or debugging a test, or
before touching `modules/flake/git-hooks.nix`.

**Testing a clan flake: `lib.runTests` for eval, clan's `clanTest` for a VM.**
`nix flake check` builds `checks`, so both belong in it. For eval-level
assertions use `lib.runTests { test_x = { expr = ...; expected = ...; }; }` --
the helper clan-core uses for its own `eval-tests`. Two contracts are easy to get
wrong: it returns a **list of failures** (`== [ ]` means pass; it does *not*
return `true`), and it only runs attributes whose name starts with `test`.
Pretty-print a failure with `lib.throwTestFailures { inherit failures; }`. One
check per group beats one check for everything: `--keep-going` then reports every
failing group instead of the first.

For a VM test, clan-core exposes the test module at
`clan-core.modules.nixosTest.clanTest` -- **not** `clan.nixosTests`, which lives
in clan-core's `testModule` flake module and drags in clan-core's whole check
suite. Apply it with `nixosLib.runTest`, the call clan-core makes itself:

```nix
nixosLib = import (inputs.nixpkgs + "/nixos/lib") { };
nixosLib.runTest ({
  imports = [ inputs.clan-core.modules.nixosTest.clanTest ];
  hostPkgs = pkgs;
  defaults.imports = [ { _module.args.clan-core = inputs.clan-core; } ];
} // body)
```

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
about whether it can fail: break each property in turn and confirm the matching
group fails, then restore. `lib.all` over an attrset, or a predicate taking two
arguments where it takes one, both *error* at evaluation rather than reporting a
failure -- the suite looks wired and is not. Assert the *actual* values too: a
`lib.all` over an empty list is vacuously true.

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

**Prove a new suite can fail before trusting it.** A suite that passes on the
first run has demonstrated nothing -- mine did, and mutation testing then found
two of its groups were only accidentally correct. Break each property in turn,
confirm the matching group fails, and restore. Expect at least one mutation to
be *your* error rather than the test's: mutating `ports` inside
`services.openssh.settings` instead of as its sibling silently changed nothing,
and the "not caught" result was the mutation's fault, not the test's.

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

