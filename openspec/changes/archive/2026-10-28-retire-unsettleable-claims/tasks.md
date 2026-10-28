# Tasks

## 1. Retire the numbers

- [x] 1.1 README: drop `(~59)` and the `23 / 4` counts, keeping the sentences' meaning.
- [x] 1.2 `claim-audit.py`: delete the ghost claim, document the two retirements where they lived.

## 2. Bring the milestone up to date

- [x] 2.1 CI row: seven jobs, ten check runs.
- [x] 2.2 Status: re-measured on `88896ec`; the three later changes recorded; contract named.

## 3. Verify

- [x] 3.1 `claim-audit.py` exits 0 with no FALSE and no UNPROVEN claim left.
- [x] 3.2 `nix flake check --keep-going`, `pytest`, and `openspec validate --all --strict` pass.
