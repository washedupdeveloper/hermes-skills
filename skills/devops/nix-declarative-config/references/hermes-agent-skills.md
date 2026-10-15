# Hermes Agent skills — layout, discovery, declarative install

## Layout and discovery

- Primary dir: `~/.hermes/skills/` (`$HERMES_HOME/skills/` when a profile is active). Hub-installed and agent-created skills land there too.
- A skill is a directory containing `SKILL.md`; the folder name is the identifier. Optional `references/`, `templates/`, `scripts/`, `assets/` subdirs travel with it.
- Discovery walks with `os.walk(skills_dir, followlinks=True)` (`agent/skill_utils.iter_skill_index_files`), so a **symlinked skill directory is discovered and loaded like a real one**, and `skill_manage` follows symlinks too. This is what makes a Nix symlink install work with no config change.
- Extra search paths: `skills.external_dirs` in config.yaml — directories scanned alongside the local one. Entries support `~` and `${VAR}` substitution, and a non-existent path is **skipped silently**, so a variable-gated entry is a clean on/off switch.
- Precedence: **project → local (`$HERMES_HOME/skills/`) → `external_dirs`**. A local skill shadows an external one; a project skill shadows everything.
- Project tier: launching inside a git checkout also reads `<project-root>/.hermes/skills/` and `<project-root>/.agents/skills/` (root = nearest ancestor containing `.git`). The repo must be trusted once with `hermes skills trust` (recorded in `skills.trusted_project_dirs`); untrusted project skills are listed but not loaded. `skills.project_discovery: false` disables the scan.
- Scanning differs by tier: project skills go through the hub security scanner (content-hash cached, a `dangerous` verdict quarantines them), while `external_dirs` is not an install path and is not scanned — treat its contents as trusted-by-you.
- Building a directory of selected skills and pointing `external_dirs` at it is the alternative when you would rather not touch `~/.hermes/skills`. Point the entry at the **store path of the derivation** when the user wants no mutable state outside Nix — a refreshed revision then takes effect on the next switch. A stable symlink repointed by a timer is the variant that goes live without a rebuild, at the cost of one mutable path.
- The skill index is read at session start: restart or `/new` after changing it. `hermes skills list` confirms what is installed.
- The session-start **index** is a snapshot, but `skill_view(name)` resolves against the live directories. A skill added by a switch mid-session is therefore loadable by name immediately, even though it is absent from the prompt's skill list; it appears in the listing from the next session on. Verified for an `external_dirs` entry: `skill_view` returned the skill with `skill_dir` under the store path while the running session's index did not mention it. Practical consequence: after a switch that provisions a skill, the current session can use it ad hoc without a restart — do not tell the user they must restart to get access.

## NixOS module

- `services.hermes-agent` (from `github:NousResearch/hermes-agent`): `settings` (attrset deep-merged into config.yaml — Nix keys win, user-added keys survive), `configFile`, `environmentFiles`, `extraPackages`, `extraPlugins` (directory plugins symlinked into `$HERMES_HOME/plugins/`), `extraPythonPackages`.
- The home-manager module splits the install from the daemon: `programs.hermes-agent.enable` puts the CLI on PATH and exports `HERMES_HOME`; `services.hermes-agent.enable` runs the gateway/backend user units. Enable both for a normal host, `services` alone for a headless box. `hermesHome` defaults to `$HOME/.hermes`.
- `addToSystemPackages = true` (NixOS module) puts the CLI on PATH and exports `HERMES_HOME` system-wide, so the interactive CLI shares state with the gateway service instead of creating a second `~/.hermes`.
- Managed mode (`HERMES_MANAGED=true`, or the `.managed` marker) blocks `hermes setup`, `hermes config edit|set`, and `hermes gateway install|uninstall` — config is declarative, so point the user at `configuration.nix`.

## Activation — installed is not active

