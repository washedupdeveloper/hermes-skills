# hermes-skills

The **source of truth** for the skills we author ourselves: skills that Hermes does
not ship and that do not come from a registry.

This repo is **not a mirror**. Machines do not push their skill library into it; they
mount it. Nothing here is generated and no script overwrites it.

## What belongs here

| class | owner | updated by | in this repo? |
|---|---|---|---|
| bundled (~59) | Hermes | `hermes update` | **no** |
| hub / registry | the upstream | `hermes skills update` | **no** |
| ours | us | `git pull` | **yes** |

Only the third row. A skill Hermes ships is tracked in the live library's
`$HERMES_HOME/skills/.bundled_manifest` (name + content hash) and is refreshed by Hermes. Copying
one in here would give a single file two owners: `git pull` would fight
`hermes update`, and `hermes skills diff` / `reset` would stop meaning anything.

Check before adding anything:

```bash
# is it bundled (i.e. not ours)?
grep -q "^<skill-name>:" "$HERMES_HOME/skills/.bundled_manifest" \
  && echo "bundled — do not add" || echo "ours — belongs here"

hermes skills list-modified      # bundled skills you have edited (kept by hermes update)
hermes skills diff <name>        # exactly what you changed in a bundled skill
hermes skills reset <name>       # keep your copy, re-baseline against stock
```

## How it is used

Clone, then run the initializer. One command, idempotent, no editing by hand:

```bash
git clone git@github.com:washedupdeveloper/hermes-skills.git ~/hermes-skills
cd ~/hermes-skills && ./setup.sh
```

`setup.sh` resolves its own location, so it works from any clone path on Windows,
Linux, macOS and WSL2. It **merges** rather than clobbers — another entry already in
`external_dirs` is preserved.

| Command | Does |
|---|---|
| `./setup.sh` | apply the desired state |
| `./setup.sh --check` | report drift, change nothing (exit 1 on drift) |
| `./setup.sh --print` | show the desired state |

**The declaration is the script's `DESIRED STATE` block** — the desired state in one
place, and the script only makes the machine match it. That is the shape available
without Nix provisioning: when infra's hermes module returns, the same declaration
belongs there and `setup.sh` becomes redundant.

### What it declares, and why

**Reference, not copy.** `skills.external_dirs` points at this repo's `skills/` tree.
No copy, no symlink, no junction — the same shape as a Nix store-path reference: one
declaration, nothing derived, nothing to drift. Reading is live, so `git pull` is the
update mechanism.

> The mount is **not a permission boundary** — it makes this tree readable, not
> protected. Why a symlink would have made things worse, and why the gate is git
> instead: [ADR-0001](docs/adr/0001-reference-not-symlink.md).

**No approval prompts.** `skills.write_approval: false`. This repo is git-tracked, so
a background skill write shows up in `git status` / `git diff` and reverts with
`git checkout`. That is the review gate, and it costs nothing at the time of the
write. Set it `true` on a machine where you would rather approve each write first.

**New skills land outside this repo.** `create_dir` is left unset, so agent-created
skills go to the profile-local `~/.hermes/skills/` and are promoted here deliberately
— the same gate as the knowledge vault's `inbox/`. That also keeps this repo free of
untracked files, which Nix cannot see.

> `create_dir` cannot protect this repo on its own: it redirects **new** skills only.
> An existing skill is patched *in place, wherever it is found* — including under
> `external_dirs`. The git diff is what covers that half.

**Precedence:** `trusted project > local profile > skills.create_dir > external_dirs`.
A skill present both locally *and* here resolves to the **local** copy, silently.
Keep names unique across the two, or delete the local copy when moving a skill in.

## Layout

```
skills/
├── autonomous-ai-agents/   council ( + its 6 rubrics under assets/rubrics/ )
│                           hermes-bot-authoring  hermes-knowledge-pipeline
│                           hermes-profile-fleet  hermes-project-handoff
│                           hermes-terminal-backend
├── communication/          caveman  ultracave  caveman-review  cavecrew
│                           caveman-explore  caveman-compress
├── devops/                 hermes-s6-container-supervision
│                           nix-declarative-config
├── productivity/           wait-what
├── security/               oss-forensics  web-app-security
└── software-development/   deterministic-quality-gates  domain-modeling
                            grill-me  handoff  nixos-clan-flake  retro
                            skill-library-curation  surgical-patch  to-spec
                            to-tickets  verify-and-stop  wayfinder  wizard
                            writing-for-agents  project-kickoff-planning
                            technology-selection
```

