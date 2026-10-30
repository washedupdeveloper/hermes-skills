---
name: nix-declarative-config
description: "Use when editing Nix modules, options, or overrides."
version: 1.3.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: devops
metadata:
  hermes:
    tags: [nix, nixos, home-manager, flake, declarative, provisioning, skills]
    related_skills: [nixos-clan-flake, hermes-agent, hermes-profile-fleet]
---

# Declarative Nix configuration (this user)

The user runs NixOS. Their infrastructure is a Clan-based flake in their projects directory — the open project dir is usually it. Hermes is Nix-installed and runs user-level with `HERMES_HOME=~/.hermes`. They want third-party tooling provisioned **declaratively in Nix** — never `npx`, `npm install -g`, `pip install`, or `curl … | bash`.

## Priority order (Clan.lol -> flake-parts -> Nix3)

When the three disagree, the earlier wins. Apply this deliberately; a conflict is a signal to check whether a lower-priority idiom is being used where it does not belong, not a coin to flip.

1. **Clan.lol** governs. This is a clan, so clan's published guidance wins even when a flake-parts or Nix3 idiom looks cleaner. Read clan's docs from the pinned revision in the store, not the website -- `references/reading-upstream-from-the-store.md`. Two worked examples: clan publishes a recommendation to *follow* clan-core's nixpkgs rather than track your own, and its `module.input` defaultText contradicts its own resolver, so the resolver wins.
2. **flake-parts** decides where clan is silent: `perSystem`, `_module.args.pkgs`, module splitting, the `imports` list, `flake.checks`.
3. **Nix3** is the layer underneath both: experimental features, the new CLI, the flake output set, `nix flake check`.

## Where arguments enter their modules

- `flake.nix` is flake-parts `mkFlake`; it imports `inputs.clan-core.flakeModules.default` plus local `./modules/*.nix`, and holds `clan = { imports = [ (import ./clan.nix { inherit inputs; }) ]; specialArgs = { … }; }`. **`clan.specialArgs` is how a value reaches a clan module** — that is where an `inputs.<x>`-style value gets threaded, and it is a different key from home-manager's `extraSpecialArgs`.
- Home-manager is imported as a NixOS module from `modules/home/default.nix`, which sets `home-manager.extraSpecialArgs = { inherit username; }` — that is how `username` reaches the user's HM modules.
- Machine-level options live in `machines/<host>/configuration.nix`; shared system services live in `modules/clanServices/<name>/`. Local clan services are registered in `clan.nix` under `modules."<name>" = ./modules/clanServices/<name>;` with `module.input = "self"` — `module.input` defaults to `"clan-core"`, so a local module must say `"self"` explicitly.
- Package outputs go in `perSystem` in `flake.nix`. The switch command is `nh os switch` (`programs.nh` is enabled and points at the flake dir).

## When to Use

- The user asks for any Nix, NixOS, home-manager, or flake change — especially "install X declaratively".
- Third-party tooling must be provisioned without `npx` / `npm install -g` / `curl | bash`.
- An app loads a directory of units (skills, plugins, presets) that should be pinned in the Nix store.

## Standing rules

