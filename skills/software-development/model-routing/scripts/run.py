#!/usr/bin/env python3
"""Run the selector from a checkout or an installed skill directory."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from surplus_select.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())