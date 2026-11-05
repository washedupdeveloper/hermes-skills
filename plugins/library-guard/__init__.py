"""Directory-drop entry for the library-guard plugin.

Hermes loads a directory plugin by file path and sets ``__path__`` to the plugin directory, so a
RELATIVE import resolves to the sibling module. An absolute ``from library_guard import …`` fails
with ``No module named 'library_guard'`` and the plugin is skipped with one warning in
``logs/errors.log`` — the trap this file exists to avoid.
"""
from .library_guard import register  # noqa: F401

__all__ = ["register"]