- **Inline comments are short pointers; the reasoning lives in `docs/`.** This user has rejected verbose inline comments explicitly. An inline comment earns its place only if the code cannot be understood without it: a non-obvious requirement, a workaround, or the reason a line is written the surprising way. One or two lines. When the reasoning needs more room the comment becomes a pointer -- `See docs/<file>.md` -- and the reasoning goes in that file. Do **not** put inline: restatements of what the code or an option does, evidence trails ("verified with nix 2.35.2", "the lock carried two of each"), upstream quotes, or anything inferable from the surrounding lines. A `docs/README.md` stating the convention and indexing the documents is part of the deliverable, not optional polish. Topical documents are named for their subject (`flake-internals.md`, `hermes-agent-provisioning.md`); decisions go in `docs/adr/`; forward-looking work goes in `docs/recommendations.md`. When a comment's pointer or a document names a file, moving that code means updating the pointer and every doc that named the old location -- that update is part of the move, not polish. Do not trim comments that are commented-out config the user may still want (a `# fzf = { ... }` block) -- that is intent, not prose.
- Answer with a Nix expression, not an imperative command list. If upstream only documents `npx <tool> add …`, translate it: pin the source, link or copy its artifact into the config dir, and say that is the replacement.
- Pin the *source*, not the *revision*, unless the user asks for a frozen snapshot. A `flake = false` input declared **without** `rev` still pins exactly — the resolved commit is recorded in `flake.lock` — while the input keeps tracking the branch, so `nix flake update <input>` moves it forward. Setting `rev` freezes a copy: that is the "hardcoded snapshot" to avoid whenever the user wants the thing kept current. Use `fetchFromGitHub { rev; hash; }` only when they want no new input or a deliberate freeze.
- **Symlink rather than copy** when the target dir supports it. The link stays read-only and pinned in the Nix store; updates are `nix flake update <input>` + switch. Copies into `$HOME` drift from the declaration.
- **An upstream defect is fixed here and pinned with a test; filing it upstream is the user's call, not a deliverable.** A consumer repo can carry a small workaround and a `checks.<system>` assertion that fails when the workaround is removed, which is cheaper than waiting on an upstream release and is what makes the workaround safe to keep across an input bump. Do not open issues, PRs or discussions on someone else's tracker on your own initiative — it is a publication under the user's identity. Instead reproduce the defect, fix it locally, and record the upstream state in the project's work list (`docs/recommendations.md`, an "upstream issues worth filing" section) with the one-line fix and the repro command, so reporting it later costs one paste. Reproduction recipe: `references/verification-discipline.md`.
- Read the user's actual flake and module tree before writing Nix for it. Do not invent paths, module names, or the `extraSpecialArgs` wiring.
- **A reference is not protection — say which one you provisioned.** A Nix **store** path is genuinely read-only, so anything symlinked from it cannot be edited at runtime by the agent or the app. A plain **working-tree directory** named in `skills.external_dirs` is merely *readable*: the background self-improvement review patches an existing skill **in place, wherever it is found**, so an unattended agent can write into a source-of-truth repo. Never describe the second as if it were the first. Where the tree is a git checkout, **git is the gate** and needs no approval prompt; where it is not, use `skills.write_approval`. Details, the three gates and what each covers: `references/hermes-agent-skills.md`.

  Two mechanisms that make this worse than it reads:
  - **A symlink does not prevent a write, it redirects one.** Pointing `$HERMES_HOME/skills/<name>` at the repo means a background write aimed at "the live library" lands *through* the link, in the repo — the same failure, now indistinguishable from a normal library write. Nix's store symlink is safe because the **target** is read-only; the link is not the protection. Copying the symlink without the read-only target copies the appearance and none of the property.
  - **`skills.create_dir` does not cover in-place patches.** It redirects *new* skills only; an existing skill is patched where it is found, including under `external_dirs`. So a redirect is not a write barrier. Deliberately leaving `create_dir` **unset** is the shape that keeps a source repo free of untracked files: new skills land in the profile-local dir (an inbox) and are promoted by hand.
