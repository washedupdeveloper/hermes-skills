"""A tiny tool, present so the fixture target has a python stack too."""
from __future__ import annotations

import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def summarise(rows: list[dict]) -> dict:
    return {"count": len(rows), "total": sum(r.get("n", 0) for r in rows)}


def main() -> int:
    data = load(Path("input.json"))
    print(json.dumps(summarise(data.get("rows", []))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
