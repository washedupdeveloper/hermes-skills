"""harness_audit — two harness invariants, implemented rather than described.

Importable two ways, and both are supported by Hermes:

* **directory drop** — ``plugins/harness-audit/__init__.py`` re-exports ``register`` from
  here, and the loader gives a directory plugin ``__path__ = [plugin_dir]`` so the
  relative import resolves;
* **pip / Nix** — this module IS the distribution, declared in ``pyproject.toml`` with the
  ``hermes_agent.plugins`` entry point, so ``extraPythonPackages`` can carry it and no file
  is copied into a profile by hand.

Read out of DeepSeek Harness and mapped onto Hermes mechanics that exist today:

1. **Model-visible means logged.** In dsh, anything reaching a model request must be
   reconstructable from the session log. Hermes keeps the conversation, but a tool call's
   *arguments and result* are only in the transcript, which context compression can
   rewrite. This plugin writes one durable JSONL line per call, so a run can be
   reconstructed after compression, after a restart, or from another profile.

2. **Discovery reports complete or incomplete, never absence.** A skill directory that
   cannot be read, or one whose frontmatter is unparseable, currently just yields fewer
   entries — indistinguishable from "the skill is not there". `harness_audit` reports the
   distinction explicitly.

What is deliberately NOT here, because Hermes has no seam for it: dsh's two invocation
switches (model-invocable vs user-invocable). Hermes gates skills at offer time on
relevance (`requires_toolsets`, `environments`, `platforms`, `skills.disabled`), which is
a different axis. Faking it with a naming convention would be advice, not a capability.

Nothing in this plugin reads credentials: arguments are reduced to key names and a
digest, and any value that looks like a secret is dropped before it is written.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

PLUGIN_DIR = Path(__file__).resolve().parent

#: Fields whose VALUE is never written, only its presence. A tool call's arguments are
#: model-authored text and may quote a credential the model read somewhere.
SENSITIVE_KEY = re.compile(
    r"(pass(word|wd)?|secret|token|api[_-]?key|apikey|credential|auth|private[_-]?key|"
    r"session[_-]?token|cookie|bearer|card|cvc|pin)",
    re.I,
)

#: A value that looks like a credential regardless of its key name.
SENSITIVE_VALUE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
    r"xox[abprs]-[A-Za-z0-9\-]{10,}|inf_[A-Za-z0-9]{16,}|-----BEGIN [A-Z ]*PRIVATE KEY)"
)

MAX_TEXT = 400


def _home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def _log_dir() -> Path:
    d = _home() / "logs" / "tool-audit"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def _redact(value: Any, depth: int = 0) -> Any:
    """Key names and shapes only. Never a value that could be a credential."""
    if depth > 4:
        return "…"
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:40]:
            if SENSITIVE_KEY.search(str(k)):
                out[str(k)] = "<redacted>"
            else:
                out[str(k)] = _redact(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_redact(v, depth + 1) for v in list(value)[:20]]
    text = str(value)
    if SENSITIVE_VALUE.search(text):
        return "<redacted:credential-shaped>"
    return text[:MAX_TEXT] + ("…" if len(text) > MAX_TEXT else "")


def _write(record: Dict[str, Any]) -> None:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = _log_dir() / f"{day}.jsonl"
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# --- hooks ------------------------------------------------------------------

def on_pre_tool_call(tool_name: str, args: Dict[str, Any], task_id: str):
    """Record the intent BEFORE the call, so a crash still leaves evidence of it."""
    try:
        _write({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "phase": "pre",
            "task": task_id,
            "tool": tool_name,
            "args": _redact(args),
        })
    except Exception:  # noqa: BLE001 - a logging hook must never break a tool call
        pass
    return None


def on_post_tool_call(tool_name: str, args: Dict[str, Any], result: str,
                      task_id: str, duration_ms: int):
    """Record the outcome: length and digest, not the payload."""
    try:
        text = result if isinstance(result, str) else str(result)
        _write({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "phase": "post",
            "task": task_id,
            "tool": tool_name,
            "ms": duration_ms,
            "result_bytes": len(text.encode("utf-8", "replace")),
            "result_sha256": _digest(text),
            "result_head": _redact(text[:MAX_TEXT]),
        })
    except Exception:  # noqa: BLE001
        pass
    return None


# --- tools ------------------------------------------------------------------

def _audit(params: Dict[str, Any], **kwargs) -> str:
    """Query the durable tool-call record, and report the skill catalog's completeness."""
    action = (params.get("action") or "status").strip().lower()

    if action == "status":
        days = sorted(_log_dir().glob("*.jsonl"))
        today = days[-1] if days else None
        entries = 0
        if today:
            with today.open(encoding="utf-8", errors="replace") as fh:
                entries = sum(1 for _ in fh)
        return json.dumps({
            "log_dir": str(_log_dir()),
            "days_recorded": len(days),
            "latest": today.name if today else None,
            "entries_today": entries,
            "writable": os.access(_log_dir(), os.W_OK),
            "note": "every tool call is recorded pre and post; results are digested, not stored",
        }, indent=2)

    if action == "recent":
        limit = max(1, min(int(params.get("limit") or 20), 200))
        days = sorted(_log_dir().glob("*.jsonl"))
        if not days:
            return json.dumps({"entries": [], "note": "no audit log yet"}, indent=2)
        lines: List[str] = []
        for path in reversed(days):
            with path.open(encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()[-limit:]
            if len(lines) >= limit:
                break
        out = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"error": "unparseable line", "raw": line[:120]})
        return json.dumps({"entries": out}, indent=2)

    if action == "catalog":
        return json.dumps(_catalog_report(), indent=2)

    return json.dumps({
        "error": f"unknown action {action!r}",
        "actions": ["status", "recent", "catalog"],
    }, indent=2)


