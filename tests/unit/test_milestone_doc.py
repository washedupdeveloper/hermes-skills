"""The milestone's figures are derived from the tree, not remembered.

`docs/milestone.md` states two counts — the requirements in the contract and the mutants that measure
the gate's rules — because both can be computed. Every other count was removed from that paragraph
rather than checked: a number nothing derives is a claim with no owner, and this repository has spent
enough changes retiring those.

The comparison is a function so it can be pointed at a drifted document: a check never observed to
fail is a guess, and this one carries its own negative control.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs/milestone.md"
HARNESS = ROOT / "tests/e2e/test_gate_mutants.py"

# The sentence, whitespace-normalised: the document wraps its lines.
CONTRACT = re.compile(
    r"\*\*(\d+) requirements across (?:two|three|four|\w+) capabilities\*\*"
)
CAPABILITY = re.compile(r"`([a-z-]+)` \((\d+)\)")
MUTANTS = re.compile(r"measured by \*\*(\d+) mutants\*\*")


def requirement_counts() -> dict:
    """Requirements per capability, counted from the merged specs — the same files the CLI reads."""
    return {
        spec.parent.name: len(re.findall(r"^### Requirement: ", spec.read_text(encoding="utf-8"), re.M))
        for spec in sorted((ROOT / "openspec" / "specs").glob("*/spec.md"))
    }


def mutant_count() -> int:
    return len(re.findall(r'\{"id": "', HARNESS.read_text(encoding="utf-8")))


def mismatches(text: str) -> list:
    """Everything the document states that the tree contradicts. Empty means it agrees."""
    flat = re.sub(r"\s+", " ", text)
    match = CONTRACT.search(flat)
    if match is None:
        return ["the contract sentence is gone or reworded, so nothing states these figures"]

    total = int(match[1])
    counts = requirement_counts()
    stated = {name: int(number) for name, number in CAPABILITY.findall(flat)}
    mutant_match = MUTANTS.search(flat)
    stated_mutants = int(mutant_match[1]) if mutant_match else -1
    problems = []

    if total != sum(counts.values()):
        problems.append(f"doc says {total} requirements; the specs hold {sum(counts.values())} {counts}")
    if total != sum(stated.values()):
        problems.append(f"doc's parts sum to {sum(stated.values())}, its total says {total}")
    for name, number in counts.items():
        if stated.get(name) != number:
            problems.append(f"{name}: doc says {stated.get(name)}, spec holds {number}")
    if set(stated) != set(counts):
        problems.append(f"doc names {sorted(stated)}, specs hold {sorted(counts)}")
    if stated_mutants != mutant_count():
        problems.append(f"doc says {stated_mutants} mutants; the harness defines {mutant_count()}")
    return problems


def test_the_milestone_agrees_with_the_tree():
    assert mismatches(DOC.read_text(encoding="utf-8")) == []


def test_a_drifted_number_is_caught():
    """The negative control: bump one figure and the comparison must notice."""
    real = DOC.read_text(encoding="utf-8")
    assert "**21 requirements across four capabilities**" in real, "the checked sentence moved"
    drifted = real.replace("**21 requirements across four capabilities**",
                           "**22 requirements across four capabilities**", 1)
    assert mismatches(drifted), "a document stating 22 requirements was accepted"


def test_a_missing_sentence_is_caught():
    """An absent count is not a passing one."""
    assert mismatches("# a document that states nothing\n"), "a document with no sentence passed"