- A skill that is merely installed (local dir, `external_dirs`, project tier) is only *available*; it loads on demand. A mode or style skill therefore does nothing until something loads it, which is why "the skills are visible" and "the behaviour changed" are different observations.
- `skills.auto_load` in config.yaml pins skills so they are **fully loaded at the start of every session, on every surface** (CLI, TUI, gateway, cron, API). Resolved once per session when the system prompt is first built, so the prompt stays cache-stable; edits apply to the next session. Missing or disabled names warn and are skipped. Profile-scoped. `--ignore-rules` / `HERMES_IGNORE_RULES=1` suppresses the list.
- **The cost is the whole decision.** `auto_load` puts each named skill's full text into every session's system prompt forever. Pin only what must shape every reply — a communication-style or mode skill, and one of them. Everything else belongs on demand behind `/skill-name`.
- Declare it beside the extra search path: `services.hermes-agent.settings.skills.auto_load = [ "<name>" ];`.
- Also available on the same block: `skills.guard_agent_created` (scan agent skill writes for dangerous patterns, default off) and `skills.write_approval` (stage every agent skill write for review).

## Choosing which upstream units to install

Provisioning a third-party skill repo is a selection problem, not all-or-nothing. Classify each unit before offering it:

- **Style / mode** — shapes every reply. Auto-load it, and only it.
- **Task-invoked workflow** — commit messages, code review, a migration, compression of context files. Leave on demand; the user invokes it when they have that task.
- **Product-specific** — units that only do anything against a vendor service (a proxy, a spend dashboard, a hosted gateway). Skip them unless the user actually uses that service; otherwise they are dead weight in the index.
- **Duplicates of skills already installed** — upstream "native" packs frequently reimplement procedures the agent already has (debugging, refactoring, verification, code review). Loading both gives the agent two conflicting procedures for one job. Recommend one per domain and name the collisions explicitly, rather than installing both and staying silent about it.

## Making the agent more concise

Style skills cut *output* tokens. Thinking depth is a separate knob, and conflating the two is the usual error:

- `agent.reasoning_effort` — `none|minimal|low|medium|high|xhigh|max|ultra`, default `medium`. Governs how much the model thinks before answering. Try it per session with `/reasoning <level>` before pinning it globally.
- `agent.text_verbosity` — `low|medium|high`. Sent **only** on Responses-API routes (GPT-5 family, Codex, Azure); never on `chat_completions`, Anthropic, or xAI. A no-op on a custom OpenAI-compatible endpoint, so do not offer it as a lever there.
- Lowering reasoning effort is a trade, not a free win: it degrades exactly the work that needs depth (evaluation failures, multi-file refactors, unfamiliar build systems). Prefer a per-session `/reasoning` over a global low, and say which tasks you would keep at `medium`.
- `SOUL.md` occupies slot #1, is injected verbatim on every turn, and is never chosen
  by the model — which makes it the right home for a **voice or communication contract
  that must shape every reply**, and the wrong home for a task workflow. Two traps: it
  *replaces* the built-in identity rather than adding to it, and Hermes reads it **only**
  from `$HERMES_HOME` (a profile is its own `HERMES_HOME`, so a global file does not
  reach a profile). `auto_load` is the alternative when the content is a *unit* of
  knowledge rather than a voice; the two are different slots and the choice is
  deliberate, not a matter of which is cheaper.

## Skill bundles — a task profile behind one slash command

A bundle is a YAML file that loads several skills at once under `/<slug>`. It is the third activation shape, between "installed but on demand" and `auto_load`.

