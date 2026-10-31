# Pitfalls

Each bullet is a measured failure from a real tree, not a caution. Read the one that
matches what you are about to do, before you do it.


- **Experimental features and modern syntax:** the bootstrap rule (a `|>` written in `flake.nix` itself can never be self-enabled, but one in an **imported** module can -- so set `nixConfig.extra-experimental-features` and do not argue against it), the literal-attribute-set rule for `flake.nix` and `nixConfig`, `|>` semantics, which features are worth enabling, and the `nix.settings.experimental-features` concatenation/`mkDefault` trap are all in `references/nix-experimental-features.md`. Read it before enabling a feature or writing a pipe.

- **`nix flake check` and `nix eval` WRITE `flake.lock` into the tree they run against.**
  Any tool that runs nix over a user's repository must pass `--no-write-lock-file`, or a
  "read-only" review leaves a new untracked file in the working copy — and if the target
  is a fixture whose own hashes you pin, the next run scores a tree you silently changed.
  The flag must follow the **subcommand**: `nix flake check --no-write-lock-file` is
  accepted, `nix flake --no-write-lock-file check` fails with `unrecognised flag`. Inject
  it at the one place every nix invocation funnels through rather than at each call site,
  and test both halves — flag present and positioned, and non-nix commands untouched.
- **`lib.mkForce` on a *sub-attribute* stops the overridden definition's thunk from being
  evaluated — that is how a broken upstream extractor is worked around without copying it.**
  Measured: nix-topology's mosquitto extractor builds `details = … "${l.address}:…"` and dies
  on a `null` address; forcing `topology.self.services.mosquitto.details` alone made the
  error disappear while the extractor's `name`, `icon` and `id` still came from upstream —
  the discarded definition was never evaluated. Forcing the whole service instead restates
  every field and loses the rest. Verify the scoping claim by removing the override and
  watching the original error return; do not assume `mkForce` suppresses evaluation.
  **Say which level you are forcing, because only one of them works.** Measured on
  `types.attrs`: `service.details = mkForce { … }` discards the upstream definition whole —
  its `throw` never runs and `service.name` / `service.icon` still come from upstream —
  while `service.details.host = mkForce …` changes nothing at all: `host` keeps upstream's
  value and the throw still fires, because an `attrs` value merges shallowly and priority is
  resolved at the `details` option, not inside it. `attrsOf` does accept the per-key force,
  but a `throw` sitting in a sibling key of the same definition is still evaluated. And do
  not force blind when checking this: **`nix eval --expr` is lazy**, so it prints `«error:
  …»` placeholders *inside* an attrset instead of failing, and an unforced read looks like
  the override did nothing — pass `--json` to force the whole value.
  Two corollaries: **`toString null` is `""`, not `"[::]"`**, so "use `toString` on both
  sides" is a different fix from a null conditional and renders `:1883` — pin the displayed
  value in a test, or the two look equivalent; and **an assertion whose subject is derived
  from an attribute key can never fail** (the service's `id` comes from the attrset key, so
  a test that forcing the whole service "drops the id" passes under every mutation). Watch
  each new assertion fail once, and delete the ones that do not.
- **A flake input's `ref` is `null` after resolution, so a package built from a flake
  cannot know its own version.** `inputs.x.ref` and `inputs.x.rev` are both discarded for a
  tag or branch URL — measured: `inputs.ha.ref` is null with `url = "github:o/r/v1.2.3"`,
  while `rev` holds the resolved commit. A package whose flake takes `version ? "0.0.0"`
  therefore reports `0.0.0` forever. The tag survives only in `flake.lock`'s
  `original.ref`, and `outputs` can read it back — `builtins.fromJSON (builtins.readFile
  ./flake.lock)` — then pass it as the version override. One fact, and bumping the release
  is one edit. Do not restate the version beside the URL; the two drift, and a silently
  wrong version is worse than none. Pin a **tag** rather than a rev when the label
  matters: `nix flake update <input>` re-resolves the tag to the same commit (verified
  byte-identical lock), so it stays an exact pin with a readable name.
  **A branch URL is also an exact pin** — `locked.rev` is what every rebuild reads, so
  `main` moves only when `nix flake update <input>` runs — and it is the right choice when
  the ask is "latest" rather than "labelled": the price is the version string, which falls
  back to `0.0.0` with the commit as the only identity. Say that price out loud instead of
  letting the user discover it; it is a trade, not a defect to paper over with a fabricated
  version.