- **Decide whether a standing instruction is identity or a unit — different slots.** A voice or communication contract that must shape every reply belongs in `SOUL.md`, not in a skill and not in `auto_load`: `SOUL.md` is slot #1 of the system prompt, injected verbatim on every turn, and never chosen by the model. A skill is chosen per task and may not be chosen, so a style that lives only in a skill is a suggestion. The cost is explicit — roughly 400 tokens of system prompt on every turn — so keep the fragment condensed and leave the long form in an on-demand skill. Two traps: Hermes reads `SOUL.md` **only** from `$HERMES_HOME` (never the working directory), so a repo cannot inject it — the repo *carries* the fragment and each machine applies it; and a **profile is its own `HERMES_HOME`**, so a global `~/.hermes/SOUL.md` does not reach a profile — a fleet ships one `SOUL.md` per member and the installer copies it in.
- Choose the scope deliberately and confirm it: **global** (every project, every session), **per-project** (only sessions started in that repo), or **variable-gated** (a shell-scoped toggle). The mechanism follows from the scope — see step 5.
- Ask before writing when the deployment shape is ambiguous. This user's requirements narrow across turns (declarative → shell-scoped → global and auto-updating); pinning the shape down once is cheaper than rewriting the module three times.
- Their infrastructure uses **Clan** and **flake-parts**, and home-manager is imported as a NixOS module. Match those conventions and the existing option namespaces; do not hand over a standalone snippet in a generic style. They have explicitly rejected "generic Nix idiomatic" answers in favour of modules consistent with the tree they already have.
- **Choose the scope of a setting deliberately: machine or clan baseline.** A value that describes *one host* -- build parallelism and headroom, topology, host-local services, the flake path -- belongs in `machines/<host>/configuration.nix`. `base-system` carries only what every machine should share: locale and timezone defaults, SSH policy, binary caches, the experimental-feature list. A number picked for one host in `base-system` silently becomes policy for machines that do not exist yet, and nobody re-examines it. `lib.mkDefault` is the escape hatch when a baseline value *is* right clan-wide but one machine may want to override it. This user states the rule as: "if it is added in base-system it will be for ALL machines I interface with" -- so propose the machine file first and only argue for the baseline when the reason applies to every machine.
- **Prove a claim with a command run at the moment you make it, and name the check that produced it.** Never assert tree state, a derivation path, or "checks pass" from an earlier observation -- an edit or another tool can have moved things since. Run `git status` in the same breath as the claim. Distinguish what you actually ran: evaluation, `nix flake check --no-build`, a full check with builds, and a real `nix build` are four different strengths of evidence, and "checks pass" does not mean "it builds". **A long build belongs in the background, and its status must be captured unpiped**: `nix build … | tail` records `tail`'s exit code, so a failed build reports `EXIT=0`; write `echo "EXIT=$?" >> log` after a redirect instead. Oracle per change type, the one-variable rule for testing whether a config is required, probe validation, and how to hand verification to the user when the sandbox cannot observe the machine: `references/verification-discipline.md`.
- Put the artifact derivation in its own file and `callPackage` it from **both** places that need it: `perSystem.packages.<name>` (so a refresh job can `nix build .#<name>`) and the consuming module (so the running config points at the same derivation). Two derivations means the job builds one thing and the config uses another — drift nobody notices until a switch.
- **Name a module under `modules/` after the input it integrates** — `git-hooks.nix`, `treefmt.nix`, `caveman-skills.nix`, `hermes.nix`. When a local name collides with a file upstream documents at a fixed path, rename the *local* one: upstream's documented path is a convention you would be fighting, and yours is the one out of step. Two files sharing a basename across different module systems reads as a mistake even when it is not.
- **Presenting a set of changes to the user:** give a tree of the affected paths with a status marker per file, a short explanation per section, and an explicit list of what was left untouched. They want the shape of the change and the reasoning, not a replay of the commands.

## Procedure: provision an upstream directory into an app config dir

1. Identify the upstream artifact directory — the dir whose *children* the app loads (e.g. one subdirectory per skill, each containing `SKILL.md`).
2. Declare the input and thread it to the consuming module:
   ```nix
   inputs.<name> = { url = "github:owner/repo"; flake = false; };
   # home-manager: extraSpecialArgs = { inherit inputs; };
   # NixOS:        add `inputs` to the module's argument set
   ```
   Without this, `inputs` is undefined inside the module and evaluation fails.
3. Discover children by their **marker file**, never a hardcoded list, so a later `nix flake update` picks up new entries and non-artifact siblings drop out:
   ```nix
   discovered = lib.filterAttrs
     (n: t: t == "directory" && builtins.pathExists "${root}/${n}/SKILL.md")
     (builtins.readDir root);
   ```
