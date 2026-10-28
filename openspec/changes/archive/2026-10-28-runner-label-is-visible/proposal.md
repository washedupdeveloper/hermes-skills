# Proposal

## Why

The runner rule reads a label wherever it is written: scalar, quoted, bracketed list, block list,
and a matrix `os:` list. That covers every form this repository uses, and it still cannot see
`runs-on: ${{ inputs.os }}` — there is no label in the file to read, only an expression pointing
somewhere the scan does not go.

## What Changes

Two blunt conditions replace nothing and add a class:

- A `runs-on:` expression SHALL name a matrix key. The matrix values sit in the same file the token
  scan already reads, so a pinned label there is a pinned label here.
- `include:` SHALL NOT appear in a workflow that uses one, because it can add matrix values the
  written list does not show — the one way an expression can name a label no reader can see.
- Mutant `1.1e`: `runs-on: ${{ inputs.os }}` must fail.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `gate-integrity`: adds "A runner label is visible in the file that names it".

## Impact

`nix/tests.nix`, `tests/e2e/test_gate_mutants.py` (23 mutants). No workflow change.

## Rejected

Refusing every expression was the first attempt and it failed on this repository: `ci.yml:118` and
`ci.yml:230` legitimately use `${{ matrix.os }}` for the `tests` and `setup` matrices. Making that
rule hold means rewriting both as explicit per-OS jobs — a CI restructure, and one that buys nothing
the two conditions above do not, since the matrix values are literal and the scan reads them.