- **An overlay cannot move a package onto another nixpkgs; only the input's
  `nixpkgs.follows` can.** Upstreams frequently publish an overlay that is a *pure alias* for
  the package their own nixpkgs built — hermes-agent's `nix/overlays.nix` says exactly that —
  so `nixpkgs.overlays = [ flake.overlays.default ]` hands back the same frozen derivation
  and changes nothing. To build it against the machine's nixpkgs, set
  `inputs.<flake>.inputs.nixpkgs.follows = "nixpkgs"` and expect a local rebuild: the
  derivation stops matching the binary cache, and the cost is real (hermes-agent: 157
  derivations). Read the built wrapper's `HERMES_PYTHON` and PATH store paths to prove which
  nixpkgs won — the flake evaluating says nothing about that. A `git+file://` profile entry
  then moves with `nix profile upgrade <name>`, which re-evaluates the tree's `flake.lock`
  and leaves the lock itself untouched. For cost — closure size done right, what a cold
  runner must build, and how to decide a structure change — read
  `references/flake-cost-and-structure.md`.
- **A nix-built CLI cannot find the working tree from `__file__`.** The installed command
  is a launcher into a store copy of the package, so `Path(__file__).parent.parent` is a
  `/nix/store/…` path — and a shipped tree deliberately carries no build metadata
  (`pyproject.toml`, `CHANGELOG.md`), so a tool that resolves its repository that way
  fails with `FileNotFoundError` on a file the user is looking at. Resolve the root from
  **CWD then upwards**, offer `--repo <path>` to override, and keep the module's own
  location only as the last resort — which is exactly right for a sandboxed nix check
  that runs the file from a copy of the tree it should inspect.
- **A store copy makes an experiment measure the OLD code only when the launcher's store
  path is FIXED.** Editing a module in the working tree and re-running a launcher that was
  installed or pinned earlier gives you the build from *before* the edit — it execs a store
  path, not your file. Unlike the `__file__` case this raises nothing: the command runs,
  prints plausible output, and the numbers match the pre-edit run, so an A/B reads as "my
  change had no effect" and the natural next move is to doubt the change rather than the
  harness. The tell is exactness — a result matching the previous run to the decimal is a
  stale build, not a null result. Run the module from the working tree instead
  (`python3 scripts/<mod>.py …`, plus whatever dispatch guard the CLI sets for direct
  invocation), or rebuild before re-measuring.
  **Which launchers are affected is measurable, so measure it rather than assuming.** It
  applies to `nix profile install`, a pinned wrapper, or a store path captured in a
  variable. It does NOT apply to `nix develop -c <launcher>`: that re-evaluates the flake
  per invocation and, for a dirty tree, rebuilds from the working tree. Measured: a marker
  prepended to the framework's own `council.py` appeared in the store path the devshell
  launcher then exec'd (`grep -c MARKER <that path>/scripts/council.py` -> 1), so the edit
  was live. Two ways to get this wrong, both hit while checking it: read the launcher's
  store path instead of the file it execs, and conclude "stale" from a run that failed for
  an unrelated reason — a marker inserted above `from __future__ import annotations` is a
  `SyntaxError`, which looks exactly like a launcher ignoring your edit.
