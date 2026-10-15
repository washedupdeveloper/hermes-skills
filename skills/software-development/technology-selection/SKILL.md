---
name: technology-selection
description: "Use when choosing between candidate stacks or platforms."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [architecture, evaluation, tradeoffs, embedded, toolchain, decision]
    related_skills: [project-kickoff-planning, to-spec, domain-modeling]
---

# Technology Selection

Choosing between candidate technologies (languages, frameworks, platforms,
silicon) for a project. The deliverable is a decision, not a survey: a bottom
line, per-candidate benefits and drawbacks, a direct comparison, the toolchain
for each, the pitfalls, and sources.

## When to Use

- "Which should I use for X", "compare A vs B vs C", "is Y viable here"
- Stack or platform selection where hardware, toolchain, ecosystem reach or
  vendor lock-in are in play
- Re-analysis after the user revises a constraint mid-conversation

Skip when the user has already chosen and wants implementation, or when only one
candidate is genuinely viable and the answer is a lookup.

## Always-on rules

1. **Bottom line first.** Open with the decision and the single constraint that
drives it. Never open with a survey.
2. **Name the decision hinge.** State which requirement collapses the candidate
set, and which candidate wins if that requirement changes.
3. **Primary sources only.** Vendor docs, datasheets, spec pages, repos. Search
snippets and blog roundups do not establish capability; a claim that "X supports
Y" needs the page that says so.
4. **Verify maturity, don't assume it.** For each candidate library or stack
check the objective signals: last commit, release count, stars/forks, open
issues matching your exact use case, and whether the maintainer is one person. A
project that exists is not a project that works.
5. **Separate the layers.** Radio/transport, application protocol and server are
independent choices joined by wire protocols. A constraint on one layer does not
constrain another — say so explicitly, because users assume it does.
6. **Capability beats preference.** If a language has no stack for a required
protocol, that decides the option no matter how much the user likes the
language. Lead with the gap, not with ergonomics.
7. **For hardware, the part sets the floor.** Power, memory and radio limits are
properties of the silicon, not the runtime. Compare against a dedicated-purpose
baseline before declaring a platform viable.
8. **Sources at the end.** Every load-bearing claim traceable to a URL. Use
`grounded-citations` when the analysis is a written deliverable.

## Procedure

① **Extract constraints before evaluating.** Hardware, power budget, ecosystem
targets, language preferences, code-sharing goals, and whether it ships as a
product (certification, attestation, manufacturing) or a personal build. If one
missing constraint would change the answer, ask that single question; otherwise
state the assumption and proceed.

② **Eliminate on hard capability first.** For each candidate determine whether a
stack exists for the required protocol at the required spec version on the
required hardware. Drop the ones that fail before comparing anything else.

③ **Research each survivor against primary sources.** Per candidate collect:
what exists, spec/version supported, supported hardware list, toolchain,
licensing, and known failure modes. Batch searches per topic and fetch the doc
pages that carry each claim.

④ **Probe real-world maturity.** Repos, issue trackers, changelogs. Look
specifically for open issues on the exact thing the user needs (low-power modes,
a protocol role, a hardware revision), "experimental"/"unstable"/"alpha" markers
in the vendor's own words, and single-maintainer risk.

⑤ **Build the comparison matrix.** One row per candidate, one column per
requirement that actually discriminates. Add rows for the tradeoff axes the user
named, as ordered scales rather than adjectives.

⑥ **Write the recommendation with paths.** One primary pick plus alternative
architectures, each as a concrete stack: device, transport, integration, server,
storage, UI. Name the tradeoff each path buys.

⑦ **State the physical or economic limit** that overrides preference (power
floor, certification, licensing) separately from the ergonomics discussion.

⑧ **List pitfalls as generalizable rules with the mechanism**, then cite
everything load-bearing and close with sources.

## Deliverable shape

In order:

1. **Bottom line** — the pick and the driving constraint.
2. **Reality check** — the architecture facts that constrain the choice (what the
   transport can and cannot do, what sits between device and server).
