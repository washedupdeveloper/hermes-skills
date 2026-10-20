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

## A machine on new hardware: the support arrives as a module

Clan builds each machine itself -- `modules/clan/module.nix` calls
`nixpkgs.lib.nixosSystem` and passes `specialArgs = { inherit clan-core; } //
clan.specialArgs` -- so an upstream flake that ships its own system-builder helper
cannot be used at that seam. Board support (a vendor kernel and firmware, the
bootloader options for a single-board computer) is therefore consumed as **modules
plus a specialArg**:

```nix
# flake.nix
clan.specialArgs.<support-flake> = inputs.<support-flake>;

# machines/<name>/configuration.nix
{ <support-flake>, ... }: {
  imports = [ <support-flake>.nixosModules.<board>.base ];
}
```

The helper that applies that flake's *global* overlays is unreachable from clan's
call site, so what the base module takes from its own flake -- kernel packages,
firmware, the options it defines -- is something to read in the pinned source rather
than infer from the helper's documentation. The same rule covers any module that
expects a `specialArg`: the module is what arrives, the arg is how it finds its flake.

Check whether that module provisions the firmware partition **on activation**. Where
it does, an install needs no hand-prepared image and a deployment tool can run the
whole thing non-interactively; where it does not, the card is a manual step and
saying so is part of the answer.

## Reading a service's interface from the pinned store

An instance is written against `manifest.name` and the role's interface, so read both
from `clanServices/<name>/default.nix` in the store path `flake.lock` pins:

```nix
manifest.name = "clan-core/mycelium";  # the instance says module.name = "mycelium"
roles.peer.interface = { openFirewall; addHostedPublicNodes; };
perInstance = { settings, mkExports, machine, ... }: { ... };
```

Three things to lift from it before writing the instance:

- **the options the role actually exposes**, which live in `interface` -- a setting
you invented from the prose is a silently ignored key;
- **what it generates and exports** -- `clan.core.vars.generators.<gen>` and its
  `files.*.secret` flags say which values are secret, and `exports` says what other
  machines may read (a peer's overlay address, for instance);
- **what it already sets**, so your config adds to it instead of fighting it.

Instances then use the shape the built-in ones do: `module.name = "<name>"` with
`module.input = "clan-core"`, and a local module must say `"self"` because
`"clan-core"` is the default. Assign roles by tag so a machine added later joins with
no edit.

**An overlay's public nodes are discovery and NAT traversal, not reachability.** A
peer that is switched off stays unreachable however many public nodes exist, which is
why a roaming machine needs at least one always-on peer at home. Two design
consequences: that peer is a machine's whole justification, and a roaming machine's
`deploy.targetHost` has to be its overlay address rather than a LAN name, which is
wrong the first time it leaves the house.

## A machine from a template, so the skeleton cannot forget

Clan reads machine skeletons from `clan.templates.machine.<name>` in the clan module, and
applies one with either spelling:

```bash
clan machines create <name> --template <template>     # writes machines/<name>/ AND the inventory entry
clan templates apply machine <template> <name>        # an alias for the same call
```

Two properties decide what a skeleton can do. **It is a plain directory copy** -- clan
substitutes nothing in a machine template, unlike disk templates which take `--set` for
their `{{placeholders}}` -- so a skeleton knows nothing about the machine's name and must
derive what it can: `networking.hostName = config.clan.core.settings.machine.name` cannot
disagree with the machine's name, whereas a hand-typed string can and does. **And clan
then writes `inventory.json`** for what it creates, while a repo whose checks read its
`clan.nix` declaration still needs that block: the file speaks for the keys it carries and
clan merges both.

A skeleton is the right place for the two lines a copied file forgets -- the platform and
`topology.self` -- and for nothing the machine should decide. Keep the platform in a
`platform.nix` the skeleton imports: the repo's own assertion over `systems` can then read
the same file, which is what lets a flake declare a system *before* the machine that will
use it exists. Putting the platform back into the assertion as a literal is a second copy
and drifts.

## Building another machine's architecture on the host you have

Adding `aarch64-linux` to `systems` is only half the contract: the gate BUILDS what it
asserts, and without a builder for that platform nix refuses with `a 'aarch64-linux' ... is
required to build ... but I am a 'x86_64-linux'`. `boot.binfmt.emulatedSystems = [ ... ]` on
the x86_64 machine closes it -- qemu-user through the kernel's binfmt_misc, with the module
also adding the platform to `nix.settings.extra-platforms`. Measured on an x86_64 host with
the aarch64 leg enabled: the same rebuilt check takes **8.6 s against 8.3 s native**,
because that leg is evaluation and trivial builders; a compiling build pays for the
emulation in full.

- **`nix flake check` builds the CURRENT system's checks only.** The other leg is
  `--all-systems`, and a repo whose hook runs the bare command is not gating the emulated
  architecture at all.
- **Gate the VM tier off an emulated leg.** `runNixOSTest` boots a QEMU guest of the
  system under test, so on aarch64 it would be qemu-user running qemu-system-aarch64:
  nested emulation, minutes per test, and no claim about the other board. `lib.optionalAttrs
  pkgs.stdenv.hostPlatform.isx86_64` around the e2e checks is the whole fix.
- **Under WSL, `systemd-binfmt` works, and the flush error is a warning.** A host that
  disables it "because binfmt_misc's status file is read-only" is repeating a claim worth
  re-measuring: it applies `/etc/binfmt.d/nixos.conf` and exits 0, while the flush of
  pre-existing rules fails with EROFS. Two consequences -- enabling it makes
  `wsl.interop.register = true` load-bearing (WSLInterop must stay declared in binfmt.d or
  `.exe` execution is at the mercy of that flush; verify with `cmd.exe /c echo ok` after the
  switch), and the emulated interpreter lands as `/run/binfmt/<system>`.

## When a service joins the fleet, the ports assertions fail -- and that is the point

Enabling a service that opens a firewall port turns the `ports` unit group red, because
that group enumerates the fleet's declared exposure in full on purpose. Read the failure as
a list, then edit the expectations deliberately with the port's reason next to it.
Measured example: clan-core's mycelium instance adds **TCP 9651 and UDP 9650/9651** (its
nixpkgs module writes them straight into `networking.firewall` rather than exposing them as
options, so an assertion can only see them by restating the numbers). The bare-port
assertion is worth keeping as "the only bare ports have a reason" -- a service whose
listener cannot be scoped to one interface (sshd, an overlay) is a decision, and the test
should make someone write it down.

## The procedure

1. `clan machines create <name> --template <template>` -- or write
   `machines/<name>/configuration.nix` by hand; the skeleton carries the platform, a
   hostname derived from the machine's name, `topology.self`, and (for bare metal) a
   bootloader.
2. `clan.nix`: `inventory.machines.<name>` with its tags, `description`, and
   `deploy.targetHost` if it is remote. `workstation` has no deploy block on purpose
   -- it is self-managed and it is where the command runs. Nothing per-machine is needed
   for `username` or any other global: those go in `clan.specialArgs` once, and a machine
   that needs module args is a sign they should have been global.
3. `git add` the new directory.
4. `clan vars generate <name>` then `git add vars/` -- scoped to the generator you added
   where possible, and never `--regenerate` unless rotation is intended. Prove nothing
   else moved by hash-diffing `vars/` before and after; clan commits the new files itself.
5. Add the architecture to `systems` if it is new -- and see the emulation section above
   for the builder that platform needs.
6. `nix flake check --all-systems --keep-going`, then build `nixos-<name>` -- the gate
   builds every machine's toplevel, so an eval-clean machine that cannot build still
   fails there.

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
