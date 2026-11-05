# Tasks

## 1. One home for the contract

- [x] 1.1 Add `library/contract.json`: required frontmatter, `description_window`, `categories`,
      `support_dirs`, `gate_command`.
- [x] 1.2 Have `nix/tests.nix` read `required` and `descMax` from it instead of restating both.
- [x] 1.3 Add the eval assertion `test_the_contract_names_every_category_on_disk`: the contract's
      category list and the directories under `skills/` are equal in both directions, and an empty
      list fails rather than passing both scans.

## 2. One implementation of the rules

- [x] 2.1 Add `plugins/library-guard/library_guard.py` with `check_skill_text` as a pure function:
      frontmatter fence, required fields, name/directory agreement, the index window, list-shaped
      fields, CRLF.
- [x] 2.2 Add `scripts/skill-contract.py` (`--all`, `--check <path>`, `--print`) importing that
      function, so the gate and the guard cannot drift.
- [x] 2.3 Add the run-tier check `contract` to `nix/checks.nix`, running `--all` over the store
      tree; it exits 2 when the scan finds no skills, so an empty scan cannot read as a pass.

## 3. The rules, on the write path

- [x] 3.1 `transform_tool_result`: after a `write_file`/`patch` to a `SKILL.md`, read the file back,
      validate it, and return the result with the violations appended. A dict result gains a
      `library_guard` key rather than losing its shape.
- [x] 3.2 `pre_tool_call`: block a write into a skill name in `$HERMES_HOME/skills/.bundled_manifest`,
      naming `hermes update` as the reason and the path to write instead.
- [x] 3.3 Fail open: each hook returns `None` on any internal error, so the guard cannot break a
      tool call.
- [x] 3.4 `library_guard.DEFAULTS` mirrors the contract for a wheel installed away from this tree;
      the suite asserts equality, so a half-change fails.

## 4. Packaging, so the guard is installable

- [x] 4.1 `nix/plugin.nix` takes `{ src, module }` and reads `pname`, `version` and `description`
      from that plugin's `pyproject.toml`.
- [x] 4.2 `flake.nix` exposes both plugins as packages and as checks.
- [x] 4.3 `nix/overlay.nix` installs both from one list, keeping `plugin` as an alias for the first
      entry so an existing consumer still evaluates.

## 5. The test the suite needs

- [x] 5.1 `tests/unit/test_library_guard.py`: a clean skill passes, one broken field is one named
      violation (including the CRLF, unclosed-fence and non-list cases), the window comes from the
      contract, a bundled write is blocked, our own tree is not, a clean write is left alone, and
      the mirror equals the file.
- [x] 5.2 The CLI test runs `--all` over the real tree, so the gate's own reading is asserted from
      the suite as well.

## 6. Unblock the gate

- [x] 6.1 Fix the KB self-test's negative control (`copy_function=shutil.copyfile`): it copied with
      `copy2`, preserving a read-only store mode, so the control could not write its own broken copy
      — it passed in a checkout and failed in `nix flake check`.
- [x] 6.2 Strip the CRLF from the three skill files the background review wrote into this tree, and
      track the reference file one of them names, so the tree the gate hashes is coherent.

## 7. Settle it

- [x] 7.1 `nix flake check --keep-going` is green: eval tier, `contract`, `tests`, `claim-audit`,
      `formatting`, `setup-e2e`, and both plugin builds.
- [x] 7.2 `python scripts/skill-contract.py --all` reports 44 skills and 0 violations on the live
      tree; `--check` on a broken file exits 1 with the field named.
- [x] 7.3 README, `AGENTS.md` and `plugins/README.md` state the contract, the guard, and why the
      guard fails open — verified by `nix flake check`, which is the gate.