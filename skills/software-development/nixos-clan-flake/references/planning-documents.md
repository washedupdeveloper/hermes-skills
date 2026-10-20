# The plan documents, and how to change one

A clan fleet repo carries four documents that must not disagree: the **milestone** (what
done means, and the gaps in order), **recommendations** (item-level outstanding work),
**adding-a-machine** (the per-machine procedure and the failure each step prevents), and
**adr/** (decisions with the options rejected). This reference covers answering "what is
missing to reach the milestone", closing an undefined target with the owner, and amending a
plan when a decision reverses.

## "What is missing?" is unanswerable until the target exists

The first move is a grep, not an analysis:

```bash
grep -rni milestone --include=*.md --include=*.nix .
```

A repo with no milestone has no referent for the question, and the honest answer is "nothing
is measurable yet". The deliverable then is the target itself — defined with the owner — not a
gap list measured against an imagined one. Do not silently substitute a plausible target
("the next machine", "the next release"): ask, or say the target is undefined.

When the target does exist, name each gap by the mechanism that blocks it, not by the feature
it resembles: `test_every_machine_runs_on_a_declared_system` compares every machine's
`nixpkgs.hostPlatform.system` against the flake's `systems`, so a `aarch64-linux` machine
cannot even be *declared* before that list grows — that is a gap with a command behind it, and
"add a Pi" is not.

## One home per fact

| fact | document |
|---|---|
| the target, the decisions taken with it, the ordered gaps, what "reached" means | `docs/milestone.md` |
| item-level outstanding work | `docs/recommendations.md`, **referenced by number** |
| the per-machine procedure and the failure each step prevents | `docs/adding-a-machine.md` |
| a decision with its rejected options | `docs/adr/` |
| a deferral, an accepted risk, and the measured consequence | `docs/milestone.md` under "Deferred on purpose" |

Copy a list into a second document and the two drift the moment either moves. Reference it
(`recommendations.md` 1.7) instead.

A document that states a claim in a weaker register than the truth is the failure mode to
watch: "vars are sops/age-encrypted at rest" reads as a promise that an unencrypted disk does
not keep. Fix the sentence where it lives and point at the milestone for the consequence —
never restate the consequence in two places.

## Closing an undefined target: interview the owner

- **Rounds of at most five questions**, each single-select or multi-select with a
  **recommended option first** (the UI marks it and appends a free-text row). Number the
  options only in the tool, never in the question text.
- **Ask only what changes the design.** "What will the Pi run" decides whether it is a machine
  or a service host; "do you want it to be nice" decides nothing. Drop the rest.
- **Decide the delegated axes yourself and say so.** "Undecided — choose what makes the fleet
  coherent" is an instruction to decide, not to ask again: pick, state the reason in one line,
  and let the owner correct it. Same for a question chain the owner answers with a shrug.
- **Fold in a decision the earlier round already made** rather than re-asking it, and name any
  fact that falls out of an answer (a chosen peer, an unpushed branch) in the same breath.
- **Ask before assuming hardware.** A board's support flake, a disk layout, a TPM — each is a
  real decision the owner may defer. "Decide when the hardware is in hand" is a legitimate
  answer, and a good plan records it as one instead of pre-empting it.

## When a decision reverses, sweep it — do not append

A reversal is measured by the number of places still asserting the old decision. Order:

1. **Grep the wording**, not the concept — `grep -rn 'LUKS\|encrypted at rest' --include=*.md
   --include=*.nix .` — and enumerate the hits before editing.
2. **Fix the "settled decisions" list first.** A list that claims to hold the constraints taken
   with the target is the one that turns a document into a lie; a deferral belongs there too,
   worded as an open decision (`nothing here should be read as a promise that…`).
3. **Fix every table row and section that repeats it**, and the neighbouring doc that states
   the same claim in its own register, pointing at the milestone rather than copying it.
4. **Leave a pointer behind if the old wording was load-bearing** — a code comment that
   restates the old decision becomes a pointer to the ADR that records the reasoning
   (`Traps and measurement: docs/adr/0003.`).
5. **Re-run the gate**: markdown is inside `nix flake check`, so a doc edit is a gated change.
   `printf '\n' >> <file>` first — MD047 wants exactly one trailing newline and `write_file`
   does not add it.

## Verify every identifier before it goes in the document

A plan is checkable only if its nouns exist. Before writing `services.github-runners.<name>`,
`tokenFile`, `boot.loader.raspberry-pi`, `systemd-cryptenroll --tpm2-device=auto`,
`nixosModules.raspberry-pi-4.base` or `sops.age.keyFile` into a document, confirm each against
its source: read the module in the pinned nixpkgs store path, read the service interface out of
the pinned clan-core store path, or check the upstream project's own README. A quoted
requirement is stronger than a remembered one — "`systemd-cryptenroll` supports only LUKS2
volumes" came from its manual, not from memory.

Measured values are what make a security or cost claim land: `nix eval --raw
.#nixosConfigurations.<m>.config.sops.age.keyFile` returning `/var/lib/sops-nix/key.txt` is
evidence; "the key is on disk" is an assertion. Prefer the eval, and paste the value.

## Write the consequence, not just the absence

A deferral with no named cost is indistinguishable from an oversight. Each one should carry:

- **what is given up and its size, measured** — the secret material a stolen unencrypted disk
  yields, the reachability an unattended reboot needs;
- **the shape when it lands**, fixed enough that deciding later is a decision and not a
  research task (the format, the key derivation, the enrollment, where the recovery key lives);
- **the cost of that shape**, so the future choice is informed (a firmware update breaks a
  PCR 7 auto-unlock until re-enrollment);
- **whether the deferral is free to reverse** (an in-place re-encrypt means no reinstall);
- **why now is not the time** — hardware not in hand, a decision the owner has not taken.

## What "reached" means must be executable

End the milestone with a claim someone can settle by running something: every machine is
declared, the gate builds all of them on the runner for the merge that carries the last one,
and a deploy has **changed something on a remote machine over SSH without a local switch**.
"The fleet works" is not a criterion; a command that returns a different value is.
