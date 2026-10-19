"""Directory-drop entry for the harness-audit plugin.

Hermes loads a directory plugin by file path and sets ``__path__`` to the plugin
directory, so a relative import resolves to the sibling module. The implementation lives
in ``harness_audit.py`` because that file is also the pip/Nix distribution (see
``pyproject.toml`` and ``nix/plugin.nix``) — one copy of the code, two ways to install it.
"""
from .harness_audit import register  # noqa: F401

__all__ = ["register"]
