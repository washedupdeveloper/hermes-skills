# hermes-skills

The source of truth for the skills we author ourselves — the ones Hermes does not ship and no
registry provides.

This repo is not a mirror: machines mount it through `skills.external_dirs`, they do not push into
it. Nothing here is generated, and no script overwrites it.

## What belongs here

| class | owner | updated by | in this repo? |
|---|---|---|---|
| bundled | Hermes | `hermes update` | **no** |
| hub / registry | its upstream | `hermes skills update` | **no** |
| ours | us | `git pull` | **yes** |

Only the third row. A bundled skill is tracked in `$HERMES_HOME/skills/.bundled_manifest` and
refreshed by `hermes update`; copying one in here gives a single file two owners, so `git pull`
fights the refresh and `hermes skills diff` / `reset` stop meaning anything.

Before adding anything:

```bash
# is it bundled (i.e. not ours)?
grep -q "^<skill-name>:" "$HERMES_HOME/skills/.bundled_manifest" \
  && echo "bundled — do not add" || echo "ours — belongs here"

hermes skills list-modified      # bundled skills you have edited
hermes skills diff <name>        # exactly what you changed in one
hermes skills reset <name>       # keep your copy, re-baseline against stock
```

## How it is used

```bash
git clone git@github.com:washedupdeveloper/hermes-skills.git ~/hermes-skills
cd ~/hermes-skills && ./setup.sh
```

`setup.sh` resolves its own location, so it runs from any clone path on Windows, Linux, macOS and
WSL2. It merges rather than clobbers: an entry already in `external_dirs` survives.

| Command | Does |
|---|---|
| `./setup.sh` | apply the desired state |
| `./setup.sh --check` | report drift, change nothing (exit 1 on drift) |
| `./setup.sh --print` | show the desired state |

The declaration is the script's `DESIRED STATE` block, and the script only makes the machine match
it. When infra's hermes module returns, the same declaration belongs there and `setup.sh` goes.

### What it declares

- **A reference, not a copy.** `skills.external_dirs` points at this repo's `skills/`; reading is
  live, so `git pull` is the update mechanism. It is not a permission boundary — the mount makes
  this tree readable, not protected. [ADR-0001](docs/adr/0001-reference-not-symlink.md).
- **No approval prompts.** `skills.write_approval: false`, because a write lands in the working tree
  where `git status` shows it and `git checkout` reverts it. Set it `true` where you would rather
  approve each write.
- **New skills land outside this repo.** `create_dir` is unset, so agent-created skills go to the
  profile-local `~/.hermes/skills/` and are promoted here deliberately. That keeps this repo free
  of the untracked files Nix cannot see, but it does not protect an existing skill: a patch lands
  in place, wherever the skill is found, and the git diff is what covers that half.
- **Precedence:** `trusted project > local profile > skills.create_dir > external_dirs`. A skill
  present both locally and here resolves to the local copy, silently — keep names unique across the
  two.

## Layout

```
skills/
├── autonomous-ai-agents/   council ( + its 6 rubrics under assets/rubrics/ )
│                           hermes-bot-authoring  hermes-knowledge-pipeline
│                           hermes-profile-fleet  hermes-project-handoff
│                           hermes-terminal-backend
├── communication/          caveman  ultracave  caveman-review  cavecrew
│                           caveman-explore  caveman-compress
├── devops/                 ephemeral-cleanup
│                           hermes-s6-container-supervision
│                           nix-declarative-config
├── note-taking/            obsidian-bases
├── productivity/           wait-what
├── security/               oss-forensics  web-app-security
└── software-development/   agent-harness-design  defensive-patterns
                            deterministic-quality-gates  domain-modeling
                            grill-me  handoff  nixos-clan-flake  postmortem
                            retro  skill-library-curation  surgical-patch
                            to-spec  to-tickets  verify-and-stop  wayfinder
                            wizard  writing-for-agents
                            project-kickoff-planning  technology-selection
```

50 `SKILL.md` across 44 skills — 43 load on Windows; `hermes-s6-container-supervision` declares
`platforms: [linux]` and is correctly skipped there.

Six of the 50 are the council's reviewer rubrics (`council/assets/rubrics/reviewer-*/SKILL.md`).
They carry frontmatter, but `assets/` is one of Hermes's support directories, so they are not
catalog skills: they travel with the council, and its orchestrator reads them.

Also at the top level, not skills: `soul/` (the SOUL fragment) and `setup.sh` (the initializer).

## The always-on voice

`SOUL.md` is slot #1 of the system prompt, injected on every turn and never chosen by the model. A
skill is chosen per task and may not be, so a communication contract that lives only in a skill is a
suggestion. The standing one lives in `SOUL.md`; the `caveman` skill is its on-demand long form.

Hermes reads `SOUL.md` only from `$HERMES_HOME`, so the repo carries the fragment and each machine
applies it:

```sh
sed -n '/^<!-- BEGIN SOUL -->$/,/^<!-- END SOUL -->$/p' soul/caveman-voice.md \
  | sed '1d;$d' > "$HERMES_HOME/SOUL.md"
```

