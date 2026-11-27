#!/usr/bin/env python3
"""Score how well the catalog routes a prompt to exactly one skill.

The claim this settles: *a prompt that names a task selects exactly one skill.* Two ways
to fail it -- two skills scoring the same, or a prompt matching none -- and one way to
degrade it silently: the right skill stops winning.

Deterministic, and deliberately simple. A prompt is tokenised; every skill's
`scope_triggers` and `scope_answers` are tokenised; a phrase covers a prompt in
proportion to how many of ITS OWN tokens appear in the prompt. Triggers weigh double,
because a trigger is the phrase a reader actually arrives by. The best-scoring skill
wins; an exact tie is `ambiguous`; a best score under `FLOOR` is `none`.

    python3 scripts/routing-score.py            # print the score
    python3 scripts/routing-score.py --strict   # exit 1 on ambiguity or below baseline
    python3 scripts/routing-score.py --show-misses

`library/routing.jsonl` is the corpus; `library/routing.json` records the floor a run
must not fall below. Raising the floor is a decision in a diff, like every other ratchet
in this repository.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"
CORPUS = REPO / "library" / "routing.jsonl"
BASELINE = REPO / "library" / "routing.json"

STOPWORDS = {
    "a", "after", "an", "and", "are", "as", "at", "be", "but", "by", "do", "does", "for",
    "from", "here", "how", "i", "if", "in", "is", "it", "its", "me", "my", "not", "of",
    "on", "or", "other", "should", "that", "the", "their", "them", "then", "there",
    "these", "this", "to", "use", "when", "will", "with", "you", "your",
}
FLOOR = 0.5          # a phrase must cover this much of itself to count at all
TRIGGER_WEIGHT = 2.0


def stem(word: str) -> str:
    """Strip the plural and gerund suffixes that make two words of one.

    Deliberately crude: `tests`/`test`, `running`/`run`, `copied`/`copy`. A real stemmer
    would be a dependency and a source of surprises; this only has to stop a prompt and a
    trigger that say the same thing from scoring as strangers.
    """
    # `ss`, `us` and `is` are the word's ending, not a plural: stripping them turns
    # "process" into "proces" and "analysis" into "analysi", which then match nothing.
    if word.endswith(("ss", "us", "is")):
        return word
    for suffix in ("ing", "ied", "ies", "es", "ed", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> set[str]:
    return {stem(word) for word in re.findall(r"[a-z0-9]+", text.lower())
            if word not in STOPWORDS}


def parse_list(raw: str) -> list[str]:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    return [item.strip().strip("\"'") for item in raw.split(",") if item.strip()]


def load_catalog() -> dict[str, dict[str, list[str]]]:
    catalog: dict[str, dict[str, list[str]]] = {}
    for path in sorted(SKILLS.glob("*/*/SKILL.md")):
        head = path.read_text(encoding="utf-8").split("---")[1]
        fields = {}
        for key in ("scope_triggers", "scope_answers"):
            match = re.search(rf"^{key}:\s*(\[.*?\])\s*$", head, re.M)
            fields[key] = parse_list(match.group(1)) if match else []
        catalog[path.parent.name] = fields
    return catalog


def document_frequency(catalog: dict[str, dict[str, list[str]]]) -> dict[str, float]:
    """How many skills each token appears under, as an inverse weight.

    Without this, a verb that appears in half the catalog ("write", "review") decides
    ties between skills it says nothing about. A token carried by four skills or fewer
    keeps full weight; the rest falls off as `4 / count`.
    """
    counts: dict[str, int] = {}
    for fields in catalog.values():
        seen: set[str] = set()
        for phrase in fields["scope_triggers"] + fields["scope_answers"]:
            seen |= tokens(phrase)
        for token in seen:
            counts[token] = counts.get(token, 0) + 1
    return {token: min(1.0, 4.0 / count) for token, count in counts.items()}


def phrase_score(phrase: str, prompt: set[str], weights: dict[str, float]) -> float:
    own = tokens(phrase)
    if not own:
        return 0.0
    matched = sum(weights.get(token, 0.0) for token in own & prompt)
    total = sum(weights.get(token, 0.0) for token in own)
    return matched / total if total else 0.0


def score_skill(fields: dict[str, list[str]], prompt: set[str],
                weights: dict[str, float]) -> float:
    best_trigger = max((phrase_score(t, prompt, weights) for t in fields["scope_triggers"]),
                       default=0.0)
    best_answer = max((phrase_score(a, prompt, weights) for a in fields["scope_answers"]),
                      default=0.0)
    if best_trigger < FLOOR and best_answer < FLOOR:
        return 0.0
    return best_trigger * TRIGGER_WEIGHT + best_answer


def route(prompt: str, catalog: dict[str, dict[str, list[str]]]) -> tuple[str, list[tuple[str, float]]]:
    body = tokens(prompt)
    weights = document_frequency(catalog)
    scored = sorted((((name, score_skill(fields, body, weights)) for name, fields in catalog.items())),
                    key=lambda pair: pair[1], reverse=True)
    if not scored or scored[0][1] == 0.0:
        return "none", scored[:3]
    if len(scored) > 1 and scored[0][1] == scored[1][1]:
        return "ambiguous", scored[:3]
    return scored[0][0], scored[:3]


def load_corpus() -> list[dict[str, str]]:
    if not CORPUS.is_file():
        return []
    rows = []
    for line in CORPUS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 on an ambiguous match, a miss, or below the recorded floor")
    parser.add_argument("--show-misses", action="store_true",
                        help="print every prompt that did not route to its expected skill")
    parser.add_argument("--floor", type=float, default=None, metavar="RATIO",
                        help="override the floor from library/routing.json (0..1)")
    args = parser.parse_args(argv)

    catalog = load_catalog()
    corpus = load_corpus()
    if not corpus:
        print(f"routing-score: no corpus at {CORPUS.relative_to(REPO)}", file=sys.stderr)
        return 2

    correct = ambiguous = missed = wrong = 0
    misses: list[str] = []
    for row in corpus:
        prompt, expect = row["prompt"], row["expect"]
        got, top = route(prompt, catalog)
        if got == "ambiguous":
            ambiguous += 1
            misses.append(f"AMBIGUOUS  {prompt!r}\n           ties: "
                          + ", ".join(f"{name}={score:.2f}" for name, score in top[:3]))
        elif got == "none":
            missed += 1
            misses.append(f"NONE       {prompt!r}")
        elif got == expect:
            correct += 1
        else:
            wrong += 1
            misses.append(f"WRONG      {prompt!r} -> {got} (expected {expect})")

    total = len(corpus)
    ratio = correct / total if total else 0.0
    print(f"routing: {correct}/{total} correct ({ratio:.0%}), {wrong} wrong, "
          f"{ambiguous} ambiguous, {missed} unmatched")

    if args.show_misses or (args.strict and misses):
        for line in misses:
            print(f"  {line}")

    floor = 0.0
    if BASELINE.is_file():
        floor = float(json.loads(BASELINE.read_text(encoding="utf-8")).get("floor", 0.0))
    if args.floor is not None:
        floor = args.floor
    print(f"floor: {floor:.0%}")

    if not args.strict:
        return 0
    if ambiguous or missed:
        return 1
    if ratio < floor:
        print(f"routing-score: {ratio:.0%} is below the recorded floor of {floor:.0%}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())