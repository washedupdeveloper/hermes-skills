# Adding a machine to a clan

Growing a clan from one machine to several. Every fact here was measured against a
pinned clan-core; each one is a failure that produces a machine which *evaluates*,
so the gate is the only thing that turns it into an error.

## How clan finds a machine

`modules/clan/module.nix` turns a directory into a machine:

```nix
inventory = lib.optionalAttrs (clanLib.fs.pathExists "${directory}/machines") {
  imports = lib.mapAttrsToList (name: _t: {
    _file = "${directory}/machines/${name}";
    machines.${name} = { };
  }) (lib.filterAttrs (_: t: t == "directory") (clanLib.fs.readDir "${directory}/machines"));
};
inventory.machines = lib.mapAttrs (_n: _: { }) config.machines;
```

So **the directory is the machine**, and `inventory.machines` is derived from
`config.machines`. A directory plus one `machines.<name>` entry for its
`_module.args` is enough: the machine evaluates, carries the account and its home,
and reads back `[ "all" "nixos" ]`. Read the pinned source rather than the website
when this matters -- the site documents `inventory` first and invites the opposite
conclusion.

## The reserved tags

`all` and `nixos` are added to **every** machine by clan. Measured: a machine
configured with `tags = [ "pi" ]` reads back `[ "pi" "all" "nixos" ]`.

That makes `roles.default.tags.all = { }` the correct way to give every machine a
service -- including future ones -- with no per-machine edit and no tag to remember.
The alternative, `roles.default.machines.<name> = { }`, is the shape that produces a
machine which builds, boots, and has no account or no dotfiles.

## The vars store is a build prerequisite, not a tidy-up

`clan vars generate <name>` is **required before the toplevel will build**. The
failure is legible, which is the one mercy here:

```text
error: File 'ssh.id_ed25519.pub' at 'per-machine/<name>/openssh' does not exist.
       Try running 'clan vars generate' first.
```

A settled machine carries roughly eleven files across five generators --
`state-version`, `openssh` (host key), `openssh-cert`, and one `user-password*` pair
per account -- plus one pair per service that machine runs. The secrets are
sops/age-encrypted at rest (`{"data": "ENC[AES256_GCM,...`), so committing `vars/`
is correct and is what clan expects.

Do not hand-write these. `state-version` can be emulated for an experiment (its value
is the fleet's pinned release); the key material cannot, and a machine whose
`state-version` you emulated but whose host key is missing will pass every eval-tier
group and fail the toplevel build. That gap is the reason an "all groups pass" result
is not evidence a new machine works -- build `nixos-<name>`.

Skipping `state-version` alone is the quieter failure: the machine silently takes
nixpkgs' current release instead of the fleet's pinned one, and `stateVersion` is the
one setting that must never move on an existing machine.

## Where a machine's topology entry goes

`topology.self` in the machine's **own** config, not in the repo's `topology.nix`.
That file holds only the non-NixOS devices -- the router, the host, the uplink --
because machines are derived from their own config. Without `topology.self` the
machine still renders as a node, an empty one attached to nothing, so only an
assertion catches it:

```nix
topology.self = {
  parent = "home-router";          # required; assert it exists
  interfaces.eth0 = {
    network = "lan";               # must be a network topology.nix defines
    addresses = [ "192.168.68.110/24" ];
  };
};
```

## Two failures that do not name their cause

- **An untracked `machines/<name>/`.** Nix sees tracked files only, so the directory
  is absent from the eval and the machine fails with `Neither nixpkgs.hostPlatform
  nor the legacy option nixpkgs.system has been set` -- which reads as a missing
  setting, not a missing file. `git add` the directory first.
- **An architecture missing from `systems`.** `systems` is the build contract, not a
  wish list: every `perSystem` output is expected to evaluate for each entry. A Pi
  needs `aarch64-linux` added there before the machine can be built at all, and
  `test_every_machine_runs_on_a_declared_system` is what says so.

## Declare the inventory entry even though clan would derive it

Clan derives `inventory.machines` from the directory, so an explicit entry is
redundant to clan -- and still required by a repo whose checks read the
**declaration**. That is the right design: an assertion against clan's *derived*
inventory can never fail, so it proves nothing. Keep the explicit entry, put the
machine-specific facts there (extra tags, `description`, `deploy.targetHost`), and
when a reader deletes it after reading clan's source, the gate tells them.

## Assertions must be fleet-shaped, or the second machine fails for existing

This is the part that has to be fixed *before* the second machine arrives, because
the naive spellings are all one-machine-shaped:

```nix
# WRONG -- asserts "there is exactly one machine, and it is workstation"
expr = lib.unique (lib.map (m: m.config.networking.hostName) named);
expected = [ "workstation" ];

# RIGHT -- asserts the property, for any number of machines
expr = lib.all (m: m.config.networking.hostName == m.name) named;
expected = true;
```

The per-machine map (`lib.mapAttrs (_n: m: ...) machines` compared to a literal
`{ workstation = [ "x" ]; }`) and the per-user list (`[ [ true true ] ]`) have the
same defect, and it is worse than a failure: the fix a reader reaches for is to add
a second row, which disables the assertion for the machine they just added.

Convert to `lib.all (...) named` / `lib.all (...) hmUsers` with `expected = true`,
or to a `subtractLists` against the declared set with `expected = [ ]`. Two
assertions worth having that the fleet shape makes possible:

- **one home per machine** -- `builtins.length hmUsers == builtins.length named`,
  which catches a machine that lost its importer, something a per-user list cannot
  see;
- **a normal user per machine** -- `(users.users.<name> or { }).isNormalUser or false`,
  **not** `users.users ? <name>`. The attribute exists on every machine regardless,
  because the base module assigns `users.users.<name>.shell` for the login shell, so
  the existence test is vacuous and passes the exact case it was written for.

And delete the homogeneity assertion (`every machine is x86_64-linux`). It forbids
the heterogeneous machine you are adding, and it duplicates the declared-systems
check.

## The procedure

1. `machines/<name>/configuration.nix` -- `networking.hostName` equal to the machine
   name, `nixpkgs.hostPlatform`, `topology.self`.
2. `clan.nix`: `machines.<name>._module.args.username`, and
   `inventory.machines.<name>` with its tags, `description`, and
   `deploy.targetHost` if it is remote. `workstation` has no deploy block on purpose
   -- it is self-managed and it is where the command runs.
3. `git add` the new directory.
4. `clan vars generate <name>` then `git add vars/`.
5. Add the architecture to `systems` if it is new.
6. `nix flake check --keep-going`, then build `nixos-<name>` -- the gate builds every
   machine's toplevel, so an eval-clean machine that cannot build still fails there.

Expect the gate to fail on the first run; that is the design working. The groups are
separate checks that run in parallel, so there is no "order" — read them together. What
each one catches: `clan` -> the inventory entry and the tag; `system` -> the normal user,
the state version, the host name and the declared system; `home` -> one home per machine;
`structure` -> `topology.self` and the networks it names.

## What is NOT proven by any of this

A machine that evaluates, carries its vars and builds is ready to *install*; it is
not evidence that `clan machines update` can reach it. Deployment needs
`deploy.targetHost` on the target and has to be executed once to be believed. Say
which of the two you measured -- building is the half that can be proven locally.
