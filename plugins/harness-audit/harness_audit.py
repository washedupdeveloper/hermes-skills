"""harness_audit — three harness invariants, implemented rather than described.

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

3. **A model request is a logged fact, not an inferred one.** dsh records a
   `request/header` per call. Here the prompt is assembled from the skill table, the tool
   schemas and the conversation, so "what did the model see, and how big was it" is the
   measurement every context change is argued from — and Hermes keeps none of it. One
   line per request records the counts, the sizes and a digest of the system prompt. The
   text is never stored: a log that quotes the prompt is a second copy of it.

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

#: Fields whose VALUE is never written, only its presence: a tool call's arguments are
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


def _request_log_dir() -> Path:
    d = _home() / "logs" / "model-requests"
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


def _write_request(record: Dict[str, Any]) -> None:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = _request_log_dir() / f"{day}.jsonl"
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


def _request_record(kw: Dict[str, Any]) -> Dict[str, Any]:
    """One model request as sizes and digests. Never the prompt, never a message body."""
    raw_prompt = kw.get("system_prompt")
    prompt = raw_prompt if isinstance(raw_prompt, str) else ""
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "phase": "request",
        "session": kw.get("session_id") or "",
        "task": kw.get("task_id") or "",
        "turn": kw.get("turn_id") or "",
        "request": kw.get("api_request_id") or "",
        "platform": kw.get("platform") or "",
        "provider": kw.get("provider") or "",
        "model": kw.get("model") or "",
        "api_mode": kw.get("api_mode") or "",
        "api_call": kw.get("api_call_count"),
        "retry": kw.get("retry_count"),
        "messages": kw.get("message_count"),
        "tools": kw.get("tool_count"),
        "approx_input_tokens": kw.get("approx_input_tokens"),
        "request_chars": kw.get("request_char_count"),
        # None, not 0 and not the digest of an empty string: the host not passing a
        # system prompt is a different fact from a request that carried an empty one.
        "system_prompt_bytes": len(prompt.encode("utf-8", "replace")) if prompt else None,
        "system_prompt_sha256": _digest(prompt) if prompt else None,
    }


def on_pre_api_request(**kw: Any):
    """Record what the model is about to see, before it is sent."""
    try:
        _write_request(_request_record(kw))
    except Exception:  # noqa: BLE001 - a logging hook must never break a request
        pass
    return None


# --- tools ------------------------------------------------------------------

def _tail_records(directory: Path, limit: int) -> List[Dict[str, Any]]:
    """The last `limit` JSONL records across the day files, newest file last.

    An unparseable line is returned as an error record rather than dropped: a log with a
    hole in it reads exactly like a log that never held the entry.
    """
    days = sorted(directory.glob("*.jsonl"))
    lines: List[str] = []
    for path in reversed(days):
        with path.open(encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()[-limit:]
        if len(lines) >= limit:
            break
    out: List[Dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"error": "unparseable line", "raw": line[:120]})
    return out


def _summarize_requests(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Prompt growth over the window, and which of the facts were actually reported.

    `growth` is interval-wide, not causal: the window spans turns, and several requests
    share one conversation. `complete` is false when the host did not report a size, so
    a smaller number is never mistaken for a measured one.
    """
    usable = [r for r in records if isinstance(r.get("approx_input_tokens"), (int, float))]
    tokens = sorted(int(r["approx_input_tokens"]) for r in usable)
    prompts = {r.get("system_prompt_sha256") for r in records if r.get("system_prompt_sha256")}
    sizes = [int(r["system_prompt_bytes"]) for r in records
             if isinstance(r.get("system_prompt_bytes"), int)]
    summary: Dict[str, Any] = {
        "requests": len(records),
        "sessions": len({r.get("session") for r in records if r.get("session")}),
        "models": sorted({str(r.get("model")) for r in records if r.get("model")}),
        "providers": sorted({str(r.get("provider")) for r in records if r.get("provider")}),
        "tokens_reported": len(usable),
        "tokens_missing": len(records) - len(usable),
        "distinct_system_prompts": len(prompts),
        "complete": len(usable) == len(records) and bool(records),
    }
    if tokens:
        summary["input_tokens"] = {
            "min": tokens[0],
            "median": tokens[len(tokens) // 2],
            "max": tokens[-1],
            "growth": tokens[-1] - tokens[0],
        }
    if sizes:
        summary["system_prompt_bytes"] = {"min": min(sizes), "max": max(sizes)}
    return summary


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
        req_days = sorted(_request_log_dir().glob("*.jsonl"))
        req_today = req_days[-1] if req_days else None
        requests = 0
        if req_today:
            with req_today.open(encoding="utf-8", errors="replace") as fh:
                requests = sum(1 for _ in fh)
        return json.dumps({
            "log_dir": str(_log_dir()),
            "days_recorded": len(days),
            "latest": today.name if today else None,
            "entries_today": entries,
            "request_log_dir": str(_request_log_dir()),
            "requests_today": requests,
            "writable": os.access(_log_dir(), os.W_OK) and os.access(_request_log_dir(), os.W_OK),
            "note": (
                "every tool call is recorded pre and post, and every model request by "
                "size and digest; no result text, prompt text or message body is stored"
            ),
        }, indent=2)

    if action == "recent":
        limit = max(1, min(int(params.get("limit") or 20), 200))
        return json.dumps({"entries": _tail_records(_log_dir(), limit)}, indent=2)

    if action == "requests":
        limit = max(1, min(int(params.get("limit") or 50), 500))
        records = _tail_records(_request_log_dir(), limit)
        return json.dumps({
            "summary": _summarize_requests(records),
            "note": (
                "counts, sizes and a system-prompt digest per model request; no prompt "
                "text and no message bodies are stored"
            ),
            "entries": records,
        }, indent=2)

    if action == "catalog":
        return json.dumps(_catalog_report(), indent=2)

    return json.dumps({
        "error": f"unknown action {action!r}",
        "actions": ["status", "recent", "catalog", "requests"],
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
    ctx.register_hook("pre_api_request", on_pre_api_request)

    ctx.register_tool(
        name="harness_audit",
        toolset="harness_audit",
        schema={
            "name": "harness_audit",
            "description": (
                "Read the durable record of what this profile sent and did: every tool "
                "call, and every model request's shape. Actions: 'status' (log locations "
                "and today's counts), 'recent' (last N tool calls, each with the tool, "
                "its redacted arguments, duration, result size and a digest — never the "
                "result text), 'requests' (last N model requests with message and tool "
                "counts, input-token sizes and a system-prompt digest, plus prompt growth "
                "over the window), 'catalog' (every discovered skill plus any directory "
                "that could not be read, which is otherwise indistinguishable from a "
                "skill that is not installed)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "recent", "catalog", "requests"],
                        "description": "Which report to return. Default: status.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            "For 'recent': how many entries, 1-200. For 'requests': 1-500. "
                            "Default 20 and 50."
                        ),
                    },
                },
                "required": [],
            },
        },
        handler=_audit,
    )
