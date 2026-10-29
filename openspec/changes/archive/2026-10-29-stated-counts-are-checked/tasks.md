# Tasks

## 1. Remove what cannot be checked

- [x] 1.1 The check-run count and the change count leave the status paragraph, replaced by pointers.
- [x] 1.2 The historical table rows stop quoting counts.

## 2. Check what can

- [x] 2.1 `tests/unit/test_milestone_doc.py` derives the requirement and mutant counts.
- [x] 2.2 Negative control: a drifted number is rejected. And a missing sentence is rejected.

## 3. Verify

- [x] 3.1 Archive first — the new requirement is part of what the document counts — then `pytest`.
- [x] 3.2 `nix flake check --keep-going` gated on its exit code; `claim-audit`; `openspec validate
  --all --strict` before and after the archive.
