# Checking a change's shape without the CLI

`openspec validate --strict` needs Node. Inside a container image, a sandbox, or an agent runtime
that ships no Node, the change still has to be checked before it is presented as a handover. Encode
the rules below in the host language; they are the ones the CLI enforces, so a shape that passes
here would pass there.

Keep it **structural**. `validate --strict` checks shape, not truth — an offline checker that
invents extra rules rejects legitimate work, and one that checks less proves nothing.

## The rules, and what to assert

| Rule | Assertion |
|---|---|
| proposal exists | `proposal.md` present |
| proposal says why | contains `## Why` and `## What Changes` |
| a capability delta exists | at least one `specs/<capability>/spec.md` |
| requirements are real | a `### Requirement: <non-space>` block exists in each spec |
| every requirement is testable | each block contains at least one `#### Scenario:` |
| every scenario is observable | each scenario body contains both `**WHEN**` and `**THEN**` |
| tasks are trackable | `tasks.md` contains at least one `- [ ]` **or** `- [x]` item |
| a new capability has a purpose | (only when creating one) `## Purpose` with 50+ characters |

Two of these look pedantic and are not, because they were both wrong on a first attempt:

- **A task is a checkbox, checked or not.** An *archived* change has every task ticked, so
  requiring an open `- [ ]` rejects exactly the well-formed work you are validating against.
- **`changes/archive/` is not a change.** Scaffolding a change directory creates it; iterating
  `changes/*` and treating every directory as a change reports a correct scaffold as malformed.

## Empty is not valid

A change directory holding only `.openspec.yaml` is an **empty** change. Report it as invalid
(list the three missing paths); do not let "a directory exists" read as "a change exists". This
is the failure a model produces when it runs `openspec new change` and `openspec instructions` and
stops before authoring — the instructions output saved to a `.instructions.txt` is a symptom, not
an artifact.

## Test the checker against a real change

Fixtures only cover the malformations you imagined. Validate the checker against a change the tool
actually produced — one from `openspec/changes/archive/` in any repo that carries the container —
and skip that test when no such checkout is present. Both of the bugs above were found that way,
not by the fixtures.

## Sketch

```python
def validate_handover(changes_root: Path) -> dict:
    result = {"found": False, "valid": False, "problems": []}
    if not changes_root.is_dir():
        return result
    changes = sorted(p for p in changes_root.iterdir()
                     if p.is_dir() and p.name != "archive")   # bookkeeping, not a change
    if not changes:
        return result
    result["found"] = True
    for change in changes:
        problems = []
        proposal = change / "proposal.md"
        specs = sorted((change / "specs").rglob("spec.md")) if (change / "specs").is_dir() else []
        tasks = change / "tasks.md"
        if not proposal.is_file():
            problems.append("proposal.md missing")
        else:
            text = proposal.read_text(encoding="utf-8")
            problems += [f"proposal.md: no `{h}`" for h in ("## Why", "## What Changes")
                         if h not in text]
        if not specs:
            problems.append("no specs/<capability>/spec.md")
        for spec in specs:
            text = spec.read_text(encoding="utf-8")
            if not re.search(r"^### Requirement: \S", text, re.M):
                problems.append(f"{spec.name}: no `### Requirement:` block")
            for block in re.split(r"^### Requirement: ", text, flags=re.M)[1:]:
                name = block.splitlines()[0].strip() or "(unnamed)"
                scenarios = re.split(r"^#### Scenario: ", block, flags=re.M)[1:]
                if not scenarios:
                    problems.append(f"requirement '{name}' has no scenario")
                for sc in scenarios:
                    if "**WHEN**" not in sc or "**THEN**" not in sc:
                        problems.append(f"scenario '{sc.splitlines()[0].strip()}' needs WHEN and THEN")
        if not tasks.is_file():
            problems.append("tasks.md missing")
        elif not re.search(r"^\s*- \[[ xX]\] \S", tasks.read_text(encoding="utf-8"), re.M):
            problems.append("tasks.md: no checkbox task")
        result["problems"] += [f"{change.name}: {p}" for p in problems]
    result["valid"] = not result["problems"]
    return result
```

Record the result where the reader will meet it — the verdict, the console output, a JSON sidecar
and the handover document — and treat an absent or malformed change as a **recorded deviation**,
never as silence. A handover nobody validated is a handover that will be trusted wrongly.
