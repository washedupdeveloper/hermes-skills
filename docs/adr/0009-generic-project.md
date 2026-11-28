# A generic library: the gate is Python, the host is a label

**Decision.** `python3 scripts/validate.py` (standard library only) is the gate; `nix flake
check` calls it. `install.sh <dir>` targets whatever directory a host scans. Skills that
only make sense inside one agent declare `targets: [hermes]`.

**Why.** Everything the gate enforces about a skill is a property of the text, not of a
host: frontmatter, name, the index window, encoding, references. Two implementations of
one rule is the drift this repository forbids elsewhere.

**Cost accepted.** A Nix user's failure message now comes from Python rather than from the
evaluator with both values quoted; maintainer-only assertions keep the eval-tier form.

**Deleted, because they served one host rather than the library.** `plugins/library-guard`
(its rules are in `validate.py`), `plugins/harness-audit`, `soul/caveman-voice.md`,
`scripts/verify-live.py`.