4. Expose a selection option (`null` = everything) and an `assertions` entry that names any requested-but-missing entry, so typos fail evaluation instead of silently installing nothing.
5. Wire it up according to the scope you chose:
   - **Global, config-driven** — point the app's extra-search-paths setting at the built artifact. For Hermes, `skills.external_dirs` in config.yaml: declare it under the NixOS module (`services.hermes-agent.settings.skills.external_dirs = [ "${pkg}" ]`, `pkg` being the derivation), or `hermes config set skills.external_dirs '["<path>"]'` once when unmanaged. Entries support `~` and `${VAR}` substitution, and a path that does not exist is **skipped silently** — which is what makes a variable-gated entry a clean on/off switch with no cleanup step.
     Point it at the **store path directly** when the user wants zero mutable state outside Nix: a refreshed revision then takes effect on the next switch, and nothing ever rewrites a live config. A stable symlink that a timer repoints is the variant that goes live without a rebuild, at the cost of one mutable path outside the declaration. This is a real trade, not a detail — ask, because it decides whether an unattended job can change what the agent is told without a review step.
   - **Always-on subset** — installing a unit is not making it *active*: an installed skill loads on demand, so a mode or style skill does nothing until something loads it. For Hermes, `services.hermes-agent.settings.skills.auto_load = [ "<name>" ];` injects the named skills **in full** at the start of every session on every surface (CLI, TUI, gateway, cron, API). Pin only the units that must shape every reply, because each one is paid for in every session's system prompt forever — pinning a whole provisioned directory is the classic mistake, spending tens of thousands of always-on tokens to save output on one unit. Everything else stays on demand behind `/skill-name`.
   - **Grouped on demand** — a task profile the user invokes as one command: one YAML file per bundle under `modules/skill-bundles/`, `home.file`-linked into `<hermesHome>/skill-bundles/`. `home.file` must sit inside the `home-manager.users.<name>` attribute set, and read the directory as `config.home-manager.users.<name>.services.hermes-agent.hermesHome` — the bare `config.services.hermes-agent` is a NixOS-scope path and is missing unless `nixosModules.default` is imported. Use it for sets that are always used together. Do **not** use it to activate a style skill (that is `auto_load`), and never give a bundle a slug matching one of the skills it lists — the bundle wins the collision and the skill becomes unreachable under its own name.
   - **Global, no config change** — `home.file."<HERMES_HOME>/skills/<name>".source = "${root}/${name}";` (the template below). Simplest, but the app cannot edit store-backed links.
   - **Per-project** — symlink into `<project-root>/.hermes/skills/` and run `hermes skills trust` once; the repo is then recorded in `skills.trusted_project_dirs`. Untrusted project skills are listed but not loaded, and they are inert outside that repo.
6. Verify for real, in this order: `home-manager switch` (or `nixos-rebuild switch`) → `ls -l <target>` to confirm the symlink → the app's own list command (e.g. `hermes skills list`) → restart the app or start a new session, because most tools read their index once at startup.

Write the module against the user's actual tree — a flake-parts module, their existing option namespace, home-manager threaded as a NixOS module. There is no generic drop-in for this user; they have rejected that shape.
Hermes-side layout/discovery facts, activation and the cost of auto-load, the bundle shape and its slug-collision rule, which upstream units to install at all, the conciseness knobs, and a worked repo inventory: `references/hermes-agent-skills.md`.

When what is being deployed is a **repo's own tree** (a skill that repo publishes) rather than an upstream input, build it as a derivation and point the app at the store path: a read-only tree cannot drift, and the copier stays only for hosts without Nix. The diff-against-live-output procedure, the two checks it needs, and why `nix flake check` never evaluates your module output: `references/derivation-backed-deployment.md`.

### A repo that installs itself, without Nix

When the provisioning module does not exist yet (or was removed), the repo can still
be declarative — put the desired state in a **`setup.sh` beside the skills tree** with a
single `DESIRED STATE` block naming every setting, and make the script only bring the
machine to it.