3. Per candidate: **Benefits** list, **Drawbacks** list, **Toolchain**, then a
   one-line verdict.
4. **Direct comparison** — matrices for capability, ecosystem reach, and the
   tradeoff axes.
5. The limit that overrides preference (e.g. power floor, certification).
6. **Server-side** options with the same benefits/drawbacks treatment.
7. **Recommended architectures** as numbered paths, each a concrete stack.
8. **Pitfalls checklist.**
9. **Sources.**

Dense and tabular over prose. Tables for anything enumerable. No filler.

## Pitfalls

- **Answering from memory.** Capability matrices change fast (spec versions,
  chip support, library maturity). Every cell comes from a fetched page.
- **Trusting the vendor's own adjective.** "Production ready" on a vendor page
  coexists with an open issue on the exact feature you need. Report both; the
  open issue is the operative fact.
- **Treating a named project as a usable option.** A library with a handful of
  commits and one release is a hobby artifact. Say so instead of listing it as a
  candidate.
- **Recommending a runtime that cannot reach the required layer.** Check the
  radio/transport support of a language *before* recommending it; a VM or
  interpreter with no driver for the required radio is not a candidate for that
  node.
- **Reading a platform limit as a policy gap.** "Framework X only supports
  boards Y" is often a consequence of the underlying kernel requirement (needs an
  MMU, needs Linux). That distinction tells the user whether to wait or to choose
  differently — get it right.
- **Scoring across layers.** Do not rank a firmware language against a server
  language on one axis. Evaluate each layer on its own requirements, then state
  how they connect.
- **Patching instead of re-running on a constraint change.** When the user
  revises a requirement, redo the capability matrix. One changed constraint can
  invert the recommendation, and a patched conclusion carries stale reasoning.
- **Sleep power from the datasheet alone.** Board-level current is dominated by
  the LDO, USB bridge and flash; the chip figure is a floor, not a budget. Tell
  the user to measure, and compare against a dedicated-purpose part before
  declaring the platform viable.
- **Optimising a build for control when someone else has to run it.** When the
  result is handed to other people, every line of custom firmware is a line you
  support remotely, on their network, for a non-technical user. Choose a
  declarative firmware stack that already solves provisioning, OTA and
  browser-based flashing, and keep custom firmware for your own nodes. Ship OTA
  plus a firmware version reported in telemetry before any node leaves your
  hands, or one bug is one physical visit per device.
- **Treating a local-only requirement as a privacy win only.** Local-only also
  removes cloud inference, so any model-shaped feature (identification, generated
  wording) needs a local model, cached generations, or deterministic templates —
  pick which before designing the feature. For remote access prefer a mesh VPN
  over hand-rolled tunnels, and keep broker ACLs even on a trusted LAN, because
  the guest network is the same LAN.
- **Building an adaptive or personalisation feature on a model the data cannot
  support.** With a handful of devices and weekly user actions there are too few
  outcomes per configuration for a neural network, and between-user differences
  confound the result. Use a small-parameter contextual bandit over explicit
  orthogonal dials, get contrast by assigning different configurations to
  different devices within one user, and keep the generative model for wording
  only. Log user responses (latency, dismiss/snooze/act, self-reported actions)
  from the first commit — behaviour data cannot be reconstructed later.
- **Ending without a next step.** Close with concrete paths and offer to
  scaffold the chosen one — repo layout, toolchain setup, wire schema.

## References

- `references/embedded-iot-stack-notes.md` — capability, toolchain and power
  notes for ESP32 firmware languages; Zigbee/Thread/Matter/MQTT integration
  surfaces; shared-codebase tiers across device and server.
- `references/decision-matrix-template.md` — copy-and-fill matrices for
  capability gates, maturity signals, and tradeoff axes, plus the output
  skeleton.
- `references/iot-node-hardware-and-kit.md` — node architecture, part selection
  and the do-not-buy list, sensor power gating, analog reading and calibration,
  battery-life arithmetic, enclosure notes, and how to package a build as a kit
  other people run.
