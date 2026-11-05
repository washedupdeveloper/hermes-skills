# Proposal

## Why

The library's rules exist in three spellings and enforce nothing at the moment a mistake is made.

- `nix/tests.nix` hardcodes the required frontmatter and the 57-character window. It is the gate,
  and it runs minutes later, in another process, after the turn that wrote the file.
- `scripts/claim-audit.py` checks the prose's claims about the tree, not the tree's conformance to
  its own contract.
- Nothing refuses the one write whose failure is silent: an edit into a skill Hermes ships, which
  `hermes update` overwrites without a word. `AGENTS.md` states the rule; no mechanism holds it.

Hermes has the seam for all three — `pre_tool_call` may return a block directive,
`transform_tool_result` may return the tool result with text appended — and this repository already
ships a plugin, so it already knows how to reach it. What it lacks is a contract that exists once,
and an enforcer on the write path.

The gate itself has been red on this tree for a reason unrelated to any change here: the KB
self-test's negative control copies the council's scripts with `shutil.copy2`, so on a read-only
store path it cannot write its own broken copy. It passes in a writable checkout and fails in
`nix flake check`, which is the only run that matters. That is fixed here too, because a change
cannot be verified against a gate that is already failing.

## What Changes

- `library/contract.json` becomes the single home for the required frontmatter, the index window,
  the category set and the support directories. `nix/tests.nix` reads it instead of restating the
  values; a new eval assertion holds the contract's category list and the filesystem equal in both
  directions.
- `scripts/skill-contract.py` runs those rules over one file or the whole catalog. It is a new
  run-tier check (`contract`) and the same function the runtime guard calls.
- `plugins/library-guard` is a second plugin: `transform_tool_result` returns contract violations
  inside the tool result that wrote the file, and `pre_tool_call` blocks a write into a skill named
  in `.bundled_manifest`. Every hook fails open.
- `nix/plugin.nix` stops being harness-audit's package and becomes a generic one whose `pname`,
  `version` and `description` come from the plugin's own `pyproject.toml`; the overlay installs
  both plugins from one list, so a consumer cannot enable half of them.
- The KB self-test's negative control copies with `shutil.copyfile`, so the control is writable on a
  read-only source tree and the assertion means what it says.