**Before writing one, check whether the repo forbids shell scripts.** A repo can
enforce a one-language rule with its own check — a flake check that fails on any
`*.sh` in the tree — and then the wrapper is not a convenience, it is the CI failure.
Read the flake's `checks` first and run `nix flake check` before pushing. Where the
CLI is already the entry point and every module is stdlib-only, the wrapper adds
nothing: the non-Nix path is `python scripts/<cli>.py <verb>`, and that is what the
docs should say too. Prefer deleting the script over weakening the check — the check
encodes the architecture and the script was the duplicate, so removing it is also the
better documentation of why there is no shell entry point.

The shape, in order of importance:

- **Idempotent.** `apply` is the default; re-running in sync is a no-op. `--check`
  reports drift and changes nothing, **exiting 1 on drift** so it can be a CI gate;
  `--print` shows the desired state. Verify both exit codes unpiped — reading `$?`
  through a pipe gives the last stage's status, not the script's.
- **A `--check` must not flag what the writer itself deletes.** If `apply` removes a
  cache or a generated file after copying, the comparison has to skip the same paths,
  or the two modes disagree by construction and the check can never pass again — the
  artifact is correct and the gate says otherwise, forever. Measured: a copier deleted
  `__pycache__` on write but compared the whole tree on `--check`, so 40 `.pyc` files
  left by running the deployed suite in place made it report drift on a tree that was
  byte-for-byte correct, and each "fix" resynced a clean tree and changed nothing. The
  filter must be narrow — a genuinely stray file still has to be reported, which is the
  half worth a test, because the easy mistake is disabling the check instead of
  scoping it.
- **Resolve its own location** (`$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)`), so
  it works from any clone path and on any OS. Never bake in a home directory.
- **Merge, never clobber, list-valued settings.** Another entry in `external_dirs` may
  belong to someone else. Compare **expanded** paths: the config may store `~/x` while
  the script resolves an absolute path, and a raw-string comparison reports false drift.
  Build the merged JSON without a parser only if you escape it correctly — `${var%"]"}`
  strips `"` too and yields `["/a,"/new"]`, corrupting the config; strip only `]`.
- **State the end state, and that it is temporary.** Say in the header that when the Nix
  module returns, the same declaration belongs there and the script is redundant — so
  nobody maintains two declarations.

Test the merge branch explicitly, not just the happy path: a machine that already has
an unrelated entry is the case the live run never exercises once the setting is set.

### Syncing a vendored copy back to its source

When a repo's tree is vendored into another repo — a skill copied into a skills
library, a framework mirrored into a consumer — the two copies drift and nothing
says so. The drift is one-directional and invisible: the source moves, the vendored
copy keeps the old files, and both look complete.