- Location: `<HERMES_HOME>/skill-bundles/<slug>.yaml`. Fields: `name` (optional, defaults to the filename stem), `description`, `skills` (required, non-empty; the same identifiers you would pass to `/<skill>`), `instruction` (optional prose prepended to the loaded content). The `instruction` is where the *order* and the "how we always use these together" belongs — it is what survives a future session not remembering why the set exists.
- Dispatch is a **user message**, not the system prompt, so it does **not** invalidate the prompt cache — unlike `auto_load`. That makes a bundle the right home for a set you invoke occasionally, and `auto_load` the right home for the one thing that must shape every reply.
- **A bundle wins over a skill of the same name** on a slug collision. The precedence is deliberate, but it makes that skill unreachable under its own name: naming a bundle `caveman-explore` and listing the `caveman-explore` skill inside it shadows the skill. Keep bundle slugs distinct from every skill name.
- Missing skills are skipped, not fatal — the agent gets a note naming what was skipped, so a typo reads as success.
- Never list an `auto_load`-pinned skill in a bundle: it is already in every session, and the bundle would load it a second time.
- Declarative install — bundles are plain files, so `home.file` one source per slug rather than running `hermes bundles create`:

  ```nix
  home.file = builtins.listToAttrs (map (slug: {
    name = "${config.services.hermes-agent.hermesHome}/skill-bundles/${slug}.yaml";
    value.source = ./skill-bundles/${slug}.yaml;
  }) [ "a" "b" ]);
  ```

  `home.file` accepts an **absolute** target (home-manager's `file-type.nix` resolves it with `isAbsolutePath`), so there is no `homeDirectory`-relative guesswork. Read the target through the option that owns it rather than hardcoding `~/.hermes` — but mind the **scope**: in a clan/flake-parts tree that imports only `homeManagerModules.default`, the option is `config.home-manager.users.<name>.services.hermes-agent.hermesHome`, and a bare `config.services.hermes-agent.hermesHome` fails evaluation with `error: attribute 'hermes-agent' missing`, because that path only exists when the *NixOS* module (`nixosModules.default`) is imported too. home-manager's `linkGeneration` completes before the hermes activation step, so the links exist before anything reads them.
- `hermes bundles list|show|reload` from the CLI; `/bundles` lists them inside a session. Run `hermes bundles reload` if a bundle does not appear after a switch.
- A bundle is an alias, not an installer: it installs nothing, and a single maintenance skill needs no bundle. Reserve bundles for sets that are genuinely always used together.

## An external mount is readable, not protected

An `external_dirs` entry makes a tree **readable by Hermes** — it does not make it
read-only. Assume the opposite at your peril: a source-of-truth repo referenced this
way is writable by the agent.

The mechanism, in order of how surprising it is:

- **An existing skill is patched *in place, wherever it is found*.** `create_dir`
  redirects **new** skills only; `patch`, `write_file`, `remove_file` and `delete` act
  on the skill where it already lives — including under `external_dirs`. So a config
  that redirects creation still leaves existing skills exposed.
- **`skill_manage` follows symlinks**, so a *symlinked* skill is writable *through* the
  link. This is why a symlink is the wrong protection: it does not prevent the write,
  it redirects it — the write lands in the source-of-truth repo and looks like a
  normal library write. A Nix store symlink is safe only because its **target is
  read-only**; the symlink is not the protection, and copying the symlink without the
  read-only target copies the look and not the property.
- **The writer is not always the curator.** The background self-improvement review —
  the fork that runs after a turn — calls `skill_manage` and lands wherever the skill
  lives. A curator ledger records it with `actor: curator`, but the `evidence.session_id`
  is the *live* session, and `hermes curator status` can show `consolidate: off` and
  "no curator-managed skills" while writes still happen. Attribute a mystery write by
  reading the ledger's session id, not by reading the actor field.

Three gates, and what each actually covers:

| Gate | Covers |
|---|---|
| `skills.write_approval: true` | Every `skill_manage` write, from foreground or background, is **staged** (not committed) to `~/.hermes/pending/skills/` and reviewed with `/skills pending` → `/skills diff <id>` → `/skills approve\|reject`. Survives restarts. Full coverage, real friction on every write. |
| `skills.create_dir` | New skills only. Existing skills are still patched in place. Not sufficient alone. |
| **git** | Everything, at zero cost at write time — *if* the tree is a tracked checkout. A write shows in `git status` / `git diff` and reverts with `git checkout`. |

So for a git-tracked source-of-truth repo, prefer **git as the gate and leave
`write_approval` off**: the review power is the same and the friction is nil. Turn the
approval gate on where the tree is *not* tracked, or where an unattended write would be
expensive to notice. `hermes curator pin` does **not** apply here — it refuses external
skills outright (`only agent-created skills participate in curation`).

Corollary: an agent-created skill landing in a tracked repo shows up as an untracked
file, which a Nix flake cannot see. Leave `create_dir` unset so new skills go to
`$HERMES_HOME/skills/` and promotion into the repo stays a deliberate, `git add`-ed act.

## Declarative bootstrap when there is no Nix provisioning

A skills repo that machines clone has no Nix module to declare it in — and "run these
three `hermes config set` commands" is an imperative runbook that drifts. Ship a
single idempotent script beside the repo instead, shaped like a Nix derivation:

- **One `DESIRED STATE` block at the top is the whole declaration.** Paths and values
  are read from it; nothing else in the script hardcodes state.
- **Resolve the repo from the script's own location** (`$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)`),
  never `$HOME` or a hardcoded path, so any clone path works on Linux, macOS, WSL and
  git-bash.
- **Modes**: default applies; `--check` reports drift and exits **1** (so CI can gate
  on it); `--print` shows the desired state and changes nothing.
- **Merge, never clobber, list-valued keys.** Another `external_dirs` entry may belong
  to someone else. Rebuild the JSON by appending before the closing `]`.
- **Compare expanded paths, not raw strings.** `hermes config get <key> --json` may
  render an entry as `~/x` while the script computed an absolute path; expand `~` on
  both sides before comparing or `--check` reports permanent false drift.
- **Verify the effect, not the write** — after setting the mount, count the skills that
  actually resolve and print the number.
- **Prove idempotence by running it twice**; the second run must report in-sync and
  change nothing.

Test the merge branch explicitly on a scratch value. It is the branch a first run on
the *author's* machine never takes (their config already has the entry), so it is the
one that ships broken — a `%]`-vs-`%"]` slip produces `["/a,"/new"]`, which is invalid
JSON that corrupts the user's config on the first real install.

## Inventorying a remote skill repo without cloning

- `https://api.github.com/repos/<owner>/<repo>/contents/skills` — direct children with `type: dir|file`.
- `https://api.github.com/repos/<owner>/<repo>/git/trees/<ref>?recursive=1` — whole tree; large, so filter in code.
- `https://raw.githubusercontent.com/<owner>/<repo>/<ref>/skills/<name>/SKILL.md` — one skill's content, to confirm it is a real skill.
- `https://api.github.com/repos/<owner>/<repo>/commits/<branch>` — `.sha` of the tip, for a reproducible `rev`.

Worked example — `JuliusBrussee/caveman`: 20 skill dirs under `skills/` (`caveman`, `cavecrew`, `caveman-commit`, `caveman-compress`, `caveman-discover`, `caveman-evidence-review`, `caveman-explore`, `caveman-help`, `caveman-learn`, `caveman-manage`, `caveman-optimize`, `caveman-review`, `caveman-setup`, `caveman-stats`, `investigate-first`, `lean-build`, `migration`, `safe-refactor`, `surgical-patch`, `verify-and-stop`) mixed with non-skill entries (`registry.json`, `compile.mjs`, `verbs-gate.mjs`, `engine-mcp-tools.json`, `native/`, `generated/`). The `SKILL.md`-existence check separates them in one rule. Six of the twenty (`investigate-first`, `lean-build`, `migration`, `safe-refactor`, `surgical-patch`, `verify-and-stop`) are upstream "native" always-on prompt packs rather than on-demand skills — offer the selection option so the user can exclude them.
