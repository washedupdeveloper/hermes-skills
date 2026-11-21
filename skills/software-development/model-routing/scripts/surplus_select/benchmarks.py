"""Benchmark cache: coding, reasoning and agentic scores, with provenance.

The public boards disagree, so the selector keeps them side by side and never
averages them into one score. Scores are cached for 30 days; a score older than
that is shown with its date and does not silently drive a role choice.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .providers import Http, ProviderError, UrllibHttp

BENCHLM_CODING = "https://benchlm.ai/coding"
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "assets" / "benchmarks.json"


@dataclass(frozen=True, slots=True)
class Benchmark:
    coding: float | None = None
    overall: float | None = None
    hle: float | None = None
    frontier_math: float | None = None
    agentic: float | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class BenchmarkCache:
    source: str
    fetched_at: datetime
    models: dict[str, Benchmark] = field(default_factory=dict)

    def age_days(self, now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        fetched = self.fetched_at
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        return (now - fetched).total_seconds() / 86400

    def get(self, model_id: str) -> Benchmark | None:
        return self.models.get(model_id)


def _to_dict(cache: BenchmarkCache) -> dict:
    return {
        "source": cache.source,
        "fetched_at": cache.fetched_at.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "models": {
            key: {
                name: value
                for name, value in {
                    "coding": item.coding,
                    "overall": item.overall,
                    "hle": item.hle,
                    "frontier_math": item.frontier_math,
                    "agentic": item.agentic,
                    "note": item.note or None,
                }.items()
                if value is not None
            }
            for key, item in sorted(cache.models.items())
        },
    }


def load(path: str | Path | None = None) -> BenchmarkCache:
    source = Path(path) if path else DEFAULT_PATH
    if not source.is_file():
        raise FileNotFoundError(f"no benchmark cache at {source}")
    data = json.loads(source.read_text(encoding="utf-8"))
    fetched = datetime.fromisoformat(str(data["fetched_at"]))
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    models = {}
    for key, value in (data.get("models") or {}).items():
        models[key] = Benchmark(
            coding=value.get("coding"),
            overall=value.get("overall"),
            hle=value.get("hle"),
            frontier_math=value.get("frontier_math"),
            agentic=value.get("agentic"),
            note=str(value.get("note", "")),
        )
    return BenchmarkCache(
        source=str(data.get("source", source)),
        fetched_at=fetched,
        models=models,
    )


def save(cache: BenchmarkCache, path: str | Path | None = None) -> None:
    target = Path(path) if path else DEFAULT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_to_dict(cache), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _balanced_array(text: str, start: int) -> list | None:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        else:
            if char == '"':
                in_string = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : index + 1])
                    except json.JSONDecodeError:
                        return None
    return None


def parse_benchlm_coding(markup: str) -> dict[str, Benchmark]:
    """Read the model arrays BenchLM embeds in its coding page.

    The array shape is positional and has changed before; every read is
    guarded, and an entry that does not fit is skipped rather than guessed.
    """
    models: dict[str, Benchmark] = {}
    for match in re.finditer(r'\[(\d{1,4}),"[A-Za-z0-9]', markup):
        item = _balanced_array(markup, match.start())
        if not item or len(item) < 20:
            continue
        try:
            if item[4] not in ("Open Weight", "Proprietary"):
                continue
            slug = str(item[2])
            coding = item[-3]
            overall = item[14]
            if not isinstance(coding, (int, float)):
                continue
            models[slug] = Benchmark(
                coding=float(coding),
                overall=float(overall) if isinstance(overall, (int, float)) else None,
                note=f"BenchLM coding, {item[1]}",
            )
        except (IndexError, TypeError, ValueError):
            continue
    return models


def refresh(cache: BenchmarkCache, http: Http | None = None) -> BenchmarkCache:
    client = http or UrllibHttp()
    try:
        markup = client.get(BENCHLM_CODING, timeout=45.0)
    except ProviderError:
        raise
    fresh = parse_benchlm_coding(markup)
    if len(fresh) < 20:
        raise ProviderError(
            f"BenchLM returned only {len(fresh)} ranked rows; the page shape changed"
        )
    merged = dict(cache.models)
    for slug, benchmark in fresh.items():
        old = merged.get(slug)
        if old is None:
            merged[slug] = benchmark
        else:
            merged[slug] = Benchmark(
                coding=benchmark.coding,
                overall=benchmark.overall or old.overall,
                hle=old.hle,
                frontier_math=old.frontier_math,
                agentic=old.agentic,
                note=benchmark.note,
            )
    return BenchmarkCache(
        source="BenchLM coding + cached reasoning rows",
        fetched_at=datetime.now(timezone.utc),
        models=merged,
    )