1. **Use the repo's own copier; do not hand-copy.** Look for one first (`setup
   skill`, `sync_to_*.py`, a `--check` flag). It encodes the shipping manifest —
   which files ship, which never do, what gets pruned — and a hand copy will include
   or omit the wrong ones. Run `--check` before writing: it lists exactly the drift,
   changes nothing, and exits 1, so it doubles as a gate.
2. **Know what the copier syncs FROM.** It may sync the *store build* of the
   framework rather than the working tree; the `--check` header names the source path.
   Untracked files are absent from that copy, so they will not sync — `git add` first.
3. **Read the output for removals.** A mirror copier PRUNES what the source lacks, so
   a sync that reports `REMOVED`/`EXTRA` is a different result from one that only adds.
   Say which happened.
4. **Know each side's shape before you diff them.** The two trees are not always the same
   object at the same depth: a mirror may hold the whole framework tree (`SKILL.md`,
   `scripts/`, `tests/`, `nix/`, `assets/`) while the repo's `skills/<name>/` holds only that
   unit's own folder. Diffing those two reports a pile of `Only in <mirror>: …` lines that
   reads as catastrophic drift and is actually a comparison of a subtree against a whole
   tree. Match the pair deliberately — the unit's `SKILL.md` against the mirror's
   `SKILL.md`, the repo's `scripts/` against the mirror's `scripts/` — and say which pair you
   compared. A mismatch of *scope* looks exactly like a mismatch of *content*, and the wrong
   conclusion from it is either "massive drift" or, if you stop looking there, "in sync".
5. **Verify with a triad, never the copier's own "in sync".** It compares what it
   knows how to compare -- often LF-normalised, and against a source it resolved itself
   (a store path, not the working tree you are looking at). Check (a) the previously-drifting
   files byte-for-byte with `cmp` against the source; (b) the file modes did not gain `+x`
   from the copy; and (c) for anything a flake installs, re-evaluate the deployed artifact
   -- `nix eval .#packages.<system>` — because a flake whose `nix/` modules are missing
   evaluates to NOTHING while every file "exists". Then run the synced tests. Two facts to
   state rather than discover: an uncommitted change in the source tree SHOULD show as a
   difference, because a copier vendors committed content, so that is not drift; and the
   sync's source is one specific commit, so name it -- `HEAD` moving afterwards makes "in
   sync" true of a tree that no longer exists. **A drift report is not permission to sync.**
   Read the drifted file before running the copier: if it is another writer's uncommitted
   edit, syncing ships their unfinished work into the deployed artifact, and the drift is
   transient rather than a defect. Separate the two cases by comparing the deployed copy
   against the committed blob -- `git show HEAD:<path> > /tmp/head && cmp -s /tmp/head
   <deployed>/<path>` -- because that distinguishes "the artifact is stale" (differs, sync
   it) from "someone is mid-edit" (matches, leave it). Report which one you found instead
   of resolving it silently in either direction.
6. **Stage only the vendored path**, and say what you left alone. Where the user has
   other work in progress, an unrelated unstaged file is theirs: report it, do not
   revert it, and commit with `--only -- <path>`.

## The Hermes desktop app (home-manager)

`programs.hermes-agent.desktop.enable` adds `hermes-desktop` to `home.packages` and an XDG launcher entry. It is a passthru of the same agent package and the wrapper points `HERMES_DESKTOP_HERMES` at the Nix-built `hermes`, so it installs no second runtime and downloads nothing on first start. It does not replace the CLI or TUI — every surface shares one `HERMES_HOME`, so there is nothing to disable.

Two rules decide whether it actually works:

- **A GUI launcher reads no shell profile**, so `home.sessionVariables.HERMES_HOME` never reaches it. The launcher must carry the value itself (the module passes it as wrapper `extraEnv`), or the app opens `~/.hermes` while the services use `hermesHome`. Same reasoning for any other GUI entry you provision: env in the wrapper, not in the session.
- **A remote backend is a pair**: `backend.mode != "none"` *and* `backend.sessionTokenFile` must both be set, and the URL and token travel together or the resolver throws. The default `backend.mode = "none"` has the app run its own `hermes serve` that dies with the window — fine for chat, wrong for cron, heartbeats and the gateway. Ask which one the user wants.

Option surface, the launcher's env split (`extraEnv` vs `extraRun`), the WSL2/WSLg path, the launcher entry name, and how a home-manager entry reaches the Windows Start menu: `references/hermes-agent-desktop.md`.

## Keeping the provisioned source current

The design rules for the unattended refresh job -- update semantics, the report contract, lock safety, environment, and state-directory diagnostics -- are in `references/unattended-refresh-job.md`. Read it before writing or changing one of these jobs.

## Installing Nix in the sandbox

Worth doing before any other verification step: with `nix` present, `nix flake check`, `nix build` and even the clan CLI all work in the sandbox, which beats every substitute technique below.

```console
# The container cannot sethostname, which Nix's build sandbox needs, so the
# installer dies with `error: cannot set host name: Operation not permitted`
# unless sandboxing is off. It also refuses to install while build-users-group
# names a group with no members.
groupadd -r nixbld
for i in 1 2 3 4; do
  useradd -r -g nixbld -d /var/empty -s /usr/sbin/nologin nixbld$i
  gpasswd -a nixbld$i nixbld
done
printf 'sandbox = false\nbuild-users-group =\nexperimental-features = nix-command flakes\n' > /etc/nix/nix.conf
curl -L -o /tmp/nix-install.sh https://nixos.org/nix/install
sh /tmp/nix-install.sh --no-daemon --yes
export PATH=/root/.nix-profile/bin:$PATH
```

