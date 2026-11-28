# hermes-skills

A library of **agent skills**: short, self-contained instructions an agent loads when a task calls
for them. Every skill here is either authored in this repository or adapted from an upstream source,
and every one of them is validated before it is accepted.

Nothing in this repository is specific to one agent. `SKILL.md` is the format several agents already
read, the gate is a Python script with no dependencies, and the installer links the tree into whatever
directory your agent scans. The eleven skills that only make sense inside one host say so in their
frontmatter, and are listed under [host-scoped skills](#host-scoped-skills).

## What a skill is

```
skills/<category>/<name>/SKILL.md     # the entry point: frontmatter + prose
              references/…            # optional: depth the entry point points at
              scripts/…               # optional: code the skill tells you to run
              templates/…             # optional: files it copies
```

The frontmatter is the contract:

```yaml
---
name: failure-semantics                    # must equal the directory name
description: "Use when designing error types, codes or recovery."
version: 1.0.0
author: "…"
license: MIT
platforms: [linux, macos, windows]         # where its commands work
category: software-development
targets: [hermes]                          # only when it is host-scoped; omit otherwise
metadata:
  hermes:                                  # optional, host-specific hints (tags, related_skills)
    tags: [errors, retries]
    related_skills: [defensive-patterns]
---
```

**The description is the whole index.** An agent shows itself the name and the description and
nothing else before choosing, so the first 57 characters must carry the trigger on their own. Every
description here fits that window, which is the tightest one the hosts we know of impose.

A skill is chosen per task and may not be chosen at all. A rule that must apply on every turn belongs
in the agent's system prompt, not in a skill.

## Install it into an agent

```sh
git clone https://github.com/washedupdeveloper/hermes-skills.git
cd hermes-skills
./install.sh ~/.claude/skills              # symlink every skill, flat
./install.sh ~/.hermes/skills --nested     # recreate <category>/<skill>
./install.sh /tmp/skills --copy --dry-run  # see the plan, change nothing
```

`install.sh` is POSIX `sh`, takes a target directory, and never touches what is already there. A
symlink keeps one home for the text: edit the repository and every agent sees the change.

| Host | Where it reads skills | How to point it here |
|---|---|---|
| Hermes Agent | `$HERMES_HOME/skills/`, plus any path in `skills.external_dirs` | `hermes config set skills.external_dirs '["~/hermes-skills/skills"]'` — read in place, so `git pull` is the update |
| Claude Code | `~/.claude/skills/` | `./install.sh ~/.claude/skills` |
| Codex, and any `AGENTS.md` host | a directory named in `AGENTS.md` | `./install.sh ./.agents/skills --nested`, then name that directory |
| OpenCode | `.opencode/skills/` | `./install.sh .opencode/skills` |
| Anything else that reads `SKILL.md` | — | `--copy` into the directory it scans |

Hosts differ in what they do with a skill's supporting files: some resolve them relative to the
skill directory, some flatten the tree. `--copy` is the safe default for a host you have not tested.

Editing the library while an agent is running: a new skill appears only after the host rescans. In
Hermes that is `/reload-skills` in the CLI or a restart of the app.

## Layout

```
skills/
├── autonomous-ai-agents/  hermes-bot-authoring  hermes-file-editing  hermes-kanban-orchestration
│                          hermes-knowledge-pipeline  hermes-process-operations  hermes-profile-fleet
│                          hermes-project-handoff  hermes-remote-backend  hermes-terminal-backend
│                          hermes-wsl-backend
├── build/  nix-flake-checks  nix-flake-packaging  oci-image-without-runtime  release-versioning
├── communication/  cavecrew  caveman  caveman-compress  caveman-explore  caveman-review
│                   reply  ultracave
├── devops/  ephemeral-cleanup  hermes-s6-container-supervision  nix-declarative-config
│            wireguard-mesh-triage
├── docs/  api-docs  readme-for-users  writing-for-agents
├── note-taking/  obsidian-bases
├── productivity/  wait-what
├── security/  cve-exposure-triage  git-history-sanitisation  oss-forensics  web-app-security
│              workflow-security
├── software-development/  agent-harness-design  browser-extension-review  codebase-design
│                          critical-verdict  cross-platform-correctness  defensive-patterns
│                          domain-modeling  failure-semantics  grill-me  grill-with-docs
│                          grilling  handoff  improve-codebase-architecture  issue-triage
│                          model-routing  nixos-clan-flake  openspec  postmortem  pr-description
│                          project-kickoff-planning  request-refactor-plan  retro  skill-library-curation
│                          state-machine-audit  surgical-patch  technology-selection  to-spec
│                          to-tickets  two-axis-review  wayfinder  wizard  zoom-out
└── testing/  cross-platform-test-portability  deterministic-quality-gates  verify-and-stop
```

70 `SKILL.md` across 70 skills — 69 load on Windows; `hermes-s6-container-supervision` declares
`platforms: [linux]` and is correctly skipped there.

## Host-scoped skills

Eleven skills only make sense inside one agent, and say so in their frontmatter
(`targets: [hermes]`). Every other skill here is host-neutral: it names tools where a
tool is what the skill is about, and nothing in the library requires that host.

| Skill | Targets | What ties it to the host |
|---|---|---|
| `hermes-bot-authoring` | `hermes` | Bot personas and capability sets are Hermes' plugin model. |
| `hermes-file-editing` | `hermes` | `write_file` and `patch` have their own staleness guards to work around. |
| `hermes-kanban-orchestration` | `hermes` | The durable queue is a Hermes cron job plus a board it owns. |
| `hermes-knowledge-pipeline` | `hermes` | Capture, distillation and indexing are wired to Hermes cron and its session store. |
| `hermes-process-operations` | `hermes` | Background jobs are spawned through Hermes' own process and plugin seams. |
| `hermes-profile-fleet` | `hermes` | The unit is a Hermes profile and its per-profile config. |
| `hermes-project-handoff` | `hermes` | Moving a project means moving Hermes profiles with it. |
| `hermes-remote-backend` | `hermes` | `hermes serve`, the desktop gateway and its token. |
| `hermes-terminal-backend` | `hermes` | The failure modes are the terminal tool's own backends. |
| `hermes-wsl-backend` | `hermes` | Running Hermes itself inside a WSL2 distro. |
| `hermes-s6-container-supervision` | `hermes` | s6 services in the Hermes Docker image. |

## Adding a skill

**Author it here, not in a live library.** A skill in a host's own skills directory that neither the
host ships nor a registry owns is a skill with no owner, no review and no backup. The gate cannot see
it, and the next machine does not get it.

**Do not vendor what someone else maintains.** Two classes do not belong here:

| class | owner | updated by |
|---|---|---|
| bundled with a host | the host | its own updater |
| from a registry or hub | its upstream | the registry's update command |

A copy of either gives one file two owners, and the update path silently loses. Reference it instead
— `docs/upstream.md` records every source, what was taken and what was refused.

Then:

1. `skills/<category>/<name>/SKILL.md`, with the frontmatter above. The description must fit 57
   characters and start with a trigger: `Use when …`. When the skill only makes sense in one host,
   add `targets: [<host>]` and a row to the table above.
2. `python3 scripts/validate.py` — the gate names every rule you broke, with the fix.
3. `python3 -m pytest tests/ -q` — the suite exercises the code the skills ship.
4. Commit. A host that mounts this tree sees the change on its next scan.

## Checks

| command | answers | needs |
|---|---|---|
| `python3 scripts/validate.py` | is every skill valid, and are the documents still true of the tree | a Python 3 standard library |
| `python3 -m pytest tests/ -q` | does the code the skills ship still work | `nix shell nixpkgs#python3Packages.pytest -c pytest` |
| `python3 scripts/claim-audit.py` | is every mechanical claim in the prose true | nothing |
| `nix flake check` | all of the above under a pinned toolchain, plus the formatter and this repository's own CI assertions | Nix |

The first three are the project. The fourth is convenience for a maintainer who has Nix; it runs the
same `validate.py` and adds nothing a contributor needs.

`library/contract.json` is the one home for the values the gate reads: the required frontmatter, the
index window, the category set, the host list, and the external skills a `related_skills` entry may
name. Add a category there before you add a directory to `skills/`.

## Upstream skills

Some skills are snapshots of external sources, re-adapted for this library, and nothing updates them
automatically. [docs/upstream.md](docs/upstream.md) pins the revisions, what was taken, what was
rejected and why — read it before evaluating a candidate that has already been decided.

## Decisions

`docs/adr/` records choices that are hard to reverse, surprising without context and a real
trade-off. An ADR is a paragraph, not a document.

| | |
|---|---|
| [0001](docs/adr/0001-reference-not-symlink.md) | Reference the repo, never a copy or symlink |
| [0002](docs/adr/0002-voice-in-soul-not-skill.md) | The voice lives in the system prompt, not a skill |
| [0004](docs/adr/0004-adopt-dsh-harness-rules.md) | Four harness rules from DeepSeek Harness, and its framework refused |
| [0005](docs/adr/0005-pin-workflow-actions-to-commits.md) | Workflow actions, runner images and installs pinned to commits |
| [0006](docs/adr/0006-dsh-second-pass.md) | What a second reading added, and what it refused |
| [0007](docs/adr/0007-dsh-third-pass.md) | The third pass: what the codebase seams, and what stayed prose |
| [0008](docs/adr/0008-openspec-as-the-spec-container.md) | OpenSpec as the spec container, per repository |
| [0009](docs/adr/0009-generic-project.md) | A generic library: the gate is Python, the host is a label |

## Where this is going

[docs/milestone.md](docs/milestone.md) lists the claims this repository makes about itself and the
command that settles each one. A claim that cannot be settled is not stated as a figure.