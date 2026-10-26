# Tasks

## 1. Make the layout declaration true

- [x] 1.1 Add `note-taking/` to the README layout tree, in alphabetical position, with its skill
      (`obsidian-bases`) named as the other rows name theirs.

## 2. Assert what the spec now claims

- [x] 2.1 Add the layout assertion to `tests/unit/test_docs.py`: parse the categories out of the
      README layout tree and compare them with the directories under `skills/` in both directions.
- [x] 2.2 Require a non-empty parse, so a reformatted tree fails instead of passing empty.
- [x] 2.3 Add the spec-path assertion: every backticked repo-relative path in
      `openspec/specs/**/*.md` exists.
- [x] 2.4 Prove both assertions can fail: run each against a temporarily broken copy (a removed
      category, a spec naming a path that does not exist) and confirm the failure names it.

## 3. Verify

- [x] 3.1 `python -m pytest tests/ -q` passes.
- [x] 3.2 `nix flake check --keep-going` passes, forced so the checks actually run rather than
      returning a cache hit.
- [x] 3.3 `openspec validate spec-paths-are-checked --strict` passes.
- [x] 3.4 `openspec validate --all --strict` passes on the tree as a whole.