- `. /root/.nix-profile/etc/profile.d/nix.sh` does not work in a non-login shell; put `/root/.nix-profile/bin` on `PATH` directly.
- Substitution from `cache.nixos.org` and GitHub does work, so a full `nix flake check` of the flake takes a minute or two once the inputs are fetched, not hours.
- Pass `--accept-flake-config` for this repo: the flake declares `nixConfig` and the machines set `nix.settings.accept-flake-config`. Check both ways -- it must pass without the flag too.
- **Untracked files are invisible to the flake.** A newly written module must be `git add`-ed before evaluation sees it, or the error is `attribute missing` / `path … is not valid` on a file that plainly exists. This looks like a real bug and is not one. The general rule, its scope and its corollaries are owned by `nixos-clan-flake` — read it there rather than from this line.
- The first `nix flake check` in a fresh container can fail with `error: path '/nix/store/…' is not valid` for an eval-time store path that has not been substituted yet. Re-run before believing it.
- **An error naming an *input's* store path is about the cached copy, not your tree.** `error: syntax error, unexpected end of file` at `<input>/flake.nix:1:1`, or any nonsense from a file you did not write, means the sandbox's copy of that input is corrupt -- check with `stat -c %s /nix/store/<hash>-source/flake.nix` and count zero-byte files. To prove it is not your change before chasing it: `git stash push -- <your file>`, re-run, `git stash pop`; a failure that reproduces without your change is pre-existing. Repair by moving `~/.cache/nix/tarball-cache*` and `~/.cache/nix/fetcher-cache*.sqlite` aside, `nix-store --delete --ignore-liveness <path>`, then `nix flake prefetch <input-url>` -- and verify the re-fetched file's sha256 against the upstream one before trusting it.
- The clan CLI is buildable too, and verifying the clan side end to end is cheap:
  ```console
  nix build --impure --print-out-paths --expr 'let f = builtins.getFlake "/path/to/infra"; in f.inputs.clan-core.packages.x86_64-linux.clan-cli'
  ```
  then `clan show --flake .`, `clan machines list --flake .` and `clan vars list <machine> --flake .`. There is no `clan services` subcommand and no `clan machines show`.

## Observing the machine from the sandbox

The sandbox cannot mount the host, but its `/nix/store` carries the host's built
**derivations**, and the generated file's text is inside the `.drv` -- including
the two facts that make a shell integration silently inert. Commands and limits:
`references/verification-discipline.md`.

The sandbox is also a container **inside the host's WSL VM**, so the guest's own
facts are readable directly -- `/proc/cmdline`, `lscpu`, `/proc/uptime`, `free`,
`df`, `uname -r`. Read them as the *guest's*, never the sandbox's: they are what
WSL handed the VM, which for a WSL question is the strongest evidence available
from inside. Only explicitly mounted directories are visible, so a path that is
absent here is not evidence the host lacks it. Guest-versus-host attribution, the
WSL processor warning, and what a switch can and cannot do to the Windows host:
`references/wsl-guest-diagnostics.md`.

## Restructuring a Nix tree

Behaviour-preservation procedure for extraction, ownership moves and renames --
the oracle to capture first, the order of gates, the `let`-binding mechanics and
the rename discipline: `references/restructuring-a-nix-tree.md`. One ownership
boundary per commit, and say which candidate was deliberately left alone.

## Auditing the decision records

When the ask is "go through the ADRs — is there work left, can any be deleted", the answer
comes from running the items, not reading them.

1. **List every unchecked item and run the command that would prove it.** Two oracles recur:
   `/run/current-system` must equal `nix build .#nixosConfigurations.<host>.config.system.build.toplevel
   --no-link --print-out-paths` (the switch landed *and* this tree is what runs), and a
   generator is a no-op when it exits 0 with no output and `git status --short` is still
   empty.