Also at the top level, not a skill:

```
soul/                       caveman-voice.md — the always-on SOUL.md fragment
setup.sh                    the initializer: declares and applies the settings
```

41 `SKILL.md` across 35 skills — 34 load on Windows; `hermes-s6-container-supervision`
declares `platforms: [linux]` and is correctly skipped here.

Six of the 41 are the council's reviewer rubrics
(`council/assets/rubrics/reviewer-*/SKILL.md`). They carry SKILL.md frontmatter, but
`assets/` is one of Hermes's `SKILL_SUPPORT_DIRS` (`references`, `templates`, `assets`,
`scripts`), so they are **not** separate catalog skills. They travel with the council and
are read by its orchestrator.

## The always-on voice

`SOUL.md` is slot #1 of the system prompt: injected on **every turn, in every
session**, and never chosen by the model. A skill is chosen per task and may not be
chosen — so a communication contract that lives only in a skill is a suggestion, not
a voice. The standing contract therefore lives in `SOUL.md`, and the `caveman` skill
is its on-demand long form.

`soul/caveman-voice.md` holds the canonical fragment. Hermes only reads `SOUL.md`
from `$HERMES_HOME`, so the repo cannot inject it — it *carries* it, version-
controlled, for each machine to apply:

```sh
sed -n '/^<!-- BEGIN SOUL -->$/,/^<!-- END SOUL -->$/p' soul/caveman-voice.md \
  | sed '1d;$d' > "$HERMES_HOME/SOUL.md"
```

Three consumers, one contract:

| Where | File | Reaches |
|---|---|---|
| Global agent | `$HERMES_HOME/SOUL.md` | every session on that machine |
| Council reviewer | `review-council/bots/council-generalist/SOUL.md` | every review sample |
| Council orchestrator | `review-council/bots/council-orchestrator/SOUL.md` | every round |

A council profile is its own `HERMES_HOME`, so the **global** `SOUL.md` does not
reach it — the council ships its own per-member `SOUL.md`, and `council setup bots`
copies them into the profiles. That is why the voice is version-controlled there too.

Cost is explicit: **~500 tokens** of system prompt on every turn, including turns
where brevity does not matter. That is the price of it actually applying, and why the
fragment is condensed rather than the full skill text.

## Adding or changing a skill

**Every skill we author lives here — none lives only in the live library.** The live
library holds two classes and only two: **bundled** (owned by Hermes, refreshed by
`hermes update`) and **hub** (owned by its upstream, refreshed by `hermes skills
update`). A skill that is neither, sitting in `$HERMES_HOME/skills/`, is ours with no
owner and no backup — and on a Nix-managed machine it is worse than that: a Nix flake
copies only **git-visible** paths, so a local-only skill is invisible to every build
and switch.

Check for strays with the app's own provenance, not a file listing:

```sh
hermes skills list | awk -F'  +' '$4=="local" && $3!="external"'
```

A non-empty result is a skill we own that is not in this repo. Promote it — copy it
here, give it the frontmatter below, then **delete the local copy**, because
`trusted project > local profile > skills.create_dir > external_dirs` means a local
copy shadows this repo silently.

Edit it **here**, commit, and on each machine `git pull`. Do not edit the mounted
copy expecting it to stick anywhere — this repo is the only writable copy.

Then reload: a new skill only appears as a `/<name>` command after the app
restarts, because the skill-command table is memoised in-process (`/reload-skills`
works in the CLI).

## Upstream skills

Some skills were adapted from external sources as **local snapshots** — nothing
updates automatically. See [docs/upstream.md](docs/upstream.md) for the pinned revisions, what
was taken, what was rejected and why, and how to pull a newer revision. Those are
upstream-managed: pull them from their source rather than hand-editing them here.

## Checks

