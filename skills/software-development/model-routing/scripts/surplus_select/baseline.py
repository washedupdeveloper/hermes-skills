"""Resolve the ambient model: the one the host is already running.

The baseline is not a recommendation. It is a fact read from the active
profile, and every decision records where it came from. If it cannot be
resolved the selector stops rather than inventing a default.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


class BaselineError(RuntimeError):
    """No baseline could be resolved from a flag, the environment or a profile."""


@dataclass(frozen=True, slots=True)
class Baseline:
    model: str
    source: str


def read_model_default(config_path: str | Path) -> str | None:
    """Return `model.default` from a Hermes profile config.

    Reads only the `model:` block at the top level. A profile that stores the
    model under `model.model` is accepted too; both spellings are documented.
    """
    path = Path(config_path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    in_model = False
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace():
            in_model = line.split(":", 1)[0].strip() == "model"
            continue
        if not in_model:
            continue
        match = re.match(r"\s+(default|model)\s*:\s*(.+?)\s*$", line)
        if match:
            value = match.group(2).split("#", 1)[0].strip().strip("\"'")
            return value or None
    return None


def resolve(
    explicit: str | None = None,
    env_var: str | None = None,
    profile_config: str | Path | None = None,
) -> Baseline:
    if explicit:
        return Baseline(explicit, "flag")
    env_value = env_var if env_var is not None else os.environ.get("SURPLUS_BASELINE_MODEL")
    if env_value:
        return Baseline(env_value, "environment")
    if profile_config:
        model = read_model_default(profile_config)
        if model:
            return Baseline(model, f"profile:{Path(profile_config)}")
    raise BaselineError(
        "cannot determine the baseline; pass --baseline, set "
        "SURPLUS_BASELINE_MODEL, or point --profile-config at an active profile"
    )


def active_profile_config(hermes_home: str | Path, profile: str | None = None) -> Path:
    home = Path(hermes_home)
    if profile:
        return home / "profiles" / profile / "config.yaml"
    return home / "config.yaml"