"""scope.py — scope, portability and domain-contract rules.

Imported by ``scripts/validate.py``, which owns the frontmatter parser and the
Result type; this module owns only the rules added with the scope contract. One
implementation per rule stays true: the parser is not copied here.

Rules:
  * every skill declares ``writes``, drawn from the symbolic roots the contract
    allows — never an absolute path;
  * a skill that writes anything opens with the POSIX root preamble, so a user
    can redirect its output without editing the skill;
  * fenced commands carry no FHS path (``/usr``, ``/etc``, ``/var``, ``/opt``,
    ``/srv``, ``/home``) and no Windows user path, unless the line opts out with
    ``# portable-ok: <reason>``;
  * every category holds a ``CATEGORY.md`` whose question is stated and whose
    "not here" pointers name real skills;
  * no two skills claim the same trigger phrase;
  * every alias in ``library/aliases.json`` resolves and shadows nothing.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

FENCE = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.S)
PORTABLE_OK = re.compile(r"portable-ok:\s*\S")
WIN_HOME = re.compile(r"[A-Za-z]:\\\\Users\\\\")
QUESTION = re.compile(r"\*\*Question\.\*\*\s*(.+)")
NOT_HERE = re.compile(r"\*\*Not here\.\*\*\s*(.*)", re.S)
PREAMBLE = ': "${SKILL_'
WRITE_TARGET = re.compile(r"(?:^\s*(?:chown|chmod|cp|mv|mkdir|install|tee|printf|echo|cat|dd)\b)|(?:(?:^|\s)\d?>>?\s*\S)")


def _contains_prefix(line: str, prefixes: list[str]) -> str | None:
    for prefix in prefixes:
        if re.search(rf"(?<![\w.]){re.escape(prefix)}(/|\b)", line):
            return prefix
    return None


ANNOUNCE = re.compile(r"\*\*Heads-up\.\*\*", re.I)


def _write_tiers(contract: dict) -> tuple[set[str], set[str]]:
    raw = contract.get("allowed_writes") or {}
    if isinstance(raw, list):          # a v3 contract predates the tier split
        return set(raw), set()
    return set(raw.get("project") or ()), set(raw.get("declared") or ())


def check_writes(skills, parsed, contract, repo, result, parse_list) -> None:
    project, declared = _write_tiers(contract)
    vocabulary = set(contract.get("side_effects") or ())
    for path in skills:
        fields, body = parsed[path]
        where = path.relative_to(repo)

        raw = (fields.get("writes") or "").strip()
        if not raw:
            result.fail(where, "frontmatter is missing `writes`; use `[none]` when the skill "
                               "changes nothing on disk")
            continue
        targets = parse_list(raw)
        if not targets:
            result.fail(where, f"`writes: {raw}` names nothing; use `[none]` or a root")
            continue
        for target in targets:
            if target not in project | declared:
                result.fail(where, f"`writes` names `{target}`, not one of "
                                   f"{sorted(project | declared)} — absolute paths are not portable")

        effects_raw = (fields.get("side_effects") or "").strip()
        if not effects_raw:
            result.fail(where, "frontmatter is missing `side_effects`; use `[none]` when the "
                               "skill spawns nothing the user must know about")
            continue
        effects = parse_list(effects_raw)
        unknown = [e for e in effects if e not in vocabulary]
        if unknown:
            result.fail(where, f"`side_effects` names {unknown}, not in {sorted(vocabulary)}")
        active = [e for e in effects if e != "none"]
        outside = [t for t in targets if t in declared]

        if outside or active:
            if not ANNOUNCE.search(body):
                what = ", ".join(outside + active) or "a declared root"
                result.fail(where, f"declares {what} outside the project but never tells the "
                                   "reader — add a `**Heads-up.**` paragraph")
        if targets != ["none"] and PREAMBLE not in body:
            result.fail(where, "`writes` is not `none` but the body has no root preamble; open "
                               "with `: \"${SKILL_PROJECT:=...}\"` so a user can redirect it")
        if targets != ["none"] and not (fields.get("leaves") or "").strip():
            result.fail(where, "`writes` is not `none` but `leaves` does not say what remains")


def check_domain_contracts(repo, skills, contract, result) -> None:
    filename = contract.get("domain_contract") or "CATEGORY.md"
    known = {p.parent.name for p in skills}
    roots = sorted({p.parent.parent.name for p in skills})
    for category in roots:
        doc = repo / "skills" / category / filename
        if not doc.is_file():
            result.fail(f"skills/{category}", f"no {filename}: a domain must state its question "
                                              f"and what belongs elsewhere")
            continue
        text = doc.read_text(encoding="utf-8", errors="replace")
        question = QUESTION.search(text)
        if question is None or len(question.group(1).strip()) < 10:
            result.fail(doc.relative_to(repo), f"{filename} states no `**Question.**` line")
        not_here = NOT_HERE.search(text)
        if not_here is None:
            result.fail(doc.relative_to(repo), f"{filename} has no `**Not here.**` section")
            continue
        for name in re.findall(r"`([a-z0-9][a-z0-9-]{2,})`", not_here.group(1)):
            if name not in known:
                result.fail(doc.relative_to(repo),
                            f"`Not here` names `{name}`, which is not a catalog skill")


def check_triggers(skills, parsed, contract, result, repo) -> None:
    """A trigger phrase belongs to exactly one skill."""
    owner: dict[str, Path] = {}
    for path in skills:
        fields, _ = parsed[path]
        raw = (fields.get("scope_triggers") or "").strip()
        for trigger in raw.strip("[]").split(","):
            norm = " ".join(re.findall(r"[a-z0-9]+", trigger.lower()))
            if len(norm) < 8:
                continue
            if norm in owner and owner[norm] != path:
                result.fail(path.relative_to(repo),
                            f"trigger `{trigger.strip()}` is already claimed by "
                            f"{owner[norm].parent.name}")
            else:
                owner[norm] = path


def check_portability(skills, parsed, contract, repo, result) -> None:
    """User-space paths fail; system paths are reported unless written to.

    A systemd unit's ``/usr/bin`` is the system being described, not a location the
    reader configures. ``/home`` and a Windows user profile are always the reader's
    space, so they fail. A system prefix fails only when the line writes to it.
    """
    fail_prefixes = list(contract.get("fhs_fail_prefixes") or ("/home",))
    note_prefixes = list(contract.get("fhs_note_prefixes") or ())
    for path in skills:
        _, body = parsed[path]
        for block in FENCE.findall(body):
            for raw in block.splitlines():
                line = raw.rstrip()
                if not line.strip() or PORTABLE_OK.search(line):
                    continue
                where = path.relative_to(repo)
                if WIN_HOME.search(line):
                    result.fail(where, "fenced command hardcodes a Windows user path: "
                                       f"{line.strip()[:70]}")
                    break
                hit = _contains_prefix(line, fail_prefixes)
                if hit:
                    result.fail(where, f"fenced command hardcodes {hit}; use a symbolic root or "
                                       f"`# portable-ok: <reason>`: {line.strip()[:70]}")
                    break
                noted = _contains_prefix(line, note_prefixes)
                if noted and WRITE_TARGET.search(line):
                    result.fail(where, f"fenced command writes to {noted}; use a symbolic root: "
                                       f"{line.strip()[:70]}")
                    break
                if noted:
                    result.notes.append(f"{where}: system path {noted} in a fenced command")


def check_aliases(repo, skills, contract, result) -> None:
    rel = contract.get("aliases")
    if not rel:
        return
    path = repo / rel
    if not path.is_file():
        return
    known = {p.parent.name for p in skills}
    try:
        table = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result.fail(rel, f"not valid JSON: {exc}")
        return
    for old, new in table.items():
        if old in known:
            result.fail(rel, f"alias `{old}` shadows a real skill")
        if new not in known:
            result.fail(rel, f"alias `{old}` points at `{new}`, which does not exist")


def check_scope(skills, parsed, contract, repo, result, parse_list) -> None:
    if not contract.get("scope_fields"):
        return  # a v2 contract predates these rules
    check_writes(skills, parsed, contract, repo, result, parse_list)
    check_domain_contracts(repo, skills, contract, result)
    check_triggers(skills, parsed, contract, result, repo)
    check_portability(skills, parsed, contract, repo, result)
    check_aliases(repo, skills, contract, result)
