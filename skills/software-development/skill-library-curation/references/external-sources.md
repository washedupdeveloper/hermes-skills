# Evaluating an external skill source

Deciding *which* of someone else's skills to adopt, and how. The default answer is
fewer than you expect: a mature upstream library overlaps heavily with what you
already have.

## 1. Read the truth, not the landing page

A marketing page, an aggregator listing and a README describe *intent*. The
`SKILL.md` is the skill. Fetch the repo tree and the raw files, then judge by the
body.

```bash
curl -sL "https://api.github.com/repos/<owner>/<repo>/git/trees/<ref>?recursive=1"
curl -sL "https://raw.githubusercontent.com/<owner>/<repo>/<ref>/<path>/SKILL.md"
```

Two things to measure before reading any individual skill:

- **How many claimed skills are substantive?** A long list where most bodies are a
  paragraph pointing at an external URL is a pointer collection, not a skill set.
- **What is the file-size distribution?** A handful of real skills and a long tail
  of stubs is the common shape. Budget attention for the head only.

## 2. Determine sync semantics BEFORE adopting

This decides whether you are taking a snapshot or subscribing to code that changes
under you. Get it wrong and either you maintain something you thought was
maintained, or unreviewed updates run with the agent's permissions.

| Delivery model | How to spot it | Behaviour |
|---|---|---|
| Installer copies files in | README shows an `add` command; docs say files are editable | **Snapshot.** Nothing updates until an explicit `update` command is run. |
| Managed plugin | An install-from-marketplace command; described as read-only or auto-updating | **Subscribed.** Updates arrive without review. |
| One-time download | A `.zip`/`.tgz` link per skill | **Snapshot**, with no update path at all. |

The distinguishing question is always *does anything reach into my machine later*.
Read the README for the word `update` and for whether an installed copy is
editable. Record the answer — "does this sync?" is the first thing a future session
will ask.

## 3. Redundancy-check before writing anything

Run the owning-token search from the skill body over the candidate's distinctive
vocabulary. For a large upstream library most entries will already be covered; the
value is in the handful that are not.

Reject a candidate as redundant when an installed skill covers the same procedure,
and say which skill covers it. Do not adopt a second copy of a procedure you
already run — two copies drift and the library loses its single-owner property.

**Routers are not skills.** A file whose entire body is "call skill A and skill B"
adds an indirection hop and no content. Skip it and let the two skills be reachable
directly.

## 4. Check provenance

Prefer the original over an aggregator's copy of it. An aggregator that scrapes
other repositories produces third-hand files: you cannot diff them against the
source, cannot pull upstream fixes, and inherit whatever transformation happened in
between.

Cheap tell: a skill whose body says "follow the official guide at <URL>". That is a
pointer dressed as a skill. Sharpen the pointer or skip it — do not ship it.

## 5. Adapt, never copy

Every imported skill gets the local conventions applied. A straight copy drags in
the other ecosystem's assumptions:

- Description cut to the local ceiling (≤60 chars), trigger-first.
- Host-specific frontmatter dropped (invocation hints, tool gating, plugin fields).
- Upstream-only dependencies removed. An installer command or a companion-skill
  reference that will not exist locally becomes a self-contained default.
- Shell prose replaced with the host's tool names.
- A `verification` section added, if the upstream had none.
- `metadata.hermes.source` pinned to the exact revision taken.

The rewrite is the work. A copied skill that still names the other ecosystem's
setup step is worse than no skill: it instructs a future agent to run something
that is not there.

## 6. Record the rejections

Keep a file naming what was declined and why, one line each. This is what stops the
next session re-evaluating the same candidates from scratch, and it documents that
the omission was a decision rather than an oversight.

Group rejections by reason — redundant (name the skill that covers it), out of
scope (tied to another ecosystem), or low quality (pointer-only, third-hand).

## 7. Reference it or vendor it — pick deliberately

Two ways to hold someone else's skill, with opposite maintenance:

| | Referenced (subscribed) | Vendored (snapshot) |
|---|---|---|
| Where it lives | installed by the hub, updated in place | a file in your own skill repo |
| Maintained by | `hermes skills update` | you, by hand, forever |
| Use when | you would not change the text | you rewrote it for this environment |

**Default to referencing.** A skill you did not rewrite belongs to whoever wrote
it. Vendoring it gives one file two owners, and `hermes skills diff` / `reset` stop
meaning anything. Vendor only once step 5 (adapting) has actually changed the file —
then it is yours and your repo is its source of truth.

### The command surface

```bash
hermes skills tap add <owner>/<repo>   # register a GitHub repo as a source
hermes skills tap list                 # the skills path detected per tap
hermes skills search <query> --json    # find a skill and its exact identifier
hermes skills inspect <identifier>     # preview the body before installing
hermes skills install <identifier>     # install; hub-owned from then on
hermes skills check                    # which installed skills have updates
hermes skills update                   # apply them
hermes skills uninstall <name>
hermes skills snapshot export <file>   # record the installed set
hermes skills snapshot import <file>   # reproduce it on another machine
```

`snapshot export` is the artifact to commit when a machine's *selection* must be
reproducible without vendoring the skills themselves.

### Pitfalls

- **Never construct an identifier.** Take it from `search --json`. A guessed path
  form fails to resolve, and the failure is indistinguishable from "this skill does
  not exist". Identifiers carry their source prefix (e.g.
  `skills-sh/<owner>/<repo>/<skill>`); a registry-hosted name may be bare.
- **Parse `search` with `--json`, never the rendered table.** The table wraps at
  terminal width, so the identifier column breaks across lines and cannot be
  parsed. Index the JSON from the first `[`.
- **`inspect` has no reliable JSON mode.** Decide resolution from the rendered card
  versus an explicit not-found line. Treat a lookup failure as *transient until
  proven otherwise* — re-run before reporting a skill missing, or a network blip
  gets reported as an absence.
- **A tap installs nothing.** Registering a source only makes its skills findable;
  they still have to be installed, or declared as optional and loaded by name.
- **Local precedence beats the source.** `project > local profile >
  skills.create_dir > external_dirs`, so a name present in both resolves to the
  local copy silently. `hermes skills list` must show `Source=external` for anything
  you believe is mounted.
