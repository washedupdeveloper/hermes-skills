#!/usr/bin/env python3
"""validate.py — the skill library's gate. Standard library only.

    python3 scripts/validate.py                 # every rule, over the whole tree
    python3 scripts/validate.py --check PATH    # one SKILL.md
    python3 scripts/validate.py --json          # machine-readable result
    python3 scripts/validate.py --extra-root D  # resolve related_skills against another library

Exit 0 clean, 1 violations, 2 when the scan found no skills (a scan over nothing
passes, and would look identical to a clean tree).

This is the only implementation of every rule here. `nix flake check` runs this
file; it does not restate the rules in Nix. A rule added here is enforced on
every host, with or without Nix, which is the point of the project.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = "skills"
SUPPORT_FALLBACK = ("references", "templates", "assets", "scripts", "examples")

SKIP_DIRS = {".git", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
             "node_modules", "result", ".direnv"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip",
                 ".gz", ".tar", ".xz", ".woff", ".woff2", ".ttf", ".otf", ".so",
                 ".pyc", ".vsix", ".lock"}

WRITE_VERBS = re.compile(r"\b(write|create|add|author|generate|scaffold|produce)\b", re.I)
ILLUSTRATION = re.compile(r"\b(becomes|turns into)\b|→|->")
FENCE = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.S)


class Result:
    """Violations, each of the form `<where>: <what>`, plus the counts the docs state."""

    def __init__(self) -> None:
        self.violations: list[str] = []
        self.notes: list[str] = []
        self.counts: dict[str, int] = {}

    def fail(self, where: str | Path, what: str) -> None:
        # Two rules can catch one defect: the per-file check sees a CRLF `SKILL.md`, and the
        # tree sweep sees the same file again. Report it once — a duplicate makes a reader
        # chase a count that is really one file.
        line = f"{where}: {what}"
        if line not in self.violations:
            self.violations.append(line)


# ── the contract ────────────────────────────────────────────────────────────

def load_contract(repo: Path = REPO) -> dict:
    path = repo / "library" / "contract.json"
    if not path.is_file():
        raise SystemExit(f"validate: no contract at {path} — this is not the library root")
    return json.loads(path.read_text(encoding="utf-8"))


def support_dirs(contract: dict) -> tuple[str, ...]:
    return tuple(contract.get("support_dirs") or SUPPORT_FALLBACK)


def catalog(repo: Path, contract: dict) -> list[Path]:
    """Every catalog SKILL.md: `<category>/<skill>/SKILL.md`, never inside a support dir."""
    support = set(support_dirs(contract))
    found = []
    for path in sorted((repo / SKILLS).glob("*/*/SKILL.md")):
        parts = path.relative_to(repo / SKILLS).parts
        if support & set(parts[1:-1]):
            continue
        found.append(path)
    return found


# ── frontmatter ─────────────────────────────────────────────────────────────

def parse_frontmatter(text: str) -> tuple[dict[str, str], str | None, str]:
    """Top-level scalar keys of the leading `---` block, and the body after it."""
    if not text.startswith("---"):
        return {}, "the file does not start with a '---' frontmatter block", ""
    end = re.search(r"\n---\s*\n", text[3:])
    if end is None:
        return {}, "the frontmatter block is never closed with '---'", ""
    fields: dict[str, str] = {}
    for raw in text[3:end.start() + 3].splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or raw[:1].isspace():
            continue
        key, sep, value = raw.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields, None, text[end.end() + 3:]


def parse_list(raw: str) -> list[str]:
    """`[a, b]` or a bare `a` — the two forms a scalar frontmatter value takes."""
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    return [x.strip().strip("\"'") for x in raw.split(",") if x.strip()]


def read_raw(path: Path) -> str:
    """Text with its newlines intact.

    `Path.read_text` translates CRLF to LF, which would hide the one rule that exists
    to find it. Every gate read of a skill goes through here.
    """
    return path.read_bytes().decode("utf-8", "replace")


def check_skill_text(text: str, dirname: str, contract: dict,
                     result: Result, where: str | Path) -> dict[str, str]:
    """Every per-file rule. Returns the parsed fields so the caller can reuse them."""
    window = int(contract["description_window"])
    hosts = set(contract.get("hosts") or ())

    if "\r\n" in text:
        result.fail(where, "CRLF line endings; this tree is LF-only")

    fields, error, _ = parse_frontmatter(text)
    if error:
        result.fail(where, error)
        return {}

    for key in contract["required_frontmatter"]:
        if not fields.get(key):
            result.fail(where, f"frontmatter is missing `{key}`")

    name = fields.get("name", "").strip()
    if name and name != dirname:
        result.fail(where, f"`name: {name}` does not match its directory `{dirname}`")

    description = fields.get("description", "").strip().strip('"').strip("'")
    if not description:
        result.fail(where, "`description` is empty; it is the only field the index shows")
    elif len(description) > window:
        result.fail(where, f"`description` is {len(description)} characters; the index window is "
                           f"{window} — cut {len(description) - window}")

    for key in ("platforms",):
        raw = fields.get(key, "")
        if raw and not (raw.startswith("[") and raw.endswith("]")):
            result.fail(where, f"`{key}` must be a bracketed list, found `{raw}`")

    # Any frontmatter line whose key the parser cannot read vanishes silently.
    m = re.search(r"\n---\s*\n", text[3:])
    for raw in text[3:m.start() + 3].splitlines() if m else []:
        if not raw.strip() or raw[:1].isspace() or raw.lstrip().startswith("#"):
            continue
        if ":" not in raw:
            result.fail(where, f"frontmatter line not parsed as `key: value`: {raw!r}")

    # Host scope: a host-prefixed directory must say which host it serves.
    targets = parse_list(fields.get("targets", ""))
    unknown = [t for t in targets if t not in hosts]
    if unknown:
        result.fail(where, f"`targets` names {unknown}, not in the contract's hosts {sorted(hosts)}")
    for host in hosts:
        if dirname.startswith(f"{host}-") and host not in targets:
            result.fail(where, f"`{dirname}` is host-scoped but declares no `targets: [{host}]`")

    return {**fields, "_targets": ",".join(targets)}


# ── the tree ────────────────────────────────────────────────────────────────

def check_tree(repo: Path, contract: dict, result: Result) -> list[Path]:
    skills = catalog(repo, contract)
    if not skills:
        raise SystemExit("validate: the scan found no skills — the tree is not where this expects it")

    seen: dict[str, Path] = {}
    for path in skills:
        name = path.parent.name
        if name in seen:
            result.fail(path.relative_to(repo), f"duplicate skill name, also at {seen[name]}")
        seen[name] = path.relative_to(repo)

    categories = {p.name for p in (repo / SKILLS).iterdir() if p.is_dir() and not p.name.startswith(".")}
    declared = set(contract.get("categories") or ())
    for extra in sorted(categories - declared):
        result.fail(f"{SKILLS}/{extra}", "category is on disk but not in library/contract.json")
    for missing in sorted(declared - categories):
        result.fail(f"{SKILLS}/{missing}", "category is declared in the contract but absent on disk")

    for entry in sorted((repo / SKILLS).iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        for child in sorted(entry.iterdir()):
            if child.is_dir() and not child.name.startswith(".") and not (child / "SKILL.md").is_file():
                result.fail(child.relative_to(repo), "skill directory holds no SKILL.md")

    return skills


def check_crlf(repo: Path, result: Result) -> None:
    for path in sorted(repo.rglob("*")):
        if not path.is_file() or path.suffix.lower() in SKIP_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in data:
            continue
        if b"\r\n" in data:
            result.fail(path.relative_to(repo), "CRLF line endings; this tree is LF-only")


def check_dead_references(skills: list[Path], repo: Path, result: Result) -> None:
    """A promised support file that does not exist is a broken pointer.

    Only POINTERS are checked: a path in a prescriptive sentence names a file to
    create, a placeholder names none, and a path shown being transformed is an
    illustration. A pointer that climbs out of the skill directory is broken even
    when the target exists in the repo, because a skill is read from its own
    directory alone.
    """
    for path in skills:
        _, error, body = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        if error:
            continue
        for line in body.splitlines():
            for m in re.finditer(r"`((?:references|templates|assets|scripts)/[^`\s]+)`", line):
                rel = m.group(1).rstrip(".")
                if "<" in rel or ">" in rel or "*" in rel or "?" in rel or "[" in rel:
                    continue  # a placeholder or a glob names no single file to dereference
                if WRITE_VERBS.search(line):
                    continue
                if not (path.parent / rel).exists():
                    result.fail(path.relative_to(repo), f"dead reference -> {rel}")
            for m in re.finditer(r"`(\.\./[^`\s]+)`", line):
                rel = m.group(1)
                if any(ch in rel for ch in "<>…*"):
                    continue
                if WRITE_VERBS.search(line) or ILLUSTRATION.search(line):
                    continue
                result.fail(path.relative_to(repo), f"dead reference -> {rel} (escapes the skill dir)")


def check_fenced_commands(repo: Path, result: Result) -> None:
    """A fenced command that runs a script this skill ships must find it.

    Only paths into a directory the skill itself ships are checked: a `scripts/x.py`
    in a skill with no `scripts/` belongs to another repository.
    """
    for path in sorted((repo / SKILLS).rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        skill_dir = path.parent if path.name == "SKILL.md" else next(
            (a for a in path.parents if (a / "SKILL.md").is_file()), path.parent)
        text = path.read_text(encoding="utf-8", errors="replace")
        for block in FENCE.findall(text):
            for raw in block.splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if any(c in line for c in "<>$") or WRITE_VERBS.search(line):
                    continue
                for ref in re.findall(r"\b((?:scripts|references|templates|assets)/[\w./-]+\.\w+)", line):
                    if not (skill_dir / ref.split("/", 1)[0]).is_dir():
                        continue
                    # A skill that documents this repository cites paths from its root
                    # (`python3 scripts/validate.py`); a skill that ships its own helper
                    # cites its own. The path is dead only when it exists at neither.
                    if not (skill_dir / ref).exists() and not (repo / ref).exists():
                        result.fail(path.relative_to(repo), f"dead path in a fenced command -> {ref}")


def check_related_skills(skills: list[Path], contract: dict, extra_roots: list[Path],
                         repo: Path, result: Result) -> None:
    known = {p.parent.name for p in skills}
    for root in extra_roots:
        if root.is_dir():
            known |= {p.parent.name for p in root.rglob("SKILL.md")}
    allowed = set(contract.get("external_skills") or ())
    for path in skills:
        fields, error, _ = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        if error:
            continue
        for ref in parse_list(fields.get("related_skills", "")):
            if ref in known or ref in allowed:
                continue
            result.fail(path.relative_to(repo),
                        f"`related_skills` names `{ref}`, which is neither here nor in "
                        f"library/contract.json's `external_skills`")


# ── the documents ───────────────────────────────────────────────────────────

def readme_counts(repo: Path, skills: list[Path], contract: dict, result: Result) -> None:
    readme = repo / "README.md"
    if not readme.is_file():
        result.fail("README.md", "missing")
        return
    text = readme.read_text(encoding="utf-8")
    total = len(list((repo / SKILLS).rglob("SKILL.md")))
    windows = sum(1 for p in skills
                  if not (m := re.search(r"^platforms:\s*(.+)$",
                                         p.read_text(encoding="utf-8").split("---", 2)[1], re.M))
                  or "windows" in m.group(1))
    rubrics = len(list((repo / SKILLS).rglob("assets/rubrics/*/SKILL.md")))
    result.counts = {"skill_md": total, "catalog": len(skills), "windows": windows, "rubrics": rubrics}

    m = re.search(r"^(\d+) `SKILL\.md` across (\d+) skills — (\d+) load on Windows", text, re.M)
    if m is None:
        result.fail("README.md", "the headline count sentence is gone or reworded")
    elif (int(m[1]), int(m[2]), int(m[3])) != (total, len(skills), windows):
        result.fail("README.md", f"headline states {(m[1], m[2], m[3])}, tree has "
                                 f"{(total, len(skills), windows)}")


def check_layout(repo: Path, skills: list[Path, ], contract: dict, result: Result) -> None:
    """The layout tree in README must be the filesystem, category by category."""
    readme = repo / "README.md"
    if not readme.is_file():
        return
    text = readme.read_text(encoding="utf-8")
    m = re.search(r"```\nskills/\n(.*?)```", text, re.S)
    if m is None:
        result.fail("README.md", "the layout tree is gone")
        return
    glyphs = {"│", "├──", "└──"}
    declared: dict[str, set[str]] = {}
    current = None
    for line in m.group(1).splitlines():
        name = re.match(r"[├└]── ([a-z0-9-]+)/", line)
        if name:
            current = name.group(1)
            declared[current] = set()
            rest = line.split("/", 1)[1] if "/" in line else ""
            declared[current] |= {t for t in rest.split() if t not in glyphs}
            continue
        if current and line.strip():
            declared[current] |= {t for t in line.split() if t not in glyphs}
    on_disk = {p.parent.parent.name: {q.parent.name for q in skills if q.parent.parent.name == p.parent.parent.name}
               for p in skills}
    for category in sorted(set(declared) | set(on_disk)):
        if category not in declared:
            result.fail("README.md", f"layout tree omits category `{category}`")
        elif category not in on_disk:
            result.fail("README.md", f"layout tree declares category `{category}`, absent on disk")
        else:
            missing = sorted(on_disk[category] - declared[category])
            extra = sorted(declared[category] - on_disk[category])
            if missing:
                result.fail("README.md", f"layout tree omits {missing} from `{category}`")
            if extra:
                result.fail("README.md", f"layout tree names {extra} in `{category}`, absent on disk")


def check_host_table(repo: Path, skills: list[Path], result: Result) -> None:
    """Every host-scoped skill is listed in the README table, and every row names one."""
    readme = repo / "README.md"
    if not readme.is_file():
        return
    text = readme.read_text(encoding="utf-8")
    m = re.search(r"^## Host-scoped skills\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    labelled = set()
    for path in skills:
        fields, _, _ = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        if parse_list(fields.get("targets", "")):
            labelled.add(path.parent.name)
    if m is None:
        if labelled:
            result.fail("README.md", f"no `## Host-scoped skills` table, but {len(labelled)} skills "
                                     f"declare `targets`: {sorted(labelled)}")
        return
    listed = set(re.findall(r"^\|\s*`([a-z0-9-]+)`\s*\|", m.group(1), re.M))
    for name in sorted(labelled - listed):
        result.fail("README.md", f"`{name}` declares `targets` but is absent from the host table")
    for name in sorted(listed - labelled):
        result.fail("README.md", f"the host table lists `{name}`, whose frontmatter declares no `targets`")


def check_upstream_ledger(repo: Path, skills: list[Path], result: Result) -> None:
    """'Taken' skills must exist here; 'rejected' ones must not."""
    ledger = repo / "docs" / "upstream.md"
    if not ledger.is_file():
        return
    names = {p.parent.name for p in skills}
    taken = not_taken = False
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            low = line.lower()
            if "not taken" in low:
                taken, not_taken = False, True
            elif line.startswith("## "):
                taken, not_taken = True, False
            continue
        m = re.match(r"\|\s*`([a-z0-9-]+)`\s*\|", line)
        if not m:
            continue
        name = m.group(1)
        if not_taken and name in names:
            result.fail("docs/upstream.md", f"rejected `{name}` is present in the repo")
        elif taken and not not_taken and name not in names:
            result.fail("docs/upstream.md", f"taken `{name}` is missing")


# ── entry point ─────────────────────────────────────────────────────────────

def validate(repo: Path = REPO, extra_roots: list[Path] | None = None,
             one: Path | None = None) -> Result:
    contract = load_contract(repo)
    result = Result()

    if one is not None:
        if not one.is_file():
            raise SystemExit(f"validate: no such file: {one}")
        check_skill_text(read_raw(one), one.parent.name, contract, result, one)
        return result

    skills = check_tree(repo, contract, result)
    for path in skills:
        check_skill_text(read_raw(path), path.parent.name, contract, result,
                         path.relative_to(repo))
    check_crlf(repo, result)
    check_dead_references(skills, repo, result)
    check_fenced_commands(repo, result)
    check_related_skills(skills, contract, extra_roots or [], repo, result)
    readme_counts(repo, skills, contract, result)
    check_layout(repo, skills, contract, result)
    check_host_table(repo, skills, result)
    check_upstream_ledger(repo, skills, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the skill library against library/contract.json.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("--check", metavar="PATH", help="validate one SKILL.md")
    parser.add_argument("--extra-root", action="append", default=[], metavar="DIR",
                        help="resolve related_skills against another library too (repeatable)")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument("--repo", metavar="DIR", default=str(REPO), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    result = validate(repo, [Path(p).resolve() for p in args.extra_root],
                      Path(args.check).resolve() if args.check else None)

    if args.json:
        print(json.dumps({"ok": not result.violations, "violations": result.violations,
                          "counts": result.counts}, indent=2))
    else:
        for violation in result.violations:
            print(violation)
        if result.counts:
            print(f"{result.counts['skill_md']} SKILL.md, {result.counts['catalog']} catalog skills, "
                  f"{result.counts['windows']} on Windows, {result.counts['rubrics']} rubrics")
        print(f"validate: {len(result.violations)} violation(s)")
    return 1 if result.violations else 0


if __name__ == "__main__":
    raise SystemExit(main())