| Where | File | Reaches |
|---|---|---|
| Global agent | `$HERMES_HOME/SOUL.md` | every session on that machine |
| Council reviewer | `review-council/bots/council-generalist/SOUL.md` | every review sample |
| Council orchestrator | `review-council/bots/council-orchestrator/SOUL.md` | every round |

A council profile is its own `HERMES_HOME`, so the global file does not reach it; `council setup
bots` copies the per-member files into the profiles, which is why they are version-controlled too.

It costs **~500 tokens** of system prompt on every turn, including turns where brevity does not
matter — the price of it applying, and why the fragment is condensed rather than the full skill.

## Adding or changing a skill

Every skill we author lives here; none lives only in the live library. A skill in
`$HERMES_HOME/skills/` that is neither bundled nor from the hub is ours with no owner and no backup
— and on a Nix-managed machine a flake copies only git-visible paths, so it is invisible to every
build and switch.

Find strays by provenance, not by listing files:

```sh
hermes skills list | awk -F'  +' '$4=="local" && $3!="external"'
```

A non-empty result is a skill we own that is not in this repo. Copy it here, then delete the local
copy: a local copy shadows this tree silently.

Edit it here, commit, and `git pull` on each machine. A new skill appears as a `/<name>` command
only after the app restarts, because the command table is memoised in-process (`/reload-skills`
works in the CLI).

## Upstream skills

Some skills are local snapshots of external sources, and nothing updates them automatically.
[docs/upstream.md](docs/upstream.md) pins the revisions, what was taken, what was rejected and why.

## Checks

`nix flake check` is the gate: two tiers plus a live check. An assertion belongs in the cheapest tier
that can make it.

| tier | answers | cost |
|---|---|---|
| eval | what the tree **says** — frontmatter, index window, names, encoding | milliseconds |
| run | **behaviour** — `setup.sh` against a stub, the prose claims against the tree | seconds |
| live | does the **real Hermes** load every skill | one install |

`nix/tests.nix` holds the eval tier and `nix/checks.nix` the run tier; each says why its assertions
belong there. There is no build tier: an earlier one checked a simulated "shipped" tree against a
copier that does not exist, so the artefact was fiction and was deleted.

```bash
nix flake check                   # the gate: eval + run tiers
python scripts/verify-live.py     # the real Hermes loads every skill (exit 2 = no hermes)
python -m pytest tests/ -q        # the retained Python suite; the docs gate is part of it
python scripts/claim-audit.py     # exit 1 on any claim in the prose that is FALSE
bash tests/e2e/test_setup.sh      # setup.sh, against a stubbed `hermes`
```

| gate | what it enforces | where |
|---|---|---|
| `skills` | frontmatter complete and closed, every key parsed, name matches its directory, unique, description inside the index window, no CRLF | `nix/tests.nix` |
| `tests` | the retained unit suite, on **Linux, macOS and Windows** | `.github/workflows/ci.yml` |
| `live` | the real Hermes discovers every catalog skill and honours `environments:` | same |
| `claim audit` | every mechanical claim in the prose is checked, not asserted | same |
| `setup.sh e2e` | the initializer merges rather than clobbers, and `--check` exits 1 on drift | same, Linux and macOS |

The e2e gate stubs `hermes`, which is the only honest way to exercise the merge path: the script has
to be lied to about the current config, and doing that against the live config would edit it. It is
not on Windows because how a Windows runner's Git Bash executes an extensionless shebang file is
unverified here, and an unverified assertion teaches people to ignore red.

`scripts/verify-live.py` installs nothing; it asks the `hermes` on your PATH, and the `live` CI job
installs Hermes to run it. It honours `environments:`, so a skill gated on `[s6]` is correctly absent
everywhere else.

## Decisions

`docs/adr/` records choices that are hard to reverse, surprising without context and a real
trade-off. An ADR is a paragraph, not a document.

| | |
|---|---|
| [0001](docs/adr/0001-reference-not-symlink.md) | Reference the repo, never a copy or symlink |
| [0002](docs/adr/0002-voice-in-soul-not-skill.md) | The voice lives in `SOUL.md`, not a skill |
| [0003](docs/adr/0003-the-council-skill-is-a-generated-copy.md) | The council skill is a generated copy |
| [0004](docs/adr/0004-adopt-dsh-harness-rules.md) | Adopt four harness rules from DeepSeek Harness, reject its framework |
| [0005](docs/adr/0005-pin-workflow-actions-to-commits.md) | Pin workflow actions and installs to commits |
| [0006](docs/adr/0006-dsh-second-pass.md) | The second pass: bug classes, incident classes, request logging |
| [0007](docs/adr/0007-dsh-third-pass.md) | The third pass: the codebase, the record, and what stayed prose |
| [0008](docs/adr/0008-openspec-as-the-spec-container.md) | OpenSpec as the spec container, per repository |

Everything else — the ownership classes, the setup contract, the layout — is a rule or a fact, and
lives in `AGENTS.md` or here.

## Where this is going

[docs/milestone.md](docs/milestone.md) lists the claims this repository makes about itself and the
command that settles each one. A claim that cannot be settled is not stated as a figure.