`nix flake check` is the gate. It has two tiers plus one live check, and the tier
is chosen by what the assertion needs:

| tier | answers | cost |
|---|---|---|
| eval | what the tree **says** — frontmatter, the index window, names, encoding | milliseconds |
| run | **behaviour** — `setup.sh` against a stub, and the prose claims against the tree | seconds |
| live | does the **real Hermes** load every skill | one install |

`nix/tests.nix` holds the eval tier, `nix/checks.nix` the run tier, and each
explains why its assertions belong where they are. The rule: an assertion belongs
in the cheapest tier that can make it, and an interpreter is only needed by the
run tier.

**There is no build tier, deliberately.** An earlier version built a simulated
"shipped" tree and checked self-containment against it. No copier exists — Hermes
reads `external_dirs` in place — so the artifact was fiction. It was deleted, and
the `../`-escape rule it carried moved into `test_no_dead_references`, where the
write-verb heuristic it needs already lives.

`scripts/verify-live.py` is the live check: it installs nothing, it asks the
`hermes` on your PATH, and the `live` CI job installs Hermes to run it. It knows
about `environments:` — a skill gated on `[s6]` is *correctly* absent outside
that environment, and a check that ignored the gate would fail on every host that
is not the one the skill is for.

The three commands below still work on a machine with no Nix, which is why they
stay: they are the no-Nix path, not a second owner of the same property. The
properties that moved to Nix were removed from `tests/unit/test_repo_skills.py`,
and its docstring says which and why.

```bash
nix flake check                   # the gate: eval + run tiers
python scripts/verify-live.py     # the real Hermes loads every skill (exit 2 = no hermes)
python -m pytest tests/ -q        # the retained Python suite; the docs gate is part of it
python scripts/claim-audit.py     # exit 1 on any claim in the prose that is FALSE
bash tests/e2e/test_setup.sh      # setup.sh, against a STUBBED `hermes`
```

| gate | what it enforces | where |
|---|---|---|
| `skills` | frontmatter complete and closed, every key parsed, name matches its directory, unique, description inside the index window (boundary inclusive), no CRLF | `nix/tests.nix` |
| `tests` | the retained unit suite, on **Linux, macOS and Windows** | `.github/workflows/ci.yml` |
| `live` | the real Hermes discovers every catalog skill and honours `environments:` | same |
| `claim audit` | every mechanical claim in the prose is checked, not asserted | same |
| `setup.sh e2e` | the initializer merges rather than clobbers, and `--check` exits 1 on drift | same, Linux and macOS |

The e2e gate stubs `hermes` so the merge path is exercised **without touching a real
config** — the only way to test it honestly, since lying to the script about the current
config is the point and doing that against the live config would edit it.

The `setup.sh e2e` job is deliberately **not** on Windows: it builds an extensionless
`hermes` stub and executes it through `bash`, and how a Windows runner's Git Bash handles a
shebang file with no extension is unverified here. An unverified assertion in CI is worse
than an absent one — it teaches people to ignore red.

## Decisions

`docs/adr/` records choices that are **hard to reverse, surprising without context,
and a real trade-off** — the three tests, from `domain-modeling`. An ADR is a
paragraph, not a document.

| | |
|---|---|
| [0001](docs/adr/0001-reference-not-symlink.md) | Reference the repo, never a copy or symlink |
| [0002](docs/adr/0002-voice-in-soul-not-skill.md) | The voice lives in `SOUL.md`, not a skill |

Everything else — the ownership classes, the setup contract, the layout — is a rule
or a fact, and lives in `AGENTS.md` or here.

## Why there is no `sync.sh`

There used to be. It did `rm -rf skills/` and copied a machine's live skill library
over the top — a mirror, enforcing *live machine → repo*. That model is gone, and the
script was the most dangerous file in the repo:

- it could only ever copy **from** a machine, so it could never be a source of truth;
- it copied everything, bundled skills included;
- it was a replace, not a merge, so any skill absent from the live machine was
  **deleted** from the repo.

In practice the two machines' local skill sets were disjoint (23 here, 4 there, zero
overlap), so running it from either side destroyed the other's skills. Nothing needs
to copy skills between machines now: `external_dirs` mounts them.