def _external_dirs() -> tuple[List[Path], List[str], List[str]]:
    """`skills.external_dirs`, with the reason recorded when it cannot be read.

    PyYAML is not guaranteed in every interpreter this plugin may run under, and the
    first version of this function wrapped the import in a bare `except: pass` — which
    silently dropped the mounted library and reported a smaller catalog as if it were
    complete. That is the exact failure this plugin exists to prevent, so the fallback
    is explicit and its outcome is reported.
    """
    warnings: List[str] = []
    errors: List[str] = []
    cfg = _home() / "config.yaml"
    if not cfg.is_file():
        return [], warnings, errors

    text = ""
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError as exc:
        return [], warnings, [f"{cfg}: {exc}"]

    try:
        import yaml  # noqa: PLC0415

        data = yaml.safe_load(text) or {}
        dirs = [Path(os.path.expanduser(str(d)))
                for d in ((data.get("skills") or {}).get("external_dirs") or [])]
        return dirs, warnings, errors
    except ImportError:
        warnings.append("PyYAML unavailable; parsed skills.external_dirs by hand")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"config.yaml did not parse ({exc}); parsed by hand")

    # Hand parser: only the `skills:` block's `external_dirs:` list, and only because
    # the alternative is reporting an incomplete catalog as complete.
    dirs = []
    in_skills = False
    in_dirs = False
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if re.match(r"^skills:\s*$", raw):
            in_skills, in_dirs = True, False
            continue
        if in_skills and re.match(r"^\S", raw):
            break
        if in_skills and re.match(r"^\s+external_dirs:\s*$", raw):
            in_dirs = True
            continue
        if in_dirs:
            m = re.match(r"^\s+-\s*(\S+)\s*$", raw)
            if m:
                dirs.append(Path(os.path.expanduser(m.group(1))))
            else:
                break
    if not dirs and "external_dirs" in text:
        errors.append("skills.external_dirs is present in config.yaml but could not be read")
    return dirs, warnings, errors


def _catalog_report() -> Dict[str, Any]:
    """Complete, or incomplete-with-a-reason — never a silently shorter list.

    A skill directory that cannot be read is the failure this exists to make visible:
    it produces fewer entries, which reads exactly like "those skills are not
    installed".
    """
    roots: List[Path] = []
    own = _home() / "skills"
    if own.is_dir():
        roots.append(own)

    external, warnings, errors = _external_dirs()
    for path in external:
        if path.is_dir():
            roots.append(path)
        else:
            errors.append(f"external_dirs entry is not a directory: {path}")

    skills: List[Dict[str, Any]] = []
    unreadable: List[str] = []
    malformed: List[str] = []
    gated: List[Dict[str, str]] = []

    for root in roots:
        for skill_md in sorted(root.rglob("SKILL.md")):
            if any(p in {"references", "templates", "assets", "scripts"}
                   for p in skill_md.parts):
                continue
            try:
                text = skill_md.read_text(encoding="utf-8")
            except OSError as exc:
                unreadable.append(f"{skill_md}: {exc}")
                continue
            if not text.startswith("---"):
                malformed.append(str(skill_md))
                continue
            head = text.split("---", 2)[1]
            env = re.search(r"^environments:\s*\[?([^\]\n]+)\]?", head, re.M)
            plat = re.search(r"^platforms:\s*\[?([^\]\n]+)\]?", head, re.M)
            name = re.search(r"^name:\s*(\S+)", head, re.M)
            row = {
                "name": name.group(1) if name else skill_md.parent.name,
                "path": str(skill_md),
            }
            if env:
                row["environments"] = env.group(1).strip()
                gated.append({"name": row["name"], "environments": row["environments"]})
            if plat:
                row["platforms"] = plat.group(1).strip()
            skills.append(row)

    return {
        "complete": not unreadable and not malformed and not errors,
        "roots": [str(r) for r in roots],
        "skill_count": len(skills),
        "environment_gated": gated,
        "unreadable": unreadable,
        "malformed_frontmatter": malformed,
        "warnings": warnings,
        "incomplete_because": errors,
        "skills": skills,
    }


def register(ctx):
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("post_tool_call", on_post_tool_call)

    ctx.register_tool(
        name="harness_audit",
        toolset="harness_audit",
        schema={
            "name": "harness_audit",
            "description": (
                "Read the durable record of tool calls this profile has made, and report "
                "whether the skill catalog is complete. Actions: 'status' (log location "
                "and today's count), 'recent' (last N entries, each with the tool, its "
                "redacted arguments, duration, result size and a digest — never the "
                "result text), 'catalog' (every discovered skill plus any directory that "
                "could not be read, which is otherwise indistinguishable from a skill "
                "that is not installed)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "recent", "catalog"],
                        "description": "Which report to return. Default: status.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "For 'recent': how many entries, 1-200. Default 20.",
                    },
                },
                "required": [],
            },
        },
        handler=_audit,
    )
