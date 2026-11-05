"""library-guard — the skill library's contract, enforced where the writes happen.

Hermes chooses a skill by the first 57 characters of its `description` and by the frontmatter it
can parse. A violation of either is invisible until `nix flake check`, which runs minutes later,
in another process, usually after the turn that made it. This plugin makes two of the rules
`AGENTS.md` states into runtime facts:

- ``transform_tool_result`` — after a ``SKILL.md`` is written, the file is read back and validated;
  a violation returns a note naming the field and the fix, inside the same tool result, so the
  model corrects it while it still has the context.
- ``pre_tool_call`` — a write into a skill Hermes owns (a name in ``.bundled_manifest``) is refused,
  because ``hermes update`` rewrites that directory and the divergence stays silent until it bites.

The values live in ``library/contract.json`` — one home, shared with ``nix/tests.nix`` and
``scripts/skill-contract.py``. :data:`DEFAULTS` mirrors that file for a wheel installed away from
the repository, and a test asserts the two are equal so the mirror cannot rot.

Fail-open by design: every hook swallows its own errors and returns ``None``. A guard that can
break a tool call is worse than a missing one.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CONTRACT_SCHEMA = "skill-contract/v1"
NOTE_PREFIX = "[library-guard]"

#: Mirror of ``library/contract.json``. The test suite asserts equality whenever the repository
#: contract is reachable, so this is a copy with an owner, not a second source.
DEFAULTS: Dict[str, Any] = {
    "schema": CONTRACT_SCHEMA,
    "description_window": 57,
    "required_frontmatter": ["name", "description", "version", "author", "license", "platforms"],
    "categories": [
        "autonomous-ai-agents",
        "communication",
        "devops",
        "note-taking",
        "productivity",
        "security",
        "software-development",
    ],
    "support_dirs": ["assets", "references", "templates", "scripts", "examples"],
    "gate_command": "nix flake check",
}

#: Frontmatter keys whose value must be a bracketed list.
LIST_FIELDS = ("platforms",)

_CONTRACT: Optional[Dict[str, Any]] = None
_BUNDLED: Optional[frozenset] = None


def repository_root(start: Optional[Path] = None) -> Optional[Path]:
    """The clone this file is installed in, found by walking up to ``library/contract.json``.

    Returns ``None`` for a wheel installed outside the repository — the caller then falls back to
    :data:`DEFAULTS` instead of guessing a path.
    """
    here = (start or Path(__file__)).resolve()
    for parent in [here, *here.parents][:6]:
        if (parent / "library" / "contract.json").is_file():
            return parent
    return None


def contract() -> Dict[str, Any]:
    """The repository contract when reachable, else the mirror. Cached for the process."""
    global _CONTRACT
    if _CONTRACT is None:
        root = repository_root()
        if root is not None:
            try:
                _CONTRACT = json.loads((root / "library" / "contract.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _CONTRACT = dict(DEFAULTS)
        else:
            _CONTRACT = dict(DEFAULTS)
    return _CONTRACT


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def bundled_names() -> frozenset:
    """Skill names Hermes ships and rewrites on update, one ``name:hash`` per line."""
    global _BUNDLED
    if _BUNDLED is None:
        names = set()
        try:
            text = (hermes_home() / "skills" / ".bundled_manifest").read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    names.add(line.split(":", 1)[0].strip())
        except OSError:
            names = set()
        _BUNDLED = frozenset(names)
    return _BUNDLED


def parse_frontmatter(text: str) -> Tuple[Dict[str, str], Optional[str]]:
    """Top-level scalar keys of the leading ``---`` block; ``(fields, error)``."""
    if not text.startswith("---"):
        return {}, "the file does not start with a '---' frontmatter block"
    end = text.find("\n---", 3)
    if end == -1:
        return {}, "the frontmatter block is never closed with '---'"
    fields: Dict[str, str] = {}
    for raw in text[3:end].splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or raw[:1].isspace():
            continue  # nested metadata is not a top-level key
        key, sep, value = raw.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields, None


def check_skill_text(text: str, dirname: str, settings: Optional[Dict[str, Any]] = None) -> List[str]:
    """Every way one ``SKILL.md`` breaks the contract, each message naming the fix.

    Pure: no filesystem, no globals beyond the default contract. This is the function the runtime
    hook, the CLI and the test suite all call, so a rule exists once.
    """
    cfg = settings or contract()
    window = int(cfg["description_window"])
    violations: List[str] = []

    if "\r\n" in text:
        violations.append("the file has CRLF line endings; the gate rejects them — write LF")

    fields, error = parse_frontmatter(text)
    if error:
        violations.append(error)
        return violations

    for key in cfg["required_frontmatter"]:
        if not fields.get(key):
            violations.append(f"frontmatter is missing `{key}`")

    name = fields.get("name", "").strip()
    if name and name != dirname:
        violations.append(f"`name: {name}` does not match its directory `{dirname}`")

    description = fields.get("description", "").strip().strip('"').strip("'")
    if description and len(description) > window:
        violations.append(
            f"`description` is {len(description)} characters; the index window is {window}, so the "
            f"model never sees past character {window} — cut {len(description) - window}"
        )

    for key in LIST_FIELDS:
        raw = fields.get(key, "")
        if raw and not (raw.startswith("[") and raw.endswith("]")):
            violations.append(f"`{key}` must be a bracketed list, found `{raw}`")

    return violations


def target_path(args: Dict[str, Any]) -> Optional[Path]:
    """The path a write-shaped tool call would touch, or ``None``."""
    raw = args.get("path") or args.get("file_path") or ""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return Path(raw).expanduser()
    except (OSError, ValueError):
        return None


def owned_skill(path: Path) -> Optional[str]:
    """The bundled skill name this path belongs to, if any.

    ``$HERMES_HOME/skills/<name>/…`` or ``$HERMES_HOME/skills/<category>/<name>/…`` where ``<name>``
    is in ``.bundled_manifest``. Anything else — including this repository's mounted tree — is not
    Hermes's to overwrite, so it returns ``None``.
    """
    try:
        rel = path.resolve().relative_to((hermes_home() / "skills").resolve())
    except (OSError, ValueError):
        return None
    parts = rel.parts
    if not parts:
        return None
    names = bundled_names()
    if parts[0] in names:
        return parts[0]
    if len(parts) > 1 and parts[1] in names:
        return parts[1]
    return None


def _note(path: Path, violations: List[str]) -> str:
    head = f"{NOTE_PREFIX} {path.name} in {path.parent.name} does not satisfy library/contract.json:"
    body = "\n".join(f"  - {v}" for v in violations)
    return f"{head}\n{body}\nFix it now: the next `nix flake check` will fail on the same lines."


def record(event: str, path: Optional[Path], detail: Any) -> None:
    """One JSONL line per action, in ``$HERMES_HOME/logs/library-guard/``.

    A guard that leaves no trace is unfalsifiable: the operator cannot tell "nothing violated the
    contract" from "the plugin never loaded". Same shape as the harness-audit log, one directory
    over, and equally fail-open.
    """
    try:
        directory = hermes_home() / "logs" / "library-guard"
        directory.mkdir(parents=True, exist_ok=True)
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        line = json.dumps(
            {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "event": event,
                "path": str(path) if path else "",
                "home": str(hermes_home()),
                "detail": detail,
            },
            ensure_ascii=False,
        )
        with (directory / f"{day}.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
    except Exception:  # noqa: BLE001 - evidence must never break the guard
        pass


# --- hooks ------------------------------------------------------------------


def on_pre_tool_call(**kwargs: Any) -> Optional[Dict[str, str]]:
    """Refuse a write into a skill ``hermes update`` owns. Everything else proceeds."""
    try:
        tool_name = str(kwargs.get("tool_name") or "")
        if tool_name not in ("write_file", "patch"):
            return None
        args = kwargs.get("args") or {}
        if not isinstance(args, dict):
            return None
        path = target_path(args)
        if path is None:
            return None
        # A CRLF write into a skill is refused outright. The tree is LF-only, the gate rejects CRLF,
        # and the unattended reviewer has produced it twice — a note arrives after the damage, and
        # the damage is a red gate nobody is watching. The payload is checked *before* the write.
        if path.name == "SKILL.md":
            payload = args.get("content")
            if payload is None:
                payload = args.get("new_string")
            if isinstance(payload, str) and "\r\n" in payload:
                record("block", path, {"reason": "crlf"})
                return {
                    "action": "block",
                    "message": (
                        f"library-guard blocked a CRLF write to `{path.name}` in `{path.parent.name}`: "
                        "this tree is LF-only and `nix flake check` rejects CRLF. Rewrite the content "
                        "with LF line endings and retry."
                    ),
                }

        name = owned_skill(path)
        if name is None:
            return None
        record("block", path, {"skill": name})
        return {
            "action": "block",
            "message": (
                f"library-guard blocked a write to `{path}`: `{name}` is a bundled skill. "
                "`hermes update` rewrites that directory, so the edit is lost and the divergence is "
                "silent until it bites (AGENTS.md rule 1). Author it as a local skill instead: "
                f"`skills/<category>/{name}/SKILL.md` in hermes-skills, then `git add`."
            ),
        }
    except Exception:  # noqa: BLE001 - a guard must never break a tool call
        return None


def on_transform_tool_result(**kwargs: Any) -> Optional[Any]:
    """After a ``SKILL.md`` write, return the tool result with the contract violations appended."""
    try:
        tool_name = str(kwargs.get("tool_name") or kwargs.get("function_name") or "")
        if tool_name not in ("write_file", "patch"):
            return None
        args = kwargs.get("args") or kwargs.get("function_args") or {}
        if not isinstance(args, dict):
            return None
        path = target_path(args)
        if path is None or path.name != "SKILL.md" or not path.is_file():
            return None
        violations = check_skill_text(path.read_text(encoding="utf-8", errors="replace"), path.parent.name)
        if not violations:
            return None
        record("note", path, violations)
        note = _note(path, violations)
        result = kwargs.get("result")
        if isinstance(result, str):
            return f"{result}\n\n{note}"
        if isinstance(result, dict):
            return {**result, "library_guard": note}
        return note
    except Exception:  # noqa: BLE001
        return None


def register(ctx: Any) -> None:
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("transform_tool_result", on_transform_tool_result)