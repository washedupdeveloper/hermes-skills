"""Emit a selected model into a Hermes profile, changing only model keys."""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .model import Snapshot
from .portfolio import Portfolio


class ProfileError(ValueError):
    """The profile could not be emitted without guessing."""


@dataclass(frozen=True, slots=True)
class ProfileChange:
    role: str
    path: Path
    before: str
    after: str
    diff: str
    backup: Path | None = None
    changed: bool = False
    created: bool = False
    command: str = ""


def profile_name(role: str) -> str:
    return "builder-baseline" if role == "builder" else f"council-{role}"


def profile_path(profiles_dir: Path, role: str) -> Path:
    return profiles_dir / profile_name(role) / "config.yaml"


def _value(text: str) -> str:
    return text if re.fullmatch(r"[A-Za-z0-9_.:/@+-]+", text) else json.dumps(text)


def _provider(snapshot: Snapshot) -> str:
    host = urlsplit(snapshot.base_url).hostname or snapshot.provider
    return f"custom:{host}"


def patch_model(text: str, *, model: str, provider: str, base_url: str,
                reasoning: str | None = None) -> str:
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines)
                  if re.match(r"^model:\s*(?:#.*)?$", line)), None)
    if start is None:
        raise ProfileError("config has no top-level model: block")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace():
            end = index
            break
    block = lines[start + 1:end]
    values = {"default": model, "provider": provider, "base_url": base_url}
    if reasoning is not None:
        values["reasoning_effort"] = reasoning
    keyed = []
    for line in block:
        match = re.match(r"^(\s+)([A-Za-z_][A-Za-z0-9_]*):(\s*)(.*?)(\s+#.*)?$", line)
        if match:
            keyed.append((line, match))
    child_indent = min((len(match.group(1)) for _, match in keyed), default=2)
    seen: set[str] = set()
    out: list[str] = []
    for line in block:
        match = next((match for candidate, match in keyed if candidate is line), None)
        if (match and len(match.group(1)) == child_indent
                and match.group(2) in values):
            key = match.group(2)
            seen.add(key)
            out.append(f"{match.group(1)}{key}: {_value(values[key])}{match.group(5) or ''}")
        else:
            out.append(line)
    for key, value in values.items():
        if key not in seen:
            out.append(f"{' ' * child_indent}{key}: {_value(value)}")
    rebuilt = lines[:start + 1] + out + lines[end:]
    return "\n".join(rebuilt) + ("\n" if text.endswith("\n") else "")


def _backup(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = path.with_name(f"{path.name}.bak-{stamp}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.bak-{stamp}-{counter}")
        counter += 1
    return candidate


def _command(name: str) -> str:
    return (f'hermes profile create {name} --no-skills --no-alias '
            f'--description "council {name} profile"')


def _create(name: str, home: Path, hermes_bin: str | None) -> None:
    binary = hermes_bin or shutil.which("hermes")
    if not binary:
        raise ProfileError(f"cannot create {name}: hermes is not on PATH")
    env = dict(os.environ)
    env["HERMES_HOME"] = str(home)
    try:
        subprocess.run(
            [binary, "profile", "create", name, "--no-skills", "--no-alias",
             "--description", f"council {name} profile"],
            check=True, capture_output=True, text=True, env=env,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise ProfileError(f"cannot create {name}: {detail.strip()}") from exc


def emit(portfolio: Portfolio, snapshot: Snapshot, profiles_dir: Path, *,
         create: bool = False, dry_run: bool = False, force: bool = False,
         reasoning: str | None = None, ambient: Path | None = None,
         hermes_bin: str | None = None) -> list[ProfileChange]:
    profiles_dir = profiles_dir.expanduser()
    home = profiles_dir.parent
    targets = [(role, profile_path(profiles_dir, role.name)) for role in portfolio.roles]
    missing = [(role, path) for role, path in targets if not path.is_file()]
    if missing and not create:
        commands = "\n".join(_command(profile_name(role.name)) for role, _ in missing)
        raise ProfileError(f"missing profile(s):\n{commands}")
    if ambient is not None:
        target = Path(ambient).expanduser().resolve()
        for _role, path in targets:
            if path.resolve() == target and not force:
                raise ProfileError("refusing to rewrite the ambient profile; pass --force")
    changes: list[ProfileChange] = []
    for role, path in targets:
        was_missing = not path.is_file()
        if was_missing and create and not dry_run:
            _create(profile_name(role.name), home, hermes_bin)
        if not path.is_file():
            changes.append(ProfileChange(
                role=role.name, path=path, before="", after="", diff="",
                changed=False, created=False, command=_command(profile_name(role.name)),
            ))
            continue
        before = path.read_text(encoding="utf-8")
        after = patch_model(before, model=role.model_id, provider=_provider(snapshot),
                            base_url=snapshot.base_url, reasoning=reasoning)
        diff = "".join(difflib.unified_diff(
            before.splitlines(True), after.splitlines(True),
            fromfile=str(path), tofile=str(path)))
        backup: Path | None = None
        if not dry_run and after != before:
            backup = _backup(path)
            backup.write_text(before, encoding="utf-8")
            temporary = path.with_name(f".{path.name}.tmp")
            temporary.write_text(after, encoding="utf-8")
            os.replace(temporary, path)
        changes.append(ProfileChange(
            role=role.name, path=path, before=before, after=after,
            diff=diff, backup=backup, changed=after != before,
            created=was_missing and path.is_file(),
        ))
    return changes
