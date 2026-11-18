"""Property test for proof normalisation: total, non-mutating, idempotent.

The plan's P0 asks for property tests on both parsers — the diff hunks and proof normalisation.
`normalise` is the gate every reviewer proof passes through before it runs, so the properties that
matter are about its edges rather than its happy path:

* **total** — any object in, either a dict or a `ProofError`. A `KeyError`, `TypeError` or
  `AttributeError` escaping means a malformed proof crashes adjudication instead of being refused.
* **non-mutating** — the caller's params must come back unchanged, because a proof is also written
  to `proofs.json` and a validator that edits its input corrupts the record.
* **idempotent** — normalising the output must equal the output, or defaults drift on a replay.

Deterministic: fixed seed, fixed case count. No unpinned dependency.

Run standalone: python tests/test_normalise_property.py
"""
from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
_spec = importlib.util.spec_from_file_location("proofs", REPO / "scripts" / "proofs.py")
proofs = importlib.util.module_from_spec(_spec)
sys.modules["proofs"] = proofs
_spec.loader.exec_module(proofs)

CASES = 500
SEED = 20261107


def junk(rng: random.Random):
    """A value chosen to be the wrong shape as often as the right one."""
    return rng.choice([
        None, True, False, 0, 1, -1, 3.5, "", "x", "../etc/passwd", "**/*.py",
        [], ["a"], ["a", "b"], {}, {"a": 1}, [None], [1, 2, 3], "absent",
    ])


def valid_value(spec: dict):
    """A value the contract should accept, derived from the spec rather than guessed."""
    if spec.get("enum"):
        return spec["enum"][0]
    return {"string": "x", "integer": 1, "array": ["**/*.py"],
            "object": {"exit": "zero"}}.get(spec.get("type"), "x")


def generated_params(rng: random.Random, kind: str) -> dict:
    """Mostly-valid params with deliberate corruption, so both outcomes are reachable.

    The first version of this generator produced only junk — every case was refused and the
    totality test was vacuous. It now builds from the contract's own spec, then corrupts a field
    or injects an unknown key often enough to exercise the refusal paths.
    """
    declared = proofs.kinds()[kind]["params"]
    params = {}
    for name, spec in declared.items():
        roll = rng.random()
        if roll < 0.72:
            params[name] = valid_value(spec)
        elif roll < 0.92:
            params[name] = junk(rng)
        # else: absent, which is legal for optional params and a refusal for required ones
    if rng.random() < 0.12:
        params[f"unknown_{rng.choice(sorted(declared))}"] = junk(rng)
    return params


def test_normalise_is_total_and_never_crashes():
    rng = random.Random(SEED)
    kinds = sorted(proofs.kinds())
    accepted = refused = 0
    for case in range(CASES):
        kind = rng.choice(kinds)
        params = generated_params(rng, kind)
        try:
            out = proofs.normalise(kind, params)
        except proofs.ProofError:
            refused += 1
            continue                      # a refusal is a valid outcome
        except Exception as exc:          # noqa: BLE001 - that is the property under test
            raise AssertionError(
                f"case {case}: {kind} raised {type(exc).__name__}: {exc} for {params!r}")
        assert isinstance(out, dict), (case, kind, type(out))
        accepted += 1
    # A property test that never reaches both sides proves nothing about either. Junk params must
    # produce refusals; the generator must also produce some params good enough to be normalised.
    assert refused > 0, "no generated case was refused — the generator is too clean to test edges"
    assert accepted > 0, "no generated case was accepted — the generator is too broken to test"


def test_normalise_does_not_mutate_its_input():
    rng = random.Random(SEED + 1)
    kinds = sorted(proofs.kinds())
    checked = 0
    for _ in range(CASES):
        kind = rng.choice(kinds)
        params = generated_params(rng, kind)
        snapshot = {k: (list(v) if isinstance(v, list) else v) for k, v in params.items()}
        try:
            proofs.normalise(kind, params)
        except proofs.ProofError:
            pass
        assert params == snapshot, f"{kind}: normalise mutated its input: {params!r}"
        checked += 1
    assert checked == CASES


def test_normalise_is_idempotent():
    rng = random.Random(SEED + 2)
    kinds = sorted(proofs.kinds())
    accepted = 0
    for _ in range(CASES):
        kind = rng.choice(kinds)
        params = generated_params(rng, kind)
        try:
            once = proofs.normalise(kind, params)
        except proofs.ProofError:
            continue
        twice = proofs.normalise(kind, once)
        assert twice == once, f"{kind}: normalising twice changed {once!r} -> {twice!r}"
        accepted += 1
    assert accepted, "no generated case was ever accepted — the generator proves nothing"


def test_an_unknown_kind_is_a_refusal_not_a_crash():
    try:
        proofs.normalise("teleport", {"x": 1})
    except proofs.ProofError as exc:
        assert "unknown proof kind" in str(exc)
    else:
        raise AssertionError("an unknown kind was accepted")


if __name__ == "__main__":
    failures = 0
    names = [n for n in sorted(globals()) if n.startswith("test_")]
    for name in names:
        try:
            globals()[name]()
            print(f"ok   {name}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(names) - failures} passed, {failures} failed")
    raise SystemExit(1 if failures else 0)