2. **A completed item keeps its evidence** — the command and what it returned — so the
   record needs no rerun. A bare `[x]` is a claim with nothing behind it.
3. **Work that is not a decision moves out.** "Add `aarch64-linux` when the Pi exists" is a
   task with a trigger, not a trade-off: it belongs in `docs/recommendations.md`, with the
   ADR keeping a one-line pointer. A decision record that grows a to-do list is two
   documents in one, and the to-do list is the half that rots.
4. **An item that cannot converge is a design defect, not a chore.** "Re-check the DHCP
   address when the lease renews" has no end state — the value changes hourly and nothing
   reads it. Replace the chore with the decision: record the stable neighbours (MAC, static
   gateway, CIDR) and drop the volatile value.
5. **Deleting an ADR needs two greps, both empty**: no file points at it
   (`grep -rn 'adr/000N'` — code comments and docs cite these), and none of its decisions is
   still in force. Either one present and the record stays; the checklist was the temporary
   part, the decision is not.
6. **A superseded ADR is the one to keep longest.** Its decision was reversed, so what
   survives in it is the trap that reversed it (`cores = 1` is a *downgrade* from the
   default `0`; bare `nix.conf` `max-jobs` is `1` while the NixOS module's is `"auto"`).
   Deleting it invites the same change again.

## Verifying what you wrote without a build

When the sandbox genuinely has no Nix and none can be installed the flake cannot be evaluated, but the *logic inside* a `writeShellScript` or `runCommand` can be — and that is where the bugs actually are. Extract the generated body, run it against stub binaries that drive every branch, cross-check any authored config artifact against the set that actually ships, and report the residue honestly rather than shipping unrun code with a caveat. Branch matrix and working harness: `references/verifying-generated-shell.md`.

## Testing what you publish, from outside

Every check in a repo builds from a **local path**, so the published artifact — the only thing a consumer gets — is the one thing nothing exercises. A throwaway flake whose only input is `github:owner/repo`, learning output names from `nix flake show --json` instead of memory (and why `packages.default` may not be the product), the `packages.<system>` nesting trap, and the `lib.evalModules` harness that imports a home-manager module without home-manager: `references/consumer-testing-a-flake.md`. Shipping `templates` (`templates/hermes-skills.nix` for the fixed-scope module, `templates/skills-refresh-timer.nix` for the refreshing one) so the first step is one command, and the check that keeps a template from rotting in someone else's repository, are in the same file.

## Checking what an upstream actually does

Option names, defaults, deprecations and published guidance differ between the upstream website and the revision in `flake.lock`, and the pinned copy is the one that decides. Read it from the store rather than guessing or trusting a summary: `references/reading-upstream-from-the-store.md` has the commands, what to read there, and the clan-specific answers (which nixpkgs to follow, why the lock node is a `tarball`).

## Pitfalls

Read `references/pitfalls.md` before any of these — every bullet there is a measured
failure, not a warning:

- editing `mkForce` / `mkDefault` / `mkOverride`, or formatting a `null` into a string
- taking a version from a flake input, or choosing a branch over a tag
- running `nix flake check` or `nix eval` over a tree you do not own
- adding an output outside the built-in set, or a `checks` entry for it
- writing a `writeShellScript` / `runCommand`, or a Nix `''…''` string
- copying skills or store files out of `/nix/store`
- a `statix` failure, or a config key you have not grepped a reader for
- user accounts, `mutableUsers`, or anything that must happen after activation

Anything not listed is still in that file: if a Nix change fails in a way you did
not predict, the answer is there — 31 measured failures, one per bullet.

Two more references hang off that file's subjects but are worth knowing about directly:
`references/flake-cost-and-structure.md` (closure size done right, what a cold runner must
build, deciding a structure change) and `references/nix-experimental-features.md` (the
bootstrap rule, `|>` semantics, the `nixConfig` literal-attribute-set trap).