- **Comments inside a `writeShellScript` / `runCommand` body are part of the derivation text**, so a comment-only edit there changes the store path and everything downstream of it (a systemd unit's `ExecStart`, the home-manager generation, `/etc`, `system.build.toplevel`). Consequences: (a) do not claim "the derivation is byte-identical" for a change that touches a script body -- check where the comment sits first; (b) when the derivation *does* move for a comment-only edit, prove the cause by swapping just that file back and forth and re-evaluating, rather than assuming something functional changed. Comments in a plain module (not a string) do not affect any derivation, which is why a flake refactor can leave `system.build.toplevel` byte-identical while a script comment cannot.
- **`nix flake check` silently skips outputs it does not recognise.** It knows a fixed set of output names; anything else prints `warning: unknown flake output '<name>'` and is *not* evaluated. A broken `topology`, `clan` or `clanInternals` output therefore passes the check untouched -- infra carried a `topology` output that had never once evaluated, and the only visible symptom was a dangling `result` symlink. Pair every custom output with a `checks.<system>.<name>` entry pointing at it, so a regression fails the check instead of waiting to be discovered. Two corollaries decide whether a **build output** is verified at all:
  - **A check must BUILD the artifact, not merely name it.** Until a check builds it, the artifact is verified by whatever separate workflow builds it and by nothing else — so "it is a pure derivation, it must be fine" is inference, not evidence. A `dockerTools.buildLayeredImage` output is a gzipped tarball, so building it needs **no docker daemon** and can be an ordinary `runCommand` (`test -s ${mkContainer pkgs}`), which is what lets the image be covered by the gate; a test needing KVM or a daemon cannot be, and stays a manual `nix build .#<name>`. Where a build is cheap and daemonless, prefer the check and let the separate workflow do only what a check cannot (publishing).
  - **Checks run only for the systems in `systems`.** A declared system with no job that exercises it is an unverified declaration: run the gate on a matrix over the systems you claim, or the platform support is an assertion nothing tests. **A matrix is not the only option, and often not the right one.** `nix flake check --all-systems --no-build` evaluates every declared system on ONE runner and builds none, so a platform-specific *evaluation* error fails for free. Confirm the command is not vacuous before relying on it: a canary check referencing Linux-only `pkgs.systemd` made `--all-systems --no-build` exit 1 while a plain `nix flake check` exited 0. That covers the declaration; *building and executing* on the platform is the part a matrix buys — and where that costs 10× minutes on a platform the author does not use, say so explicitly and leave the user the one command that settles it (`nix flake check`, the same one CI runs) rather than paying for a runner to assert something nobody asked to have asserted. Confirm which system a runner actually *is* before declaring one — `macos-latest` is arm64, so the attribute is `aarch64-darwin`, and a system can fail to evaluate outright because nixpkgs dropped it upstream (`x86_64-darwin` errors with "Nixpkgs 26.11 has dropped support for x86_64-darwin"). Prove the attribute resolves before adding it: `nix eval .#toolchain --system <system>`, then `nix build .#toolchain --system <system> --dry-run` to see whether CI fetches it or compiles it.
- **Which `config` you are in.** A clan module that only pulls in `homeManagerModules.default` is evaluated as a **NixOS** module, so `config` is the NixOS config: `config.services.hermes-agent` does not exist there and fails with `attribute 'hermes-agent' missing`. Home-manager's options are reachable one level down, at `config.home-manager.users.<name>.services.hermes-agent.<option>`. Read them from there instead of hardcoding the default, and remember that `home.file` belongs *inside* the `home-manager.users.<name>` attribute set — that subtree is an HM module, so HM options are valid there and nowhere else in the file.
- A repo with no `flake.nix` must be an input with `flake = false`; reaching for `inputs.x.packages` on it fails evaluation. Reach into it as a path: `inputs.x + "/skills"`.
- **`users.mutableUsers` defaults to `true`, so an imperative `useradd` survives every switch, forever.** In that mode activation only *ensures* declared users exist; it never removes one added by hand, and `nixos-rebuild switch` will not touch it. A user created for a test or experiment therefore persists indefinitely together with its home, its `subuid`/`subgid` ranges, and everything it owns — and a config that declares no `users.users` at all (a bare `wsl.defaultUser` only) has nothing that will ever reconcile it away. Fix by declaring the account in `users.users.<name>` with `isNormalUser`, or by removing the one-off explicitly with `userdel -r`; `mutableUsers = false` makes the config authoritative over `/etc/passwd` but is a larger behavioural change than it looks. Auditing a host for what a switch did *not* remove is `nixos-clan-flake`'s job — `journalctl | grep -E 'useradd|groupadd'` names the user, uid, home, shell and creating process, and `awk -F: '$3>=1000' /etc/passwd` lists every interactive account.
- home-manager **refuses to clobber** an existing real file or directory at the link path. Remove a prior imperative install of the same name before switching.
- Filter non-artifact siblings explicitly. Upstream repos mix the loadable directories with tooling (`registry.json`, `*.mjs` build scripts, `native/`, `generated/`). Requiring `<child>/SKILL.md` excludes all of them in one rule — do not enumerate them by name.
- Some upstream entries are always-on prompt packs rather than on-demand units. Installing them as loadable units changes their behaviour; the selection option is what lets the user exclude them.
- Do not guess at the user's flake. If the tool sandbox cannot read their flake tree, hand over the module plus the input snippet and state what still needs verifying, rather than inventing file paths — then consult the `hermes-terminal-backend` skill, because a path the agent cannot see is usually a masked mount, not a missing file.
- Inventories drift. Re-derive the upstream artifact list from the input's locked revision (GitHub `contents` / `git/trees?recursive=1`) instead of trusting a list written in an earlier session.
- **Precedence for extra search paths is project → local (`$HERMES_HOME/skills/`) → `external_dirs`.** A real directory in the local skills root shadows an external entry of the same name, and home-manager will not clobber a non-empty real dir — clear prior imperative installs first.
- The same shadowing exists one level up: a **bundle slug beats a skill name**, so a bundle named after a skill in its own set makes that skill unreachable under its own name. Keep bundle slugs distinct from every skill name.
- When the module enumerates sibling files that live beside it (`./skill-bundles/<slug>.yaml`), the directory and the list drift independently — a file added without a list entry is silently not installed. Cross-check the two sets before reporting done.
- A store path is immutable, so "update" always produces a *new* path. Pointing the config at it directly means the config reference changes on every refresh — correct and cheap when the change lands through a rebuild (`nh os switch`), wrong if something outside Nix is expected to follow it. Reach for a stable symlink only when the artifact must go live without a rebuild.
- `hermes config set` is blocked in managed mode (`HERMES_MANAGED`, or the `.managed` marker in `HERMES_HOME`). Declare the setting in Nix rather than shelling out.
- Inside a Nix `''…''` string, `${` must be written `''${` to reach the shell as a parameter expansion, and `''` is an escaped single quote. Getting this wrong is silent: the script still evaluates, it just interpolates at build time or loses characters.
- **`${f { }.attr}` closes the interpolation at the `}` of the empty argument.** A call written inline in a string whose argument is an empty attrset -- `${cfgOf { }.council.hermesHome}` -- terminates at the first `}`, so nix reports `cannot coerce a set to a string` and prints the whole call's result rather than the interpolation, which points at the wrong thing. Bind it first (`defaultCfg = cfgOf { };`) and interpolate the name. Same for any inline call whose argument braces would close the string early.
- In shell you generate, never put a literal backtick inside a double-quoted string — it is command-substituted. Use `printf 'literal `%s`\n' "$var"` or single quotes. Markdown in a report is where this bites, because backticks read as harmless formatting.
- A `runCommand` that copies selected children needs `mkdir -p $out` first, and the marker-file filter belongs in the shell (`for d in ${src}/*/; do [ -f "$d/SKILL.md" ] && cp -r "$d" "$out/$(basename "$d")"; done`). Writing it in shell rather than `builtins.readDir` lets the same derivation be `callPackage`d from both `perSystem` and a module without an `inputs`-shaped argument.
- **A copier that installs only the unit's `SKILL.md` silently drops its `references/`.** A store-shipped skill is a *directory*; a provisioner that copies the marker file alone installs a skill whose pointers all dangle, and nothing errors. This bites twice when two copiers exist (a repo→mount sync and a mount→profile install) — each drops the same file independently, so fixing one still leaves the other. When a unit routes to a support file, verify that file lands: `find <dest> -type f` after the copy, not just the `SKILL.md`.
- **Store files are mode `0444`, and that bites in two different places.** Anything copied out of the store inherits a read-only mode. (a) **A copier therefore runs exactly once.** `shutil.copy` sets `0444` on the destination and then opens it `'wb'`, which the *next* run cannot do, so the second install dies with `EACCES`/`Permission denied` on a file the first run had just written. Fix in the copier: `dst.unlink()` if it exists, `shutil.copy(src, dst)`, then `dst.chmod(0o644)` so the next run can overwrite it too. Prove it with two consecutive installs — one success is what the broken version already did. (b) **`rm -rf` on a directory holding such a copy fails partway**, leaving the directory behind with `Permission denied` on each store-mode file. Restore write permission first — `find <dir> -type d -exec chmod u+w {} +` and the same for `-type f` — then delete. Both failures name the *target* tree and are really about the source's mode.
- **A lint failure's reported line can be the wrong line, and the fix is often `inherit`.** `statix` W20 (`Avoid repeated keys in attribute sets`) fires on dotted keys — `options.home.a = …; options.home.b = …;` — and nesting only half-way (`programs = { x.enable = …; x.mode = …; }`) still trips it, so nest the set fully. W03 (`Assignment instead of inherit`) fires on `x = x;` and is reported at a *different* line, often inside a shell string in the same `let`; read the code, not the caret — the offending line is the self-assignment.
- **A declared config key that nothing reads is a dead key, and the user cannot tell.** A field can be documented, rendered into the user's config file with a comment explaining it, validated for type — and consumed by no code, so setting it changes nothing and reports nothing. Before trusting a declaration, grep for its reader (`grep -rn 'core_skills\|member.get("skills")' scripts/`), and treat "documented but unread" as a defect to fix rather than a feature to describe. Same tell as a zero-byte artifact: it looks like configuration and is inert.
- **A declarative switch cannot power off the machine it configures.** It evaluates, builds and activates; none of those can cut host power or land a machine in firmware setup, and on NixOS-WSL there is no bootloader step at all (`installBootLoader = true`, Microsoft kernel). Establish that from the tree before accepting the causal story (`grep -rnE 'boot\.loader|kernelParams|swapDevices|zram' --include='*.nix' .`), then separate load from activation so the result is attributable: `nix build .#nixosConfigurations.<host>.config.system.build.toplevel --max-jobs 2 --cores 2 --keep-going` followed by `nh os switch` (activation only). Dying during the build is load; dying during activation is something else. A guardrail cap goes in the **machine's own** `machines/<host>/configuration.nix` (`nix.settings.max-jobs` / `cores`), never in the shared baseline module: headroom is a property of the host, and a value picked for one machine in `base-system` becomes silent policy for machines that do not exist yet. Two limits on that cap: it only exists *after* a switch, which is the risky operation, so the first switch passes `--max-jobs` / `--cores` on the command line as well; and `cores` sets `NIX_BUILD_CORES`, which make and ninja honour but a derivation that spawns its own parallelism (npm/Node, some Rust builds) may not -- it lowers the peak, it does not bound it. A symptom dated "never happened until this week" is answered by what changed this week -- file mtimes in the tree, `git log --since`, and any firmware or Windows update on the host -- so check those before theorising. If it dies even at the capped build, the tree is exonerated and the fault is host-side hardware: stop running builds, warn the user to back the repo up (a hard cut can zero a git object), and see `references/wsl-guest-diagnostics.md` for the in-guest unclean-shutdown evidence and the host commands to hand over.
