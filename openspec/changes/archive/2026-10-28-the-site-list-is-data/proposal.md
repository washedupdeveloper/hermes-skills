# Proposal

## Why

`nix/pins.nix` held the version and nothing else; the list of files that adopt the CLI lived in
`nix/tests.nix` as three singletons (`agentsSpec`, `templateSpec`, `bootstrapSpec`) beside the
discovered workflows. So "which files adopt the CLI" was answered in one place and "which places to
bump" was stated in three others, each as a number:

    AGENTS.md:102        "a one-line change in four places"
    nix/pins.nix:5       "this file plus those four lines"
    nix/tests.nix:16     "this file plus the four sites"

Nothing checked any of the three. Adding a site would leave all of them wrong, and the gate would
keep passing — the same defect as the README counts retired in `b357b40`, in the file that is
supposed to be the single source.

## What Changes

- `pins.nix` gains `openspecCliSites`: the named adoption sites, as data.
- `nix/tests.nix` builds `adoptedSpecs` from it. The three singletons are gone; workflows stay
  discovered by directory, because a new workflow that installs the CLI should be checked without
  anyone remembering to list it.
- The three prose counts are removed rather than corrected. A number that three files state and
  nothing measures is a claim, and this is now a list.
- `test_the_site_list_is_not_empty`: an empty list would pass every rule built on it.
- Mutant `3.1e`: dropping a site from the list makes the gate fail naming that file.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `skill-library`: "One home per fact" now covers the site list itself.

## Impact

`nix/pins.nix`, `nix/tests.nix`, `AGENTS.md`, `tests/e2e/test_gate_mutants.py` (25 